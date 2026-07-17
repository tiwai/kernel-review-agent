# Cleanup and Guard Subsystem Details

## Macro Syntax and Invocation

The guard and cleanup macros use non-obvious call syntax that is frequently
misread — the two primary macros differ in how arguments are passed.

**`guard(TYPE)(LOCK)`** — two separate argument groups:
- `(TYPE)` selects the guard class (e.g., `mutex`, `spinlock`, `spinlock_irqsave`)
- `(LOCK)` is a separate argument group passing a pointer to the lock object
- Example: `guard(mutex)(&dev->lock)` — **NOT** `guard(mutex, &dev->lock)`
- The lock is acquired immediately and held until the enclosing scope exits
- There is no named variable exposed — the lock is anonymous

**`scoped_guard(TYPE, LOCK) { body }`** — comma-separated args, then a block:
- `TYPE` and `LOCK` form a single comma-separated argument list (unlike `guard()`)
- The body is a block statement, like the body of `for`/`while`/`if`
- **`break` inside the body exits the block legally** — it is not a bug or
  loop escape; it is the intended early-exit mechanism for this construct
- For conditional/trylock variants, the body is skipped entirely if the lock
  was not acquired — absence of the body is correct, not a missed path
- Example: `scoped_guard(mutex, &dev->lock) { val = dev->data; }`

**Standard TYPE names** (defined in `include/linux/spinlock.h`, `include/linux/mutex.h`
and related headers):

| TYPE name | Underlying lock | IRQ behavior |
|---|---|---|
| `spinlock` | `spinlock_t` | none |
| `spinlock_irq` | `spinlock_t` | disables IRQs |
| `spinlock_irqsave` | `spinlock_t` | saves/restores IRQ state |
| `raw_spinlock` | `raw_spinlock_t` | none |
| `raw_spinlock_irqsave` | `raw_spinlock_t` | saves/restores IRQ state |
| `mutex` | `struct mutex` | sleepable |
| `rwsem_read` | `struct rw_semaphore` | read lock, sleepable |
| `rwsem_write` | `struct rw_semaphore` | write lock, sleepable |

Subsystems may define additional local types via `DEFINE_GUARD()` or
`DEFINE_LOCK_GUARD_1()` — always verify against the actual definition.

## Deadlock Verification for guard() and scoped_guard()

`guard()` and `scoped_guard()` acquire real locks. Apply the same deadlock
analysis as for explicit lock/unlock pairs:

**ABBA deadlock**: If the code already holds another lock when `guard()` or
`scoped_guard()` is entered, verify that the lock acquisition order is
consistent across all code paths. Inconsistent ordering (A→B in one path,
B→A in another) is a deadlock bug.

**Context compatibility**: Check the TYPE against the caller's execution context:
- `mutex` and `rwsem` guards sleep — they **cannot** be used in atomic context
  (hardirq, softirq handler, preempt-disabled, or while holding a spinlock)
- `spinlock`/`spinlock_irq`/`spinlock_irqsave` guards do not sleep — safe in
  preempt-disabled context, but not inside `raw_spinlock_t` critical sections
- `spinlock_irqsave` is required when the same lock is also accessed from
  an IRQ handler

**Lock nesting**: The wait-type hierarchy (from locking.md §5) applies to
guards. `mutex` or `rwsem` guards cannot nest inside `spinlock` guards.
`spinlock` guards cannot nest inside `raw_spinlock` guards.

**False positive caution**: A `guard()` at function scope is held for the
entire function body. A `scoped_guard()` is held only for its compound
statement. Verify the lock TYPE and scope before concluding a deadlock.

## __free() and Memory Leak Analysis

**Do NOT report memory leaks for variables decorated with `__free()`.**

The cleanup function runs automatically when the variable goes out of scope —
cleanup is guaranteed by the compiler's `__attribute__((cleanup(...)))`. A
missing `kfree()` call is not a leak if `__free(kfree)` is present.

