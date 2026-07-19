# Open Firmware (Device Tree) Subsystem Details

## OF Node Iterator Macros and Reference Counting

Iterator macros automatically call `of_node_put()` on the previous node before advancing; adding manual puts during normal iteration or `continue` causes double-free.

Macros with automatic reference management:
- `for_each_child_of_node(parent, child)`
- `for_each_available_child_of_node(parent, child)`
- `for_each_reserved_child_of_node(parent, child)`
- `for_each_node_by_type(dn, type)`
- `for_each_compatible_node(dn, type, compatible)`
- `for_each_matching_node(dn, matches)`
- `for_each_matching_node_and_match(dn, matches, match)`
- `for_each_node_with_property(dn, prop_name)`

Rules:
- Normal iteration and `continue`: no manual `of_node_put()` needed.
- Early exit via `break` or `return`: caller must call `of_node_put()` before exiting.
- `goto` labels or explicit puts on every iteration: double-free bug.

```c
// WRONG: double-free on every iteration
for_each_child_of_node(parent, node) {
    if (!matches(node)) {
        of_node_put(node);  // double-free!
        continue;
    }
}

// CORRECT: early break needs manual put
for_each_child_of_node(parent, node) {
    if (found(node)) {
        of_node_put(node);
        break;
    }
}
```

`for_each_child_of_node_scoped()` and `for_each_available_child_of_node_scoped()` use `__free(device_node)` — no manual cleanup needed even on early exit.

## OF Node Acquisition APIs

These APIs return a node with incremented refcount; caller must call `of_node_put()` when done:
- `of_find_node_by_path()`, `of_find_node_by_name()`, `of_find_node_by_type()`
- `of_find_compatible_node()`, `of_find_matching_node_and_match()`, `of_find_node_with_property()`
- `of_get_parent()`, `of_get_child_by_name()`
- `of_parse_phandle()`, `of_find_node_by_phandle()`
- `of_node_get()`

Note: `of_find_node_by_name()`, `of_find_node_by_type()`, `of_find_compatible_node()`, `of_find_matching_node_and_match()`, and `of_find_node_with_property()` also drop the reference on their `from` argument — do not call `of_node_put(from)` separately after calling these.

`of_get_next_parent()` acquires a reference on the returned parent and drops the reference on the input node.

## MSI Controller DT Binding Variants

Two binding styles must both be handled to avoid MSI allocation failures:

1. **`msi-map` binding** — maps device IDs to MSI controller domains via `msi-map-mask`. Handled by `of_map_id()` → `of_msi_xlate()`.
2. **`msi-parent` binding** — phandle to MSI controller. If `#msi-cells` is absent or zero: 1:1 ID mapping. If non-zero: phandle carries specifier arguments. Resolved by `of_msi_get_domain()`.

## Quick Checks

- `of_node_put()` inside `for_each_*` loops: only on `break`/`return`, never on `continue` or normal iteration.
- `_scoped` iterator variants: no manual cleanup needed at all.
- `of_parse_phandle()`: always requires matching `of_node_put()`.
- `for_each_property_of_node()`: iterates property linked list directly; no reference counting involved.
