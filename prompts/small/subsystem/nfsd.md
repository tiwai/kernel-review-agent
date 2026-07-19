# NFS Server Subsystem

NFSD (fs/nfsd/) implements Linux NFS server (v2/v3/v4.x). Key subsystems: XDR codec, stateid/delegation state machine, file handle validation, client lifecycle, callbacks, session slots.

## File Layout

| Files | Domain |
|-------|--------|
| nfs4xdr.c, nfs3xdr.c | XDR codec |
| nfs4state.c, nfs4proc.c | NFSv4 state, operations |
| nfs3proc.c, nfsproc.c | NFSv2/v3 operations |
| vfs.c, nfsfh.c | VFS interface, file handles |
| nfs4callback.c, nfs4layouts.c | Callbacks, pNFS |
| filecache.c, nfscache.c | File cache, DRC |
| nfs4recover.c | Grace period, reclaim |

## Trust Boundaries

```
XDR decode (untrusted) → fh_verify() → nfs4_preprocess_stateid_op() → VFS (trusted)
```

## XDR Codec

**Decode:** Check `xdr_stream_decode_*()` return before using value. Bounds-check lengths before `kmalloc()`; use `check_mul_overflow()` for `count * sizeof(...)`. Validate array indices (slot indices against `maxreqs`, opnums).

**Encode:**
- Check `xdr_reserve_space()` for NULL; check `xdr_stream_encode_*()` return values.
- Complete irreversible state changes only after encode succeeds (close, revoke, rename cannot retry).
- Copy stateid before `nfs4_put_stid()`, not after.
- Subtract header overhead from client-supplied `maxcount`; reserve space for trailing fields.
- Populate `so_replay`/`rp_buf` only after encode success.

xdrgen code (nfs4xdr_gen.c) has built-in validation. Metadata from `fh_dentry` after `fh_verify()` is trusted.

## Reference Counting

| Counter | Prevents |
|---------|----------|
| `sc_count` | Freeing stateid |
| `cl_nfsdfs.cl_ref` | Freeing nfsdfs object |
| `cl_rpc_users` | Unhashing (incoming RPC compounds, async workers) |
| `cl_cb_inflight` | Client destruction (outgoing callbacks) |

`nfsd4_run_cb()` increments `cl_cb_inflight` internally; `destroy_client()` waits via `nfsd4_shutdown_callback()`. Do not confuse with `cl_rpc_users`.

**Pairs:** `nfs4_get/put_stid`, `nfsd_file_get/put`, `exp_get/put`, `nfsd_net_try_get/put`, `nfs4_get/put_stateowner`.

**Stateowner `so_count`:** Hash/list membership is NOT a counted reference. `alloc_stateowner()` sets `so_count=1` (creation ref to caller). `release_openowner()` consumes exactly one caller ref — do NOT add extra `nfs4_put_stateowner` after it returns.

Assign resources to struct fields only after validation; use temp variables until then.

## File Handle Lifecycle

`fh_dentry`, `fh_export`, `d_inode()` are invalid before `fh_verify()`. `NFSD_MAY_*` flags must match operation (e.g., `MAY_WRITE` for writes). Pass `S_IFREG`/`S_IFDIR` to `fh_verify()` when file type assumed; `0` skips the check.

## NFSv4 Stateid Lifecycle

**Lock per stateid type for `sc_status`:** open/lock → `cl_lock`+`st_mutex`; delegations → `deleg_lock`; layouts → `ls_lock` (spinlock; use `ls_mutex` for sleeping ops).

- Check `sc_status` under lock before state-modifying ops; check-and-modify must be atomic.
- Use `nfs4_inc_and_copy_stateid()` for generation bumps.
- Delegation callbacks: `refcount_inc(&dp->dl_stid.sc_count)` before `nfsd4_run_cb()`.
- CLAIM_DELEG_CUR must verify filehandle via `fh_match()` against `sc_file->fi_fhandle`.
- Before casting `fl_owner` to `nfs4_delegation`, check `fl->fl_lmops == &nfsd_lease_mng_ops`.
- `FMODE_NOCMTIME` valid only for `OPEN_DELEGATE_WRITE_ATTRS_DELEG`.
- Same-client short-circuit must still break other clients' delegations.
- `notify_change()` during `nfs4_unlock_deleg_lease()` needs `ATTR_DELEG` in `ia_valid`.
- TOCTOU in stateid lookup: `find_stateid_locked()` → `mutex_lock(st_mutex)` gap requires `nfsd4_verify_open_stid()` after lock.

