# io_uring Subsystem Details

## Zero-Copy Lifetime Management

Buffer references (`struct io_rsrc_node`) must attach to `notif` (`sr->notif`), NOT `req`. `req` completes before the network layer finishes; `notif` is released only when transmission finishes via `io_tx_ubuf_complete()`.

- `io_import_reg_buf(sr->notif, ...)` — correct
- `io_import_reg_vec(ITER_SOURCE, &iter, sr->notif, ...)` — correct
- Passing `req` instead of `sr->notif` — **bug**

**Notification flush**: `io_notif_flush()` drops the notif reference; calling it twice is use-after-free. Always set `zc->notif = NULL` immediately after flush.

**REPORT**: `req` passed where `sr->notif` required; `io_notif_flush()` not followed by NULL assignment.

## REQ_F_NEED_CLEANUP and Cleanup Flag Safety

Set `REQ_F_NEED_CLEANUP` *immediately after* any allocation whose release depends on the opcode cleanup handler. No early return may exist between allocation and flag-setting. Clear only after confirming the resource was recycled or freed (inside the `io_alloc_cache_put()` success branch, not unconditionally).

**REPORT**: Flag set after a path that can return early; unconditional clearing before confirming recycle/free.

## Async Data Lifecycle

`req->async_data` and `REQ_F_ASYNC_DATA` must always be in sync.

- Allocate: `io_uring_alloc_async_data(cache, req)` (sets flag on success)
- Free: `io_req_async_data_free(req)` (clears pointer + flag)
- Cache-return: `io_req_async_data_clear(req, extra_flags)`
- Never manually assign `req->async_data` or `kfree()` it directly
- Allocate in `prep`, not `issue` — data must exist before retry or cancellation

**REPORT**: Manual `req->async_data` assignment without flag; direct `kfree(req->async_data)`; allocation in `issue` for cancellable ops.

## SQE Data Stability for uring_cmd

`ioucmd->sqe` points to the ring slot; it becomes stale on async punt. `io_uring_cmd_sqe_copy()` copies SQE into `ac->sqes` and sets `REQ_F_SQE_COPIED` to prevent double-copy. SQE fields needed at issue must be cached during prep with `READ_ONCE()` (e.g., `ioucmd->cmd_op = READ_ONCE(sqe->cmd_op)`); issue code must use cached values, not `cmd->sqe->`.

**REPORT**: `ioucmd->sqe` accessed after async punt without copy; issue code reading through `cmd->sqe->` instead of cached values.

## CQE Sizing Modes: CQE32 vs CQE_MIXED

The `cqe32` parameter to `io_get_cqe()` / `io_get_cqe_overflow()` means "mixed-mode per-CQE 32B entry needing extra advancement," NOT "this CQE is 32 bytes." Derive it from per-CQE `IORING_CQE_F_32`, not ring-level `IORING_SETUP_CQE32`.

| Ring mode | `cqe32` param |
|---|---|
| `IORING_SETUP_CQE32` | `false` (ring doubles slots internally) |
| `IORING_SETUP_CQE_MIXED` + `IORING_CQE_F_32` | `true` |
| `IORING_SETUP_CQE_MIXED` w/o flag, or default | `false` |

**REPORT**: `cqe32=true` based on `IORING_SETUP_CQE32` rather than `IORING_CQE_F_32`.

## Multishot and CQE Posting

- `io_req_post_cqe()` requires task_work context with `uring_lock` held, never io-wq. Callers must have `REQ_F_MULTISHOT` or `REQ_F_APOLL_MULTISHOT` set.
- Check `issue_flags & IO_URING_F_MULTISHOT` (executing in multishot context) before returning multishot status codes like `IOU_STOP_MULTISHOT`.
- Multishot handlers must not return `-EAGAIN` for io-wq punt.
- Call `io_kbuf_recycle()` before returning to poll waiting.

**REPORT**: `io_req_post_cqe()` without multishot flag; multishot status without `IO_URING_F_MULTISHOT` check; multishot handler returning `-EAGAIN`.

## Provided Buffer Ring Semantics

`buf_ring` is in userspace-shared memory. All `buf->len`, `buf->addr`, `buf->bid` reads must use `READ_ONCE()`; writes use `WRITE_ONCE()`. Legacy `struct io_buffer` (kernel-only) needs no annotations.

- `io_should_commit()`: always auto-commit for `IO_URING_F_UNLOCKED` and non-pollable/non-uring_cmd; pollable or `IORING_OP_URING_CMD` skip (commits explicitly). New opcodes with explicit commit must be exempted.
- Capture `buf->addr` before `io_kbuf_commit()`.
- On partial completion: commit via `io_kbuf_commit()` and set `REQ_F_BL_NO_RECYCLE`.
- `io_kbuf_inc_commit()` must terminate on zero-length buffers.

**REPORT**: `buf_ring` field access without `READ_ONCE()`/`WRITE_ONCE()`; explicit-commit opcode not exempted in `io_should_commit()`; `REQ_F_BL_NO_RECYCLE` set without committing.

## Registered Buffer Management

