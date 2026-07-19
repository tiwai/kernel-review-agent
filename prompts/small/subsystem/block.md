# Block Layer Subsystem Details

## Queue Freezing Synchronization

Hold a queue freeze during teardown or reconfiguration to prevent use-after-free on queue state. `blk_mq_freeze_queue()` drains `q->q_usage_counter` to zero, blocking new bio submissions; `blk_queue_exit()` releases it.

- `blk_mq_freeze_queue()` returns `unsigned int` (memflags from `memalloc_noio_save()`); callers **must** capture and pass it to `blk_mq_unfreeze_queue()` to prevent reclaim re-entering the block layer.

## Bio Operation Type Safety

Accessing `bi_io_vec` on a no-data bio (discard, flush, etc.) causes NULL dereference. Always check op type before accessing data fields.

| Operation | Has Data |
|-----------|----------|
| `REQ_OP_READ`, `REQ_OP_WRITE` | Yes |
| `REQ_OP_DISCARD`, `REQ_OP_FLUSH`, `REQ_OP_WRITE_ZEROES`, `REQ_OP_SECURE_ERASE` | No |

- **Required guard:** `bio_has_data()` before accessing `bio->bi_io_vec`, `bio->bi_vcnt`, `bio->bi_iter.bi_bvec_done`, or any bio iterator helper (`bio_get_first_bvec()`, `bio_for_each_segment()`, etc.).
- **`op_is_write()` is NOT a valid guard** — it checks bit 0 and returns true for `REQ_OP_DISCARD` (3), `REQ_OP_SECURE_ERASE` (5), and `REQ_OP_WRITE_ZEROES` (9), all of which have no data.

## Bio Mempool Allocation Guarantees

- `bio_alloc()` / `bio_alloc_bioset()` — mempool-backed; cannot fail when `__GFP_DIRECT_RECLAIM` is set (`GFP_NOIO`/`GFP_NOFS`). Failure paths are dead code in those contexts; only reachable with `GFP_NOWAIT`/`GFP_ATOMIC`.
- `bvec_alloc()` — falls back to mempool if slab fails and `__GFP_DIRECT_RECLAIM` is set; cannot fail.
- `bio_integrity_prep()` — mempool with `GFP_NOIO`; always returns `true`.
- `bio_integrity_alloc_buf()` — falls back to `mempool_alloc(GFP_NOFS)`; cannot fail.
- `bio_kmalloc()` — plain `kmalloc()`, **no mempool**. Can fail regardless of GFP flags; always handle the error.

## Elevator `depth_updated` Callback

Signature: `void (*depth_updated)(struct request_queue *)` in `struct elevator_mq_ops`.

- **Timing invariant:** `q->nr_requests` must be written before `depth_updated()` is called (`blk_mq_update_nr_requests()`). Reordering causes all three in-tree elevators to compute limits from stale values.
- **Initialization invariant:** All in-tree elevators call `depth_updated()` at the end of `init_sched()` (`bfq_depth_updated()`, `dd_depth_updated()`, `kyber_depth_updated()`). A new elevator deriving limits from `q->nr_requests` must do the same — omitting it leaves limits at zero until the first sysfs write.

## Quick Checks

- `REQ_OP_ZONE_APPEND` (7) has bit 0 set so `op_is_write()` returns true — unlike DISCARD/WRITE_ZEROES/SECURE_ERASE, it does carry data.
- `bio_alloc_bioset()` can still return NULL with `__GFP_DIRECT_RECLAIM` if `nr_vecs > 0` and the bioset has no bvec pool (triggers `WARN_ON_ONCE`).