The only true leak is when ownership is transferred to another owner WITHOUT
using `no_free_ptr()` or `return_ptr()` to inhibit cleanup, resulting in the
resource being freed before the new owner can use it. That is a double-free,
not a leak.

## __free() UAF from Blind Reassignment

UAF can still occur with `__free()` if a `__free()`-decorated variable is
assigned a new pointer value without first consuming the original value via
`no_free_ptr()` or `return_ptr()`. At scope exit, the cleanup function fires
on whatever value the variable currently holds — the **new** value, not the
original allocation.

```c
struct obj *p __free(kfree) = alloc_obj();
// ... use p ...
p = another_ptr;   // WRONG: kfree fires on another_ptr at scope exit,
                   // not on the original alloc_obj() allocation.
                   // another_ptr's other users see a freed object → UAF.
                   // The original alloc_obj() allocation is also leaked.
```

**REPORT as bugs**: Any `__free()` variable that is reassigned a new value
without first extracting the original via `no_free_ptr()`. The correct pattern
is to call `no_free_ptr(p)` to obtain and consume the current value before
assigning a new one.

The original allocation is also leaked in this scenario — but **do not report
that as the primary bug**. The UAF of the new value at scope exit is the
crash-risk issue.

## Cleanup Function Compatibility

Using `__free()` with a cleanup function that cannot handle all values the
variable may hold causes crashes or undefined behavior. If an allocator
returns `ERR_PTR` on failure but the cleanup wrapper only checks `if (_T)`,
the `ERR_PTR` value is truthy and the cleanup function receives a bogus
pointer, causing a kernel crash.

**Validating compatibility**:
- Identify what the allocator can return: NULL, ERR_PTR, valid pointer, or combinations
- Identify what the `DEFINE_FREE` wrapper guards against: `if (_T)` (NULL-safe only), `if (!IS_ERR_OR_NULL(_T))` (NULL and ERR_PTR safe), or nothing
- Verify the wrapper handles all possible allocator return values on every early return path

**Common cleanup wrappers** (see `include/linux/slab.h` and `include/linux/cleanup.h`):
- `__free(kfree)`: defined as `if (!IS_ERR_OR_NULL(_T)) kfree(_T)` — safe with NULL and ERR_PTR
- `__free(kfree_sensitive)`: defined as `if (_T) kfree_sensitive(_T)` — safe with NULL only, NOT ERR_PTR
- Custom `DEFINE_FREE` wrappers: check the guard expression individually

**Mitigation patterns**:
- Setting the variable to NULL before early return
- Using `no_free_ptr()` before early return to inhibit cleanup
- Using a cleanup function that checks `IS_ERR_OR_NULL()`

```c
// CORRECT: cleanup wrapper guards against ERR_PTR
DEFINE_FREE(my_free, void *, if (!IS_ERR_OR_NULL(_T)) my_release(_T))

struct obj *p __free(my_free) = alloc_thing();  // may return ERR_PTR
if (IS_ERR(p))
    return PTR_ERR(p);  // cleanup sees ERR_PTR, skips my_release()

// WRONG: cleanup wrapper only checks NULL, allocator can return ERR_PTR
DEFINE_FREE(my_free, void *, if (_T) my_release(_T))

struct obj *p __free(my_free) = alloc_thing();  // may return ERR_PTR
if (IS_ERR(p))
    return PTR_ERR(p);  // cleanup sees ERR_PTR (truthy), calls my_release(ERR_PTR)!
```

**REPORT as bugs**: Any `__free()` variable where the cleanup wrapper does not
guard against all values the variable can hold at every exit point.

## LIFO Definition Ordering

Defining `__free()` variables and `guard()` locks in the wrong order causes
cleanup to run in the wrong sequence: locks release before resources that
require the lock for cleanup, resulting in use-after-free or lockdep
violations.

Cleanup runs in reverse definition order (LIFO). From `include/linux/cleanup.h`:

> "When multiple variables in the same scope have cleanup attributes, at exit
> from the scope their associated cleanup functions are run in reverse order
> of definition (last defined, first cleanup)."

