# False Positive Prevention Guide - Locking

## 4. Locking False Positives

### 4a. Deadlock Analysis Within a Function

Before reporting a deadlock, trace lock state through ALL code paths including every goto/jump target.

Required output format for deadlock reports:
```
Lock trace:
  Line X: down_write(&lock)   [LOCKED]
  Line Z:   up_write(&lock)   [UNLOCKED] ← Release!
  Line D:   down_write(&lock) [LOCKED]   ← Reacquire OK
```

Common false positive: a lock released before a goto label, then reacquired at the label — this is NOT a deadlock.

If lock state cannot be traced through all paths: report "Potential locking issue - manual verification needed", not "deadlock".

### 4b. Missing Lock Analysis (Inter-Function)

Before reporting a missing lock:
- Check ALL callers for held locks (list each caller and locks held with file:line)
- Trace up 2-3 call levels to find lock context (output full lock chain)
- Verify actual lock requirements (quote lock documentation or convention)
- Consider RCU and other lockless mechanisms (state which applies or "none applicable")
