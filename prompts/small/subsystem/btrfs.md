# Btrfs Subsystem Details

## Extent Map Fields

Using the wrong `extent_map` field causes silent data corruption. Fields diverge only with compression or partial references (reflinks); for simple uncompressed extents `len`, `ram_bytes`, and `disk_num_bytes` are equal.

Fields in `fs/btrfs/extent_map.h`:
- `start`: file offset
- `len`: file bytes covered by this extent map (`num_bytes` on disk)
- `disk_bytenr`: physical byte address (`EXTENT_MAP_HOLE` / `EXTENT_MAP_INLINE` sentinels)
- `disk_num_bytes`: full on-disk allocation size (compressed size when compressed)
- `offset`: offset within decompressed extent where file range starts (nonzero for partial refs)
- `ram_bytes`: decompressed size of full on-disk extent (`== disk_num_bytes` for uncompressed)

### Computed Helpers

Old struct fields (`block_start`, `block_len`, `orig_block_len`, `orig_start`) are removed:
- `btrfs_extent_map_block_start(em)` (public): uncompressed → `disk_bytenr + offset`; compressed → `disk_bytenr`
- `extent_map_block_len(em)` (file-private): uncompressed → `len`; compressed → `disk_num_bytes`

External callers needing block length: use `disk_num_bytes` if `btrfs_extent_map_is_compressed(em)`, else `len`.

### Invariants (`validate_extent_map()`)

Real data extents (`disk_bytenr < EXTENT_MAP_LAST_BYTE`):
- `disk_num_bytes != 0`
- `offset + len <= ram_bytes`
- Uncompressed: `offset + len <= disk_num_bytes` and `ram_bytes == disk_num_bytes`

Holes/inline: `offset == 0`

### Field Confusion Patterns

| Intent | Correct Field | Common Mistake |
|--------|--------------|----------------|
| File range covered | `len` | `ram_bytes` |
| On-disk bytes to read/write | `disk_num_bytes` | `len` |
| Decompressed extent size | `ram_bytes` | `disk_num_bytes` |
| Physical disk location for I/O | `btrfs_extent_map_block_start()` | raw `disk_bytenr` |

## Zoned Storage Active vs Open Zone Limits

Conflating `bdev_max_active_zones()` with `bdev_max_open_zones()` causes mount failures on valid filesystems. A device may report no active zone limit but still have an open zone limit — open zones is a stricter subset, not a proxy for active zones.

When synthesizing the active zone limit via `min_not_zero()` of both values in `btrfs_get_dev_zone_info()`, provide an escape hatch if the device reports no hard active limit:

```c
// CORRECT: Escape hatch when active limit was synthesized
if (nactive > max_active_zones) {
    if (bdev_max_active_zones(bdev) == 0) {
        max_active_zones = 0;  // Clear synthesized limit
        goto validate;         // Allow mount to proceed
    }
    return -EIO;  // Only fail for real device limits
}
```

Any code synthesizing zone limits from multiple sources must allow mount to proceed when the device reports no hard limit for the stricter constraint.
