# BTF Special Fields in BPF Maps

## Overview

BPF map values can contain special BTF-typed fields (spin locks, timers, kptrs, list heads, etc.) requiring special handling during copy/update:

- `check_and_init_map_value(map, dst)`: reinitializes special fields after copying to userspace buffer, preventing kernel pointer/lock leakage.
- `bpf_obj_free_fields(map->record, ptr)`: releases resources held by old value (cancels timers, drops kptr refs, frees list heads) before overwriting.

## Which Map Types Support Special Fields

Enforced in `map_check_btf()` (`kernel/bpf/syscall.c`); unsupported types get `-EOPNOTSUPP` at creation.

| Field Type | Allowed Map Types |
|-----------|-------------------|
| `BPF_SPIN_LOCK`, `BPF_RES_SPIN_LOCK` | HASH, ARRAY, CGROUP_STORAGE, SK_STORAGE, INODE_STORAGE, TASK_STORAGE, CGRP_STORAGE |
| `BPF_TIMER`, `BPF_WORKQUEUE`, `BPF_TASK_WORK` | HASH, LRU_HASH, ARRAY |
| `BPF_KPTR_UNREF`, `BPF_KPTR_REF`, `BPF_KPTR_PERCPU`, `BPF_REFCOUNT` | HASH, PERCPU_HASH, LRU_HASH, LRU_PERCPU_HASH, ARRAY, PERCPU_ARRAY, SK_STORAGE, INODE_STORAGE, TASK_STORAGE, CGRP_STORAGE |
| `BPF_UPTR` | TASK_STORAGE |
| `BPF_LIST_HEAD`, `BPF_RB_ROOT` | HASH, LRU_HASH, ARRAY |

Map types not listed cannot have special BTF fields; missing calls are not bugs for those types.

## Required Handling in Map Operations

### Lookup (kernel to userspace copy)

After `copy_map_value()` / `copy_map_value_long()`, call `check_and_init_map_value()` on the destination to zero special fields. Reference: `bpf_map_copy_value()` in `kernel/bpf/syscall.c`.

### Update (userspace to kernel copy)

Before/after `copy_map_value()` overwrites an existing value, call `bpf_obj_free_fields()` to release old resources. Reference: `array_map_update_elem()`, `htab_map_update_elem()` (via `check_and_free_fields()`).

## BPF-001: Missing BTF Field Handling in Map Copy/Update

For any new map operation or type using `copy_map_value()` / `copy_map_value_long()`, verify:

1. Does the map type support special BTF fields? (check table above)
2. Lookups: is `check_and_init_map_value()` called on destination after copy?
3. Updates: is `bpf_obj_free_fields()` called to clean up old value?
4. Percpu and non-percpu variants may have different allowlists — check exact `BPF_MAP_TYPE_*` enum.

**REPORT as bugs**: Copy operations on field-capable map types using `copy_map_value()` without `check_and_init_map_value()` (lookups) or `bpf_obj_free_fields()` (updates). Do not report for map types absent from `map_check_btf()` allowlists.
