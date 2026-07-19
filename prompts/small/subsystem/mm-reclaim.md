# MM Reclaim, Swap, and Migration

## Writeback Tags

Incorrect tag handling causes data loss or writeback livelock. Tags (`PAGECACHE_TAG_DIRTY/WRITEBACK/TOWRITE`) are XA marks in `include/linux/fs.h`.

**Lifecycle:**
1. `folio_mark_dirty()` sets DIRTY
2. `tag_pages_for_writeback()` copies DIRTY→TOWRITE for data-integrity syncs (prevents livelock from new dirty pages)
3. `folio_start_writeback()` sets WRITEBACK, clears DIRTY and TOWRITE (`keep_write=false`)
4. To preserve TOWRITE: call `__folio_start_writeback(folio, true)`

**Tag selection:** `wbc_to_tag()` returns TOWRITE for `WB_SYNC_ALL`/`tagged_writepages`, DIRTY otherwise. Data-integrity syncs iterate TOWRITE to exclude pages dirtied after sync starts.

## Cgroup Writeback Domain Abstraction

Functions/traces receiving `dirty_throttle_control *dtc` must use `dtc_dom(dtc)`, not `global_wb_domain` directly. `balance_dirty_pages()` selects global or memcg domain based on `pos_ratio`; hardcoding global produces wrong throttling.

**REPORT as bugs:** `global_wb_domain` field access in functions with a `dtc` parameter (except code explicitly targeting global domain like `global_dirty_limits()`).

## Swap Cache Residency

`folio_free_swap()` removes from swap cache only when `folio_swapcache_freeable()` AND `!folio_swapped()`.

- **mTHP swapin conflict:** fails with `-EEXIST` when a subpage slot is occupied by a racing swapin; must fall back to smaller order or retry (see `shmem_swapin_folio()`)
- **ABA problem:** swap entries are recycled. After `swap_cache_get_folio()`, verify `folio_test_swapcache()` and `folio->swap.val` still match. After acquiring PTE lock when lookup returned NULL, check `SWAP_HAS_CACHE` in `si->swap_map[swp_offset(entry)]`

## Swap Device Lifetime

`swapoff()` calls `percpu_ref_kill()` + `synchronize_rcu()` before freeing; access without a ref is use-after-free.

- `get_swap_device(entry)` validates entry and takes percpu_ref; returns NULL if swapping off. Must pair with `put_swap_device(si)`
- `__swap_entry_to_info(entry)` returns pointer WITHOUT reference — only safe with existing ref or under RCU read-side section
- `__read_swap_cache_async()` uses `__swap_entry_to_info()` internally; all callers must hold a device reference
- **Cross-device readahead hazard:** VMA readahead may encounter entries from different devices. Each non-target device entry must be separately pinned with `get_swap_device()` or skipped

## Dual Reclaim Paths: Classic LRU vs MGLRU

MGLRU is runtime-selectable; bugs only manifest when the inactive path is used.

| Classic | MGLRU |
|---------|-------|
| `shrink_inactive_list()` | `evict_folios()` |
| `shrink_active_list()` | `scan_folios()` |

Both call `shrink_folio_list()` but have separate stat updates. Any vmstat counter, memcg event, or tracepoint change in one function requires the corresponding change in its pair.

## MGLRU Generation and Tier Bit Consistency

When a folio moves to a new generation, tier bits (`LRU_REFS_FLAGS = LRU_REFS_MASK | BIT(PG_referenced)`) must be cleared. Stale bits inflate access counts and distort eviction.

All paths updating `LRU_GEN_MASK` must also clear `LRU_REFS_FLAGS`:
`old_flags & ~(LRU_GEN_MASK | LRU_REFS_FLAGS)` (done in `folio_update_gen()` and `folio_inc_gen()`).

`lru_gen_add_folio()` clears `LRU_GEN_MASK | BIT(PG_active)` but NOT `LRU_REFS_FLAGS` — review any code modifying `LRU_GEN_MASK` directly.

## Shmem Folio Cache Residency

`folio_test_swapbacked()` ≠ `folio_test_swapcache()`. Using `swapbacked` as proxy for "in swap cache" is wrong.