## Error Code Mapping

- NFSv3: return `nfsd3_map_status(resp->status)`, not bare `rpc_success`. NFSv2: `nfserrno()`.
- `PTR_ERR()` values must be converted via `nfserrno()` before reaching wire.
- NFSv4-only errors (e.g., `nfserr_delay`) in shared vfs.c/nfsfh.c break v2/v3 paths.
- Do not apply `nfserrno()` to already-converted `__be32` (double mapping).
- Do not convert `EOPENSTALE` directly to `nfserr_stale`; it signals retry needed.
- `NFSERR_INVAL` undefined in NFSv2; `nfserr_file_open` invalid for non-regular files.

## Locking

**Hierarchy (outer → inner):**
```
nn->client_lock → nn->deleg_lock → nn->s2s_cp_lock → fp->fi_lock → clp->cl_lock → stp->st_mutex
```
`nn->nfsd_ssc_lock` is outside hierarchy; never hold with `s2s_cp_lock`.

- `cl_lock` protects: `cl_openowners`, `cl_sessions`, `cl_revoked`, `cl_flags`.
- `client_lock` protects: `cl_time`, `cl_lru`, `cl_idhash`, `grace_ended`.
- `nfs4_put_stid()` under VFS break callback (holding `flc_lock`) may acquire `cl_lock` via `refcount_dec_and_lock()` → deadlock. Use `refcount_dec()` when refcount cannot reach zero.

## Client State Machine

States: `NFSD4_ACTIVE` → `NFSD4_COURTESY` → `NFSD4_EXPIRABLE` → destroyed. `NFSD4_EXPIRABLE` cannot return to ACTIVE; only COURTESY can return on reconnect.

- COURTESY requires laundromat integration (`cl_time` set, timeout checked).
- Admin interfaces (sysfs/procfs) must hold `nfsd_mutex` or check `nn->nfsd_serv`.
- Parent destruction must free child stateids (`release_openowner` must call `nfs4_free_cpntf_statelist()`).

## Grace Period and Lease Management

- Non-reclaim ops (OPEN, LOCK, size-changing SETATTR) return `nfserr_grace` during grace.
- Use `nn->nfsd4_lease`/`nn->nfsd4_grace` for durations, not hardcoded values.
- Use `ktime_get_boottime_seconds()` for `cl_time` (survives suspend/resume).
- Clients never issuing RECLAIM_COMPLETE must be destroyed after grace ends.
- Client records require `nfsd4_client_record_create()` for crash persistence.

## User Namespace ID Conversion

- Use `nfsd_user_namespace(rqstp)` in request paths, not `init_user_ns` or `current_user_ns()`.
- `make_kuid()`/`make_kgid()` results require `uid_valid()`/`gid_valid()`; mapping invalid IDs to `GLOBAL_ROOT_UID` is privilege escalation.
- ACL entries need `from_kuid_munged(ns, ...)` per entry.
- For inter-server socket creation, use `nn->net` not `current->nsproxy->net_ns`.
- Host-only paths (module init, procfs) may use `init_user_ns`.

## Callbacks

- `nfsd4_run_cb()` increments `cl_cb_inflight` internally; callers do NOT increment `cl_rpc_users` for callbacks.
- Check `cl_cb_state == NFSD4_CB_UP` under `cl_lock` before dispatch; access `cl_cb_client` only under same lock.
- `se_cb_seq_nr` modification requires locking; concurrent increment causes BAD_SEQUENCE.
- `cl_cb_session` is NULL for NFSv4.0 clients; check `cl_minorversion > 0` before access.

## Session Slots

- Validate `slotid < se_fchannel.maxreqs` before `xa_load(&session->se_slots, slotid)`.
- Compare request seqid against `sl_seqid` before modification (replay = match, new = +1).
- Replay path must check `same_creds()` before returning cached reply.
- Set `NFSD4_SLOT_INUSE` before compound execution; clear on all exit paths.
- Drain active compounds before freeing slots on teardown; invalidate cached data to prevent use-after-free.