- Never assume `imu->ubuf` is page-aligned. Use `imu->bvec[0].bv_offset` for sub-folio offset:
  ```c
  offset = buf_addr - imu->ubuf;
  offset += imu->bvec[0].bv_offset;  // CORRECT
  ```
- During registration with folio coalescing, `data.first_folio_page_idx << PAGE_SHIFT` accounts for first page position within its folio.
- Use `unpin_user_folio()`, never `unpin_user_page()` — buffers are pinned per-folio after coalescing.

**REPORT**: Offset derived by address masking instead of `bv_offset`; `unpin_user_page()` in io_uring buffer code.

## msg_ring Cross-Ring Request Lifetime

`io_msg_data_remote()` allocates `io_kiocb` via `kmem_cache_alloc()` for a remote ring. Free via `kfree_rcu(req, rcu_head)` only — never `kmem_cache_free()`, `kfree()`, or `io_alloc_cache`. Set `req->tctx = NULL` on remote requests (submitter may exit).

**REPORT**: msg_ring request in `io_alloc_cache`; freed without `kfree_rcu()`; non-NULL `req->tctx`.

## SQPOLL Thread Safety

`sqd->thread` is `__rcu`-annotated. Bare access causes use-after-free.

- Under `sqd->lock`: `sqpoll_task_locked(sqd)`
- Under RCU: `rcu_dereference(sqd->thread)`
- Assignment: `rcu_assign_pointer(sqd->thread, tsk)`
- For signaling: use `req->tctx->task`, not `sqd->thread`
- After `wake_up_new_task()` in `io_sq_offload_create()`, do NOT call `put_task_struct()`.

**REPORT**: Bare `sqd->thread` read; `put_task_struct()` after thread start; `sqd->thread` used for signaling.

## DEFER_TASKRUN Task Work Draining

With `IORING_SETUP_DEFER_TASKRUN`, task work goes to `ctx->work_llist`. Non-submitter contexts must call `io_move_task_work_from_local()` on **every iteration** of a cancel loop, not just once before it — cancellation generates new work.

**REPORT**: `io_move_task_work_from_local()` called only once before a cancel loop.

## IOPOLL Completion and Reissue

- `io_complete_rw_iopoll()` must always reach `smp_store_release(&req->iopoll_completed, 1)`. No early return.
- Reissue on `-EAGAIN`: set `REQ_F_REISSUE | REQ_F_BL_NO_RECYCLE` and fall through.

**REPORT**: Early return in `io_complete_rw_iopoll()` skipping `iopoll_completed`.

## Timeout Cancellation and Lock Ordering

Completion under `ctx->timeout_lock` (raw spinlock) is invalid on PREEMPT_RT — completion may call `io_eventfd_signal()` which takes a regular spinlock.

Two-phase pattern:
1. Under `timeout_lock`: `io_kill_timeout()` cancels hrtimers, moves to local list only.
2. After unlock: `io_flush_killed_timeouts()` calls `io_req_queue_tw_complete()`.

**REPORT**: Task_work or completion calls while holding `ctx->timeout_lock`.

## Quick Checks

- **Notif before import**: `io_alloc_notif()` must precede buffer import in zero-copy paths.
- **Bundle buffer put**: `io_put_kbufs()` takes current transfer count (`this_ret`), not cumulative total.
- **CQ overflow sentinel**: Set `ctx->cqe_sentinel = ctx->cqe_cached` before dropping CQ lock during overflow flush.
- **zcrx DMA lifecycle**: Create mappings in `io_pp_zc_init()`, unmap in `io_pp_uninstall()`.
- **Registration tags on failure**: Clear `node->tag` via `io_clear_table_tags()` before unregistering a failed all-or-nothing registration.
- **Inflight tracking**: Call `io_req_track_inflight()` in prep for requests needing submitter's `mm`.
- **Task work tokens**: Never fabricate `io_tw_token_t` on stack. Use `io_req_queue_tw_complete()` outside task_work context.
- **Buffer list upgrade**: Destroy old `io_buffer_list` and allocate fresh when upgrading to ring-mapped buffers.
- **Eventfd RCU freeing**: Use `io_eventfd_put()` (calls `call_rcu()`), never `io_eventfd_free()` directly.
- **Cross-ring cloning**: Both rings must share `ctx->user` and `ctx->mm_account`.
- **io_wq NULL after teardown**: `io_queue_iowq()` checks `!tctx->io_wq` and `PF_KTHREAD`.
- **SQE flag hierarchy**: Gate `READ_ONCE(sqe->field)` on the broadest flag covering all variants.
- **SQE fields read before use**: `READ_ONCE()` SQE field into request before using it.
- **RESIZE_RINGS and DEFER_TASKRUN**: `io_register_resize_rings()` requires `IORING_SETUP_DEFER_TASKRUN`; new ring-geometry mutations need same mutual exclusion.
- **Poll event scope**: Generic poll code must not interpret event bits as errors — `POLLERR` signals data availability for some sockets (e.g., `MSG_ERRQUEUE`). Operation-specific interpretation belongs in issue handlers.
