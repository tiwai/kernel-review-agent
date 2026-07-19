# Power Management Subsystem Details

## Runtime PM Return Value Contracts

All Runtime PM wrappers route through three base functions in `drivers/base/power/runtime.c` with distinct return semantics:

**`__pm_runtime_suspend()`** (used by `pm_runtime_suspend()`, `pm_runtime_autosuspend()`, `pm_runtime_put_sync_suspend()`, `pm_runtime_put_sync_autosuspend()`, `__pm_runtime_put_autosuspend()`):
- Returns **1**: device was already `RPM_SUSPENDED` (success, not error)
- Returns **0**: successful suspension or async request queued
- Returns negative errno on failure (`-EAGAIN`, `-EBUSY`, `-EACCES`, etc.)

**`__pm_runtime_idle()`** (used by `pm_runtime_idle()`, `pm_request_idle()`, `pm_runtime_put()`, `pm_runtime_put_sync()`):
- `pm_runtime_idle()`/`pm_request_idle()` (without `RPM_GET_PUT`): cannot return **1**; returns `-EAGAIN` when already `RPM_SUSPENDED`
- `pm_runtime_put()`/`pm_runtime_put_sync()` (with `RPM_GET_PUT`): can return **1** when already `RPM_SUSPENDED` via special-case in `rpm_idle()`
- Returns **0** on success

**`__pm_runtime_resume()`** (used by `pm_runtime_resume()`, `pm_request_resume()`, `pm_runtime_get_sync()`, `pm_runtime_get()`):
- Returns **1**: device was already `RPM_ACTIVE`
- Returns **0**: successful resume or async request queued
- Returns negative errno on failure

## Concurrency and Locking

Runtime PM state transitions are serialized by `dev->power.lock`. Callers must expect these non-bug error returns:
- **`-EAGAIN`**: usage counter incremented by concurrent `pm_runtime_get()` before idle check ran, or sync caller races with in-progress transition
- **`-EBUSY`**: `child_count` nonzero due to concurrent child resume; `ignore_children` not set
- **`-EINPROGRESS`**: async caller while suspend/resume already in progress

## Hibernation Mode Handling

`pm_hibernate_is_recovering()` returns true only when `pm_transition.event == PM_EVENT_RECOVER` (image creation **failed**, recovery needed). It does NOT cover hybrid sleep wake.

Three `thaw()` scenarios:
- **Image creation succeeded**: `pm_transition` is `PMSG_THAW`; `pm_hibernate_is_recovering()` = false; system proceeds to power off, may skip resume
- **Image creation failed**: `pm_transition` is `PMSG_RECOVER`; `pm_hibernate_is_recovering()` = true; must fully resume
- **Hybrid sleep wake**: image created, system entered S3/s0i3; on wake, `pm_hibernate_is_recovering()` = false but `pm_hibernation_mode_is_suspend()` = true; must fully resume

```c
// WRONG: breaks hybrid sleep
if (!pm_hibernate_is_recovering())
    return 0;

// CORRECT: skip only when image succeeded AND not hybrid sleep
if (!pm_hibernate_is_recovering() && !pm_hibernation_mode_is_suspend())
    return 0;
```

Reference: `amdgpu_pmops_thaw()` in `drivers/gpu/drm/amd/amdgpu/amdgpu_drv.c`.

## PM Callback Conditional Compilation

Use wrapper macros (defined in `include/linux/pm.h`) to null callbacks when PM is disabled:

| Wrapper | Non-NULL when | Use for |
|---------|--------------|---------|
| `pm_sleep_ptr()` | `CONFIG_PM_SLEEP=y` | suspend/resume/freeze/thaw/poweroff/restore |
| `pm_ptr()` | `CONFIG_PM=y` | runtime PM callbacks; `dev_pm_ops` struct pointer |

```c
// WRONG
static const struct dev_pm_ops foo_pm_ops = { .thaw = foo_thaw };
.driver.pm = &foo_pm_ops,

// CORRECT
static const struct dev_pm_ops foo_pm_ops = {
    .thaw = pm_sleep_ptr(foo_thaw),
    .runtime_suspend = foo_runtime_suspend,
};
.driver.pm = pm_ptr(&foo_pm_ops),
```

## Async vs Synchronous Runtime PM Put

`pm_runtime_put()` queues async idle via `RPM_ASYNC`; the pending work can be cancelled by `pm_runtime_disable()` (called during removal via `__pm_runtime_barrier()`), leaving hardware in wrong power state.

Use `pm_runtime_put_sync()` instead of `pm_runtime_put()` when:
- `device_del()`, `device_unregister()`, or `auxiliary_device_delete()` follows immediately
- `pm_runtime_disable()` follows immediately
- Hardware ordering requires idle/suspended state before next operation

```c
// WRONG
pm_runtime_put(&dev->auxdev.dev);
device_del(&dev->auxdev.dev);

// CORRECT
pm_runtime_put_sync(&dev->auxdev.dev);
device_del(&dev->auxdev.dev);
```

## Runtime PM in IRQ Handlers

`pm_runtime_get_noresume()` only increments the usage counter (`atomic_inc()`); it does not check `runtime_status`. Hardware access after this call may hit a suspended device (reads return `0xffffffff`); on shared IRQs, causes spurious handling.

Use `pm_runtime_get_if_active()` instead: atomically checks `RPM_ACTIVE` and increments counter only if active. Returns **1** (active, incremented), **0** (not active), or **-EINVAL** (Runtime PM disabled).

```c
int ret = pm_runtime_get_if_active(dev);
if (ret <= 0)
    return IRQ_NONE;
status = readl(base + STATUS_REG);
if (status == ~0u) { pm_runtime_put(dev); return IRQ_NONE; }
// handle interrupt
pm_runtime_put(dev);
return IRQ_HANDLED;
```

Drivers using `IRQF_SHARED` must call `synchronize_irq()` in their runtime suspend callback before powering down hardware.

## Quick Checks

- **`thaw()` hybrid sleep**: `pm_hibernate_is_recovering()` used to skip resume must also check `pm_hibernation_mode_is_suspend()`
- **`pm_sleep_ptr()` wrappers**: sleep callbacks need `pm_sleep_ptr()`; `dev_pm_ops` struct pointer needs `pm_ptr()`
- **Sync before removal**: `pm_runtime_put()` + `device_del()`/`device_unregister()` → use `pm_runtime_put_sync()`
- **IRQ PM access**: use `pm_runtime_get_if_active()`, not `pm_runtime_get_noresume()`
- **`synchronize_irq()` in suspend**: required for `IRQF_SHARED` drivers before powering down