## Page Array Management

- Save `resp->pages = rqstp->rq_next_page` BEFORE read call; reads advance the pointer.
- Loops advancing `rq_next_page` need `rq_next_page < rq_page_end` guard.
- Do not manually sync `page_ptr`/`rq_next_page` in individual NFSv4 ops; `nfsd4_encode_operation()` centralizes this.
- READDIR: set `rqstp->rq_next_page = xdr.page_ptr + 1` after completion.
- Splice: when `page == *(rq_next_page - 1)` and offset not page-aligned, page is continued — don't add again.

## Copy Offload

- IDR removal under `s2s_cp_lock` must precede final put; stale entries allow queries on freed state.
- OFFLOAD_CANCEL needs atomic state transition under lock to prevent race with completion.
- Set `wr_bytes_written`/`wr_stable_how` before `nfsd4_run_cb()`.
- Verify GSS credentials before each chunk in long copies.
- `nfsd4_setup_inter_ssc()` must verify `cnr_stateid` exists, belongs to requesting client, not expired.
- Async copy submission needs per-client or global limits.

## Security Validation

- New branches or early returns before `fh_verify()` bypass validation.
- NFSv4 stateful ops require `nfs4_preprocess_stateid_op()` before file access.
- RENAME/LINK must validate both source and target handles via `fh_verify()`.
- NFSv4 pseudo-filesystem must not be accessible from v2/v3 procedures.

## Netlink Interface

- Every `NFSD_A_*` enum needs a `nla_policy` entry; strings need `NLA_NUL_STRING` with explicit `.len`.
- Don't use `nla_data()` on strings without policy-guaranteed null termination.
- State-modifying handlers need `capable(CAP_NET_ADMIN)` or `ns_capable()`.
- Use `genl_info_net(info)` for network namespace, not `&init_net`.
- Protect `nn->nfsd_serv` checks with `nfsd_mutex` through subsequent modification.

## NFS Re-export

- On NFS superblocks (`s_magic == NFS_SUPER_MAGIC`), embed upstream `NFS_FH()` instead of `i_ino`.
- Don't retry on `-ESTALE` from NFS-backed filesystems.
- Acquire upstream VFS lock before committing local NFSD state.
- Handle both upstream grace (`-EAGAIN`) and local NFSD grace independently.
- Set `exp->ex_fsid`/`exp->ex_uuid` explicitly; device-number-derived values change on remount.

## Resource Limits

- Per-client limits required for: `nfs4_alloc_stid()`, `alloc_init_deleg()`, `create_session()`, async copy queue, work queue items.
- Check limits before allocation; post-allocation check-and-free causes transient OOM.
- `atomic_inc()` on counters before allocation needs matching `atomic_dec()` on all error paths.
- Cap READDIR/GETATTR `maxcount`; limit per-entry cost for ACLs, security labels, idmap lookups.
- COMPOUND dispatch needs upper bound on `args->opcnt`; return `nfserr_resource` when exceeded.

## Code Style

- Reverse-christmas tree variable ordering; `nfs_ok`/`nfserr_*` errors; `cpu_to_be32`/`be32_to_cpu`.
- New NFSv4 XDR code should use nfs4xdr_gen.c (xdrgen).

## Expert Review Triggers

Flag for expert review: XDR primitives; refcount primitives; `fh_verify()` semantics; stateid lifecycle; lock ordering; client state machine or grace period; callback dispatch/completion; session slot/SEQUENCE; new RPC procedure or NFSv4 op; namespace conversion; page array or splice; copy offload lifecycle or S2S auth; genetlink policy; resource limits; re-export/cross-mount; >100 lines touching multiple core files.

## Quick Checks

- `fh_dentry` access without `fh_verify()` → NULL deref
- `nfsd4_run_cb()` without `sc_count` increment for delegations → use-after-free
- `xdr_reserve_space()` return unchecked → NULL deref
- Stateid lookup without `fh_match()` → wrong file access
- `from_kuid()` with `init_user_ns` in request path → container escape
- Lock acquisition violating hierarchy → deadlock
- `sc_status` check/modify not atomic under lock → race
- State change before encode success → corruption on retry
- Session slot index unchecked against `maxreqs` → invalid access
- Async copy IDR removal after final put → stale state queries