**Rules**:
- Locks protecting a resource must be defined (via `guard()`) BEFORE the
  resource they protect (via `__free()`)
- Resources that reference other resources must be defined AFTER their
  dependencies
- Define and initialize `__free()` variables in a single statement rather
  than `= NULL` at the top with assignment later — this makes LIFO ordering
  mistakes less likely (recommended in `include/linux/cleanup.h`)

```c
// CORRECT: guard defined first, resource second
guard(mutex)(&lock);
struct object *obj __free(remove_free) = alloc_add();
// At scope exit: remove_free(obj) runs first (with lock held), then unlock

// WRONG: resource defined before guard
struct object *obj __free(remove_free) = NULL;
guard(mutex)(&lock);
obj = alloc_add();
if (!obj)
    return -ENOMEM;

err = other_init(obj);
if (err)
    return err;  // remove_free(obj) runs AFTER unlock — lock not held!
```

## Guard Scope

Using data protected by a `guard()` lock outside the scope where the guard
was declared causes use-after-free or data races, because the lock has
already been released.

From `include/linux/cleanup.h`:

> "The lifetime of the lock obtained by the guard() helper follows the scope
> of automatic variable declaration."

**Scope types**:
- Function scope: `guard()` at function level — lock held until function returns
- Block scope: `guard()` inside `if`/`else`/`while` block — lock held only until closing brace
- `scoped_guard()`: lock held only for the following compound statement

```c
// CORRECT: data used within guard scope
guard(mutex)(&lock);
val = shared_data;  // lock held here
return val;

// WRONG: guard in block, data used after block
if (condition) {
    guard(mutex)(&lock);
    val = shared_data;  // lock held here
}  // lock released here
use(val);  // data race — lock no longer held
```

## Ownership Transfer

Failing to inhibit cleanup when transferring ownership of a `__free()`
variable causes double-free: the cleanup function frees the resource, and the
new owner frees it again.

**Transfer primitives** (defined in `include/linux/cleanup.h`):
- `no_free_ptr(p)`: returns `p` and sets `p` to NULL, inhibiting cleanup. Has `__must_check` semantics
- `return_ptr(p)`: shorthand for `return no_free_ptr(p)`
- `retain_and_null_ptr(p)`: like `no_free_ptr()` but discards the return value. Use when passing ownership to a function that consumes the pointer on success

```c
// CORRECT: inhibit cleanup on success path
struct obj *p __free(kfree) = kmalloc(...);
if (!p)
    return NULL;  // cleanup frees NULL (no-op)
return_ptr(p);    // inhibits cleanup, caller takes ownership

// CORRECT: conditional ownership transfer
ret = bar(f);
if (!ret)
    retain_and_null_ptr(f);  // bar() consumed f on success
return ret;                  // if bar() failed, cleanup frees f
```

## Goto Mixing

Mixing `goto`-based error handling with `__free()`/`guard()` cleanup in the
same function creates confusing ownership semantics and double-free or
resource leak bugs.

From `include/linux/cleanup.h`:

> the expectation is that usage of "goto" and cleanup helpers is never
> mixed in the same function. I.e. for a given routine, convert all
> resources that need a "goto" cleanup to scope-based cleanup, or
> convert none of them.

**REPORT as bugs**: Functions that contain both `goto`-based cleanup labels
and `__free()`/`guard()` declarations.

## Quick Checks

- **Allocator return vs cleanup guard**: When reviewing a new `__free()`
  variable, check the allocator's return type (NULL vs ERR_PTR) against the
  `DEFINE_FREE` guard expression.
- **Split definition-initialization**: Variables declared `__free(name) = NULL`
  at function top and assigned later are more prone to LIFO ordering mistakes.
  Verify the assignment happens after any required `guard()` calls.
- **scoped_guard vs guard**: `scoped_guard()` holds the lock only for its
  compound statement; `guard()` holds it for the rest of the enclosing scope.
  Verify the correct variant is used for the intended lock lifetime.
