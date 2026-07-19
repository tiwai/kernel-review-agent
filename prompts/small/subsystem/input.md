# Input Subsystem Details

## Device Lifecycle and Registration

- Allocate with `input_allocate_device()` or `devm_input_allocate_device()`.
- After `input_register_device()` succeeds, the core owns part of lifecycle; do NOT call `input_free_device()` on a registered device. The "defensive NULL" pattern (`input_unregister_device(dev); dev = NULL; input_free_device(dev)`) is safe.
- `input_event()` is safe before registration (updates internal state only); events won't reach handlers until registered.
- `EV_SYN`/`SYN_REPORT` is added automatically; manual addition is redundant.
- Reference counting keeps `input_dev` memory valid until all userspace references drop, even after `input_unregister_device()`.
- All driver private data and `input_set_drvdata()` MUST be set before `input_register_device()`; callbacks can fire immediately after.

## Callback Timing and Serialization

- `open()` and `close()` may be called the moment `input_register_device()` returns; driver must be fully ready.
- The core serializes `open()`/`close()` via `input_dev->mutex`; drivers needing to sync other methods must explicitly acquire it.
- `input_unregister_device()` automatically calls `close()` if the device is open.
- Use `input_device_enabled()` to check active state; must be called while holding `input_dev->mutex`.

## Force-Feedback Memory Management

- `input_ff_create_memless(dev, data, play_effect)` takes ownership of `data`; the core frees it with `kfree()` on device destroy.
- `data` MUST be `kmalloc()`-allocated, NOT `devm`-managed.
- **REPORT as bugs**: manually freeing `data` after passing it, or using `devm_kzalloc()` for it (causes double-free or invalid free).

## Managed Resources (devm) Integration

- No `devm_input_register_device()` exists; use standard `input_register_device()` even for devm-allocated devices.
- `devm_input_allocate_device()` auto-arranges `input_unregister_device()` on unbind and auto-sets `input_dev->dev.parent`; manual parent assignment is redundant.
- **REPORT as bugs**: explicitly calling `input_unregister_device()` on a devm-allocated device (double-unregistration risk).
- If mixing managed and non-managed resources, acquire non-managed ones after managed ones and release them manually before managed cleanup fires.

## Event Reporting and Synchronization

- Every logical event group MUST end with `input_sync()`; without it userspace state may not update.
- Prefer `input_report_key()`, `input_report_abs()`, `input_report_rel()` over raw `input_event()` when the type is known.
- The core deduplicates redundant events; avoid unnecessary reporting to reduce overhead.
- All reporting helpers acquire `input_dev->event_lock` (spinlock, IRQs disabled); callers must not hold locks that could deadlock with it.

## Maintainer Style Preferences

- Use C-style comments `/* ... */`; multi-line format with leading ` * `.
- Prefer `input_set_capability(dev, type, code)` over `__set_bit()` for single capabilities; direct bit ops acceptable in loops.
- Use `guard(mutex)(&input_dev->mutex)` and `__free()`-annotated locals (e.g., `u8 *buf __free(kfree) = ...`) in new/refactored code.
- Use `error` or `err` for error-code variables; success path must `return 0;` explicitly.
- Do not use `return action(...);` for multi-failure-point functions; use explicit check:
  ```c
  error = action(...);
  if (error)
          return error;
  return 0;
  ```

## Quick Checks

- `input_dev->name` is assigned; all private fields and `input_set_drvdata()` set before `input_register_device()`.
- `input_dev->dev.parent` set; if devm-allocated, manual assignment is redundant and should be removed.
- IRQ handler must not run until hardware is fully ready (powered, clocks, registers accessible).
- `input_device_enabled()` called only while holding `input_dev->mutex`.
- Event reporting path ends with `input_sync()`.
- FF private data: not devm-allocated, not manually freed after passing to `input_ff_create_memless()`.
