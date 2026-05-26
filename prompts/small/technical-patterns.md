# Linux Kernel Technical Patterns (Condensed)

## Core Rules
- Trace execution flow and verify code behavior explicitly
- Never assume based on return types, comments, WARN_ON(), or BUG_ON()
- Never skip analysis steps even after finding a bug
- Kernel docs/comments can be outdated - always read actual implementation
- Verify bugs can happen in practice before reporting

## RCU Patterns (CRITICAL)
When seeing `call_rcu()`, `synchronize_rcu()`, or `kfree_rcu()`:
- Correct order: **remove from data structure FIRST**, then call_rcu(), then free in callback
- Wrong pattern: removal in RCU callback → use-after-free
```
// WRONG:
call_rcu(&obj->rcu, callback);
void callback(...) {
    remove_from_structure(obj);  // Too late!
    kfree(obj);
}
```

## Resource Management
- Every resource: alloc→init→use→cleanup→free
- refcount_dec_and_test returns true only at zero
- When freeing resources in struct fields, set pointers to NULL to prevent use-after-free
- Global/static vars are zero-filled automatically
- list_add() initializes `new` but `head` must be pre-initialized

## NULL Pointer Dereference
**What constitutes a dereference:**
- `*foo` - dereferences foo
- `foo->bar` - dereferences foo, reads bar (not a dereference of bar)
- `foo->bar->baz` - dereferences foo and bar, reads baz
- Reading a pointer field ≠ dereferencing it

**NULL checks protect:**
- `if (foo)` protects dereferencing `foo`
- `if (foo && foo->bar)` protects dereferencing `foo` and `foo->bar`

## ERR_PTR vs NULL
- `ERR_PTR()` holds error cast to pointer, not a valid pointer
- `foo = ERR_PTR(-ENOMEM); if (foo)` → TRUE, but `*foo` will CRASH

## Kernel Context
- **Preemption disabled**: Can use per-cpu vars, may be interrupted by IRQs
- **Self-tests**: Memory/FD leaks acceptable unless they crash system
- `READ_ONCE()` not required when data protected by held lock
- `__GENKSYMS__` blocks never compiled, only for ABI checking

## Common Patterns
- `list_add(new, head)` initializes `new`, `head` must exist
- `strscpy()` auto-detects array sizes
- `strlen("")` returns 0, but `s[0]` is safe to access
- All pointers same size; `sizeof(type *)` should use correct type for clarity
