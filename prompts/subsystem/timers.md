# Timer Subsystem Details

## Timer Types

### timer_list (low-resolution timers)
- Resolution: jiffies (1-10ms depending on HZ)
- Callback context: **softirq** (timer softirq)
- Cannot sleep in callback
- Setup: `timer_setup(timer, callback, flags)` or `DEFINE_TIMER()`
- Arm: `mod_timer(timer, expires)` or `add_timer(timer)`
- Cancel: `timer_delete()` / `timer_delete_sync()`
- Teardown: `timer_shutdown_sync()` - cancels and prevents re-arming
- Re-arm from callback: call `mod_timer()` inside the callback

### hrtimer (high-resolution timers)
- Resolution: nanoseconds (ktime_t)
- Callback context: **hardirq** by default, **softirq** with HRTIMER_MODE_SOFT
- Return: `HRTIMER_NORESTART` (stop) or `HRTIMER_RESTART` (continue)
- Setup: `hrtimer_setup(timer, callback, clock_id, mode)`
- Arm: `hrtimer_start(timer, time, mode)` or `hrtimer_start_range_ns()`
- Cancel: `hrtimer_cancel()` (sync) or `hrtimer_try_to_cancel()` (returns -1 if callback executing)
- Reschedule from callback: `hrtimer_forward_now()` then return HRTIMER_RESTART
- Pinned mode (`HRTIMER_MODE_*_PINNED`): timer fires on the CPU where it was armed

### delayed_work (workqueue-based timers)
- Callback context: **process context** (can sleep)
- Setup: `INIT_DELAYED_WORK(dwork, callback)`
- Arm: `schedule_delayed_work(dwork, delay)` or `queue_delayed_work(wq, dwork, delay)`
- Cancel: `cancel_delayed_work_sync()` - waits for callback completion

## Sync Cancel Semantics

- `timer_delete_sync()` spin-waits for callback completion
- Calling sync cancel from the timer's own callback deadlocks
- If caller holds a lock the callback also takes, sync cancel deadlocks
- Non-sync `timer_delete()` only dequeues; callback may still be running
- `timer_shutdown_sync()` permanently prevents re-arming (teardown only)

## timer_pending() is Not Synchronization

- Returns whether timer is enqueued, but can change immediately after check
- Timer not pending may still have callback executing on another CPU
- Cannot use as proof callback is not running

## Execution Context Constraints

| Operation | timer_list (softirq) | hrtimer default (hardirq) | hrtimer SOFT (softirq) | delayed_work (process) |
|-----------|---------------------|--------------------------|----------------------|----------------------|
| Sleep/schedule | prohibited | prohibited | prohibited | allowed |
| mutex_lock | prohibited | prohibited | prohibited | allowed |
| GFP_KERNEL alloc | prohibited | prohibited | prohibited | allowed |
| spin_lock | allowed | allowed | allowed | allowed |
| spin_lock_bh | redundant (use spin_lock) | prohibited (WARN_ON) | redundant (use spin_lock) | allowed |
| spin_lock_irqsave | allowed | allowed | allowed | allowed |
| RCU read-side | allowed (implicit) | allowed (implicit) | allowed (implicit) | needs rcu_read_lock() |

## Unsafe in Timer Callbacks (softirq/hardirq)

- Sleep functions: `msleep()`, `ssleep()`, `usleep_range()`
- Blocking waits: `wait_for_completion()`, `wait_event()`
- Sleeping locks: `mutex_lock()`, `down()`
- Non-atomic alloc: `kmalloc(..., GFP_KERNEL)` - use `GFP_ATOMIC`
- User memory: `copy_to_user()`, `copy_from_user()`
- `vfree()` - safe (auto-defers via `vfree_atomic()` when `in_interrupt()`), but `vfree_atomic()` can be called explicitly
- `synchronize_rcu()` - use `call_rcu()` instead
- `flush_work()`, `flush_workqueue()` - may sleep

## Common Teardown Patterns

Correct sync cancel before free:
```c
timer_shutdown_sync(&obj->timer);
kfree(obj);
```

Wrong non-sync cancel before free:
```c
timer_delete(&obj->timer);  /* callback may still be running! */
kfree(obj);                 /* use-after-free */
```

Wrong sync cancel while holding callback's lock:
```c
spin_lock(&obj->lock);
timer_delete_sync(&obj->timer);  /* DEADLOCK if callback takes obj->lock */
spin_unlock(&obj->lock);
```

## API Names

- `del_timer()`, `del_timer_sync()` are removed; use `timer_delete()`, `timer_delete_sync()`
- `hrtimer_init()` is removed; use `hrtimer_setup(timer, callback, clock_id, mode)`
- `timer_shutdown_sync()` for teardown paths
- `setup_timer()` and `init_timer()` are removed

## Timer API Conversion: setup_timer() → timer_setup()

**CRITICAL: These APIs have incompatible callback signatures and cannot be swapped without updating the callback function.**

### Old API (removed): setup_timer()
```c
void callback(unsigned long data) {
    struct foo *obj = (struct foo *)data;
    // use obj...
}

setup_timer(&obj->timer, callback, (unsigned long)obj);
```
- Callback receives: `unsigned long data` (pointer cast to unsigned long)
- Data passed explicitly as third argument to setup_timer()

### New API: timer_setup()
```c
void callback(struct timer_list *t) {
    struct foo *obj = from_timer(obj, t, timer);
    // use obj...
}

timer_setup(&obj->timer, callback, flags);
```
- Callback receives: `struct timer_list *` (pointer to the timer itself)
- Object extracted using `from_timer(var, timer_ptr, timer_field_name)`
- No data argument needed; container_of() magic retrieves parent struct

### Common Conversion Bug Pattern

**WRONG - incomplete conversion:**
```c
// Old callback signature NOT updated:
static void timeout_func(unsigned long data) {  // WRONG!
    struct foo *obj = (struct foo *)data;
    // ...
}

// Only changed the setup call:
timer_setup(&obj->timer, timeout_func, 0);  // BUG: signature mismatch!
```
**Result:** Crash - callback receives `struct timer_list *` but expects `unsigned long`.

**CORRECT - complete conversion:**
```c
// Updated callback signature:
static void timeout_func(struct timer_list *t) {  // CORRECT
    struct foo *obj = from_timer(obj, t, timer);
    // ...
}

timer_setup(&obj->timer, timeout_func, 0);  // OK: signatures match
```

### Detection Rule

When you see `timer_setup()` being added or `setup_timer()` being removed:
1. **MANDATORY:** Check the callback function signature
2. If callback has `(unsigned long data)` parameter → **incomplete conversion bug**
3. If callback has `(struct timer_list *t)` parameter → correct
4. The callback signature MUST match the timer setup function used

This applies to backports and conversions. Changing only the setup call without updating the callback function causes type confusion and crashes.

## Quick Checks

- Timer freed without sync cancel -> use-after-free
- Sync cancel called from own callback -> deadlock
- Lock held across sync cancel that callback also takes -> deadlock
- `timer_pending()` used for synchronization -> race condition
- Sleep-capable function called from timer/hrtimer callback -> crash
- `timer_delete()` (non-sync) followed by free -> use-after-free
- hrtimer callback not returning HRTIMER_RESTART or HRTIMER_NORESTART -> undefined
- `mod_timer()` called after `timer_shutdown_sync()` -> silent no-op
