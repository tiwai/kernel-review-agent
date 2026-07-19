# KHO (Kexec Handover) Subsystem Details

## Enabled State and Initialization

Calling serialization-side APIs when KHO is disabled causes NULL pointer dereference on `kho_out.fdt` (only allocated when enabled). All callers must gate KHO usage on `kho_is_enabled()`.

- `kho_is_enabled()`: subsystem active; `kho_enable` is `__ro_after_init`, set via `kho=` boot param or `CONFIG_KEXEC_HANDOVER_ENABLE_DEFAULT`
- `is_kho_boot()`: current kernel was kexec'd via KHO; reliable only after `kho_populate()` runs
- Gate at module init or entry point of any path using KHO APIs

```c
// CORRECT
static int __init my_kho_init(void)
{
    if (!kho_is_enabled())
        return 0;
    err = kho_add_subtree("my_node", fdt);
}
```

## Preserve and Restore API Contracts

- `kho_preserve_folio()` / `kho_unpreserve_folio()`: whole folios; restored as compound page via `kho_restore_folio()`
- `kho_preserve_pages()` / `kho_unpreserve_pages()`: contiguous order-0 range; must restore with `kho_restore_pages()` (not `kho_restore_folio()`); unpreserve requires exact same `page` and `nr_pages`
- `kho_preserve_vmalloc()` / `kho_unpreserve_vmalloc()`: only `VM_ALLOC` and `VM_ALLOW_HUGE_VMAP` flags supported; others return `-EOPNOTSUPP`
- `kho_alloc_preserve()`: allocates zeroed power-of-two folio and preserves; pair with `kho_unpreserve_free()` or `kho_restore_free()` in successor

## Subtree Lifecycle

FDT memory passed to `kho_add_subtree()` must be separately preserved; the call only records the physical address, not the backing pages.

- `kho_add_subtree()`: records FDT physical address; caller must preserve backing pages independently; returns `-EEXIST` on duplicate name
- `kho_remove_subtree()`: matches by physical address; does not free or unpreserve FDT memory
- `kho_retrieve_subtree()`: successor-side lookup; returns raw physical address; convert with `phys_to_virt()` before use

## Scratch Region Constraints

Preserving memory overlapping a KHO scratch region corrupts early boot allocations for the successor kernel.

- `kho_preserve_folio()` and `kho_preserve_pages()` check via `kho_scratch_overlap()`; return `-EINVAL` with `WARN_ON` on overlap
- Scratch regions reserved by `kho_reserve_scratch()` as CMA-backed areas scaled by `kho_scratch=` (default 200% of memblock-reserved memory)

## FDT Endianness

KHO FDT values use **native host endianness**, not the dtspec big-endian format. This is intentional; KHO FDTs are consumed only by the same architecture. Do not flag native-endian reads/writes as bugs.

## Quick Checks

- Every serialization API call (`kho_add_subtree()`, `kho_preserve_folio()`, etc.) gated by `kho_is_enabled()`
- `kho_preserve_pages()` / `kho_unpreserve_pages()` called with matching `page` and `nr_pages`
- FDT passed to `kho_add_subtree()` independently preserved
- Error paths call appropriate unpreserve (`kho_unpreserve_folio()`, `kho_unpreserve_pages()`, `kho_unpreserve_vmalloc()`, or `kho_remove_subtree()` + `kho_unpreserve_*()`)
