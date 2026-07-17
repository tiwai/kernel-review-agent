# Cleanup and Guard Macros — Condensed Reference

## Macro Syntax (Critical — frequently misread)

**`guard(TYPE)(LOCK)`** — two separate argument groups:
- First `(TYPE)` selects the guard class; second `(LOCK)` passes the lock pointer
- Example: `guard(mutex)(&dev->lock)` — **NOT** `guard(mutex, &dev->lock)`
- Lock is held until the enclosing scope exits; no named variable exposed

**`scoped_guard(TYPE, LOCK) { body }`** — comma-separated args, then a block:
- TYPE and LOCK are a single comma-separated list (unlike `guard()`)
- The body is a block statement like the body of `for`/`while`
- **`break` inside the body exits legally** — it is the intended early-exit mechanism
- For conditional/trylock variants, the body is skipped if the lock was not acquired

**Standard TYPE names**: `spinlock`, `spinlock_irq`, `spinlock_irqsave`,
`mutex`, `rwsem_read`, `rwsem_write` (plus subsystem-local types defined via
`DEFINE_GUARD()`/`DEFINE_LOCK_GUARD_1()`).

## Deadlock Verification

`guard()` and `scoped_guard()` acquire real locks — apply full deadlock analysis:

- **ABBA deadlock**: check that the acquisition order is consistent with all
  other paths that hold the same locks
- **Context**: `mutex`/`rwsem` guards sleep — forbidden in atomic context
  (hardirq, softirq, preempt-disabled, or while holding a spinlock)
- **Nesting**: `mutex`/`rwsem` guards cannot nest inside `spinlock` guards;
  `spinlock` guards cannot nest inside `raw_spinlock` guards

## __free() — Memory Leak Analysis

**Do NOT report memory leaks** for variables declared with `__free()`.
Cleanup is automatic at scope exit via `__attribute__((cleanup(...)))`.

The only true leak is ownership transferred without `no_free_ptr()`/`return_ptr()`,
causing the cleanup to fire on the original value while the new owner also holds it.

## __free() — UAF from Blind Reassignment

UAF can still occur even with `__free()`. Blindly assigning a new value to a
`__free()` variable causes the cleanup to fire on the **new** value at scope exit:

```c
struct obj *p __free(kfree) = alloc_obj();
p = another_ptr;   // WRONG: kfree fires on another_ptr at exit → UAF.
                   // The original alloc_obj() allocation is also leaked.
```

**REPORT as bugs**: A `__free()` variable reassigned without first calling
`no_free_ptr(p)` to consume and null the original value.

## LIFO Ordering

Cleanup runs in **reverse definition order**. Define `guard()` locks BEFORE the
`__free()` resources they protect. Define `__free()` variables at point-of-use,
not at the top of the function with `= NULL`.

```c
// CORRECT: guard defined first, resource second
guard(mutex)(&lock);
struct object *obj __free(kfree) = alloc_obj();  // cleaned up first, then unlock

// WRONG: resource before guard — cleanup runs: unlock, then kfree (lock not held!)
struct object *obj __free(kfree) = NULL;
guard(mutex)(&lock);
obj = alloc_obj();
```

## Ownership Transfer

Use `no_free_ptr(p)` or `return_ptr(p)` to inhibit cleanup when transferring
ownership. Missing this causes double-free when the cleanup fires on scope exit.

```c
struct obj *p __free(kfree) = alloc_obj();
if (!p) return NULL;
return_ptr(p);   // inhibits cleanup; caller takes ownership
```

## Goto Mixing

**REPORT as bugs**: Functions that mix `goto`-based cleanup labels with
`__free()`/`guard()` in the same function body.
