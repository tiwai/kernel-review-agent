# Sysfs Subsystem Details

## Attribute Group Visibility and Conditional Existence

When `is_visible()` returns 0, the attribute is **never created** in the filesystem (not just hidden). Code iterating `grp->attrs[]` or `grp->bin_attrs[]` must check `is_visible`/`is_bin_visible` and skip 0-returning attributes before calling `kernfs_find_and_get()` — otherwise `-ENOENT` propagates (e.g., during network namespace migration via `sysfs_group_change_owner()`). Binary attributes use `is_bin_visible` with identical semantics. `SYSFS_GROUP_INVISIBLE` suppresses the entire named group directory.

**Key invariant**: Any iterator over group attribute arrays that calls `kernfs_find_and_get()` or similar lookup must skip attributes where `is_visible`/`is_bin_visible` returns 0.

```c
// WRONG: kn is NULL if is_visible returned 0
for (i = 0, attr = grp->attrs; *attr; i++, attr++)
    kn = kernfs_find_and_get(parent, (*attr)->name);

// CORRECT:
for (i = 0, attr = grp->attrs; *attr; i++, attr++) {
    if (grp->is_visible) {
        mode = grp->is_visible(kobj, *attr, i);
        if (mode & SYSFS_GROUP_INVISIBLE) break;
        if (!mode) continue;
    }
    kn = kernfs_find_and_get(parent, (*attr)->name);
}
```

**Review trigger**: Patches adding `is_visible`/`is_bin_visible` to an existing group, or migrating visibility from `show()` to `is_visible()` — verify all group iterators perform the visibility check.

## Kobject Initialization and Cleanup

Every error path in loop-based kobject creation must clean up all previously allocated kobjects individually via `kobject_put()`. Direct `return -ERRNO` inside a creation loop leaks all prior iterations. In `__init`/`__initcall` functions these leaks are permanent.

- `kobject_create_and_add()` → balance with `kobject_put()` on all error paths
- `sysfs_create_group()` failure → also put the kobject passed to it
- Children hold a parent reference; freeing all children eventually drops the parent refcount

```c
// WRONG: leaks parent and children 0..i-1
for (int i = 0; i < N; i++) {
    children[i] = kobject_create_and_add(name, parent);
    if (!children[i]) return -ENOMEM;
}

// CORRECT: goto cleanup, free each child individually
for (int i = 0; i < N; i++) {
    children[i] = kobject_create_and_add(name, parent);
    if (!children[i]) { ret = -ENOMEM; goto err; }
}
return 0;
err:
    for (int j = i; j >= 0; j--) kobject_put(children[j]);
    kobject_put(parent);
    return ret;
```

## Quick Checks

- `is_visible()` = 0: attribute absent, not just hidden; cannot be found or have ownership changed
- `is_bin_visible()` = 0: same semantics for `grp->bin_attrs`
- `SYSFS_GROUP_INVISIBLE`: suppresses entire named group directory
- Any new `fs/sysfs/group.c` function iterating `grp->attrs`/`grp->bin_attrs` must respect visibility callbacks
- Loop kobject init: must use centralized `goto` cleanup, not inline `return`