| State | `swapbacked` | `swapcache` | `folio->mapping` | xarray |
|-------|-------------|-------------|-------------------|--------|
| Shmem in page cache | true | false | shmem inode | single multi-order entry |
| Shmem in swap cache | true | true | NULL | N individual entries |
| Anon in swap cache | true | true | `anon_vma` | N individual entries |

- `folio_test_swapbacked()`: true for all anon+shmem (page-cache AND swap-cache resident)
- `folio_test_swapcache()`: true only when currently in swap cache

Code choosing between single-entry (page cache) and multi-entry (swap cache) xarray operations must use `folio_test_swapcache()`. See `__folio_migrate_mapping()` in `mm/migrate.c`.

## Memcg Charge Lifecycle

Every `mem_cgroup_charge()` needs a corresponding `mem_cgroup_uncharge()`. On migration, charge transfers via `mem_cgroup_migrate()` — old folio is NOT uncharged separately. `folio_unqueue_deferred_split()` must precede uncharging.

- `folio_memcg()` may return NULL (uncharged) or an offline memcg — use online ancestor from `mem_cgroup_id_get_online()` consistently. Replacing explicit memcg param with `folio_memcg()` causes counter leaks when cgroups are deleted under pressure
- `mem_cgroup_from_id()` is RCU-protected; call `mem_cgroup_tryget()` before `rcu_read_unlock()`
- Destroying a memcg requires `drain_all_stock()` to flush per-CPU charge batches

## Folio Migration and Sleeping Constraints

`folio_mc_copy()` calls `cond_resched()` between pages — safe for order-0 but sleeps for large folios. This makes `filemap_migrate_folio()` / `migrate_folio()` / `__migrate_folio()` sleeping for large folios.

**REPORT as bugs:** `migrate_folio` callbacks in `address_space_operations` that hold a spinlock while calling these. Use non-blocking state flags (e.g., `BH_Migrate`) instead.

## Folio Isolation for Migration

Not every qualifying folio is added to the migration list (device-coherent folios skip it, `folio_isolate_lru()` can fail).

**REPORT as bugs:** using `list_empty()` on a migration list as proxy for "no qualifying items" when collection has early-continue paths. Use an explicit count.

## Quick Checks

- **Bounded LRU iteration under spinlock:** skipping entries without advancing the termination counter creates unbounded scans. Skip paths must advance the counter or have an independent bound (e.g., `SWAP_CLUSTER_MAX_SKIPPED`)
- **Migration lock scope:** if `TTU_RMAP_LOCKED` is passed to `try_to_migrate()`, `i_mmap_rwsem` must stay held until `remove_migration_ptes()` with `RMP_LOCKED`. Dropping between phases causes ABBA deadlock. Anon vs file-backed use different locks
- **kswapd order-dropping:** `kswapd_shrink_node()` drops `sc->order` to 0 after reclaiming `compact_gap(order)` pages. Watermark checks using high-order metrics must test `order != 0`, not a static flag; ignoring the dynamic drop causes massive overreclaim
- **`folio_putback_lru()` after migration:** `mem_cgroup_migrate()` clears source folio's `memcg_data`; calling `folio_putback_lru()` after triggers a memcg assert. Use `folio_put()` for the source folio
- **Swap allocator local lock:** `folio_alloc_swap()` runs under `local_lock()`. No sleeping ops allowed. Silent normally; fires under `CONFIG_DEBUG_PREEMPT`/PREEMPT_RT
- **Zone skip consistency in vmscan:** zone-skip logic must be consistent across `balance_pgdat()`, `pgdat_balanced()`, `allow_direct_reclaim()`, and `skip_throttle_noprogress()`. Mismatch causes `kswapd_failures` to never fire, causing infinite loops in `throttle_direct_reclaim()`
- **Counter-gated tracking list removal:** error paths must check the resource counter before `list_del_init()` — object may already be on the list. Unconditional removal causes iterators to loop forever
- **List iteration with lock drop:** `list_for_each_entry_safe` is unsafe when the lock is dropped mid-iteration. Concurrent `list_del_init()` makes elements self-referential (infinite loop). After reacquiring lock, check `list_empty()` and restart from head (see `shmem_unuse()`)
