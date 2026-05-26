# False Positive Prevention Guide - Locking

## 4. Locking False Positives

### 4a. Deadlock Analysis Within a Function

**CRITICAL**: Before reporting a deadlock (double-lock on same semaphore/mutex):

**Trace lock state through ALL code paths**:
1. Find ALL lock acquisitions: down_write/down_read/mutex_lock/spin_lock
2. Find ALL lock releases: up_write/up_read/mutex_unlock/spin_unlock
3. Trace lock state at EVERY goto/jump target
4. Verify lock is ACTUALLY HELD at the problematic point

**Output format** (REQUIRED for deadlock reports):
```
Lock trace:
  Line X: down_write(&lock)         [LOCKED]
  Line Y: if (condition)             [LOCKED]
  Line Z:   up_write(&lock)          [UNLOCKED] ← Release!
  Line A:   function_call()          [UNLOCKED]
  Line B:   goto label               [UNLOCKED]
  Line C: label:
  Line D:   down_write(&lock)        [LOCKED] ← Reacquire OK
```

**Common FALSE POSITIVE pattern**:
```c
down_write(&sem);
if (special_case) {
    up_write(&sem);        // ← DON'T MISS THIS!
    call_function();
    goto cleanup;
}
// ... normal path with lock held ...
cleanup:
    down_write(&sem);      // ← NOT a deadlock - lock was released above!
```

**If you cannot trace the lock state** through all paths:
- DO NOT report "deadlock"
- Instead report "Potential locking issue - manual verification needed"
- Explain: "Could not verify lock state through all code paths"

### 4b. Missing Lock Analysis (Inter-Function)

**Before reporting** a missing lock:
- Check ALL calling functions for held locks
  - Output: list each caller and locks it holds (e.g., "caller() holds mutex_x at file:line")
- Trace up 2-3 levels to find lock context
  - Output: full lock chain from entry point to issue site
- Verify the actual lock requirements
  - Output: quote lock documentation or convention (e.g., "must hold rcu_read_lock")
- Consider RCU and other lockless mechanisms
  - Output: RCU/lockless mechanism found or "none applicable"
