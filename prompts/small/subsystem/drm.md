# DRM Subsystem Details

## Atomic Context in Display Hardware Programming

Sleeping functions in atomic context cause kernel warnings, deadlocks, and instability.

**Atomic context paths:** `drm_atomic_helper_commit_tail()`, CRTC/plane/encoder atomic callbacks, VBLANK handlers, page flip handlers, hwseq functions.

| Function | Atomic-Safe |
|----------|-------------|
| `udelay()`, `ndelay()`, `mdelay()` | Yes |
| `fsleep()`, `msleep()`, `usleep_range()` | No |

**REPORT**: Any `fsleep`/`msleep`/`usleep_range`/`mutex_lock`/`GFP_KERNEL` in hwseq paths or atomic callbacks. When replacing a polling function with a fixed delay, verify the replacement uses only non-sleeping delays.

## Power Management Context Separation (XE Driver)

System PM paths must not use runtime PM flags (`xe->d3cold.allowed`, `xe->d3cold.capable`) to decide reinitialization depth. System suspend always loses power; full reinit is always required.

```c
// WRONG: runtime PM flag in system PM path
xe_i2c_pm_resume(xe, xe->d3cold.allowed);
// CORRECT:
xe_i2c_pm_resume(xe, true);
```

**REPORT**: `xe_pm_resume()`/`xe_pm_suspend()` using `d3cold.allowed` for conditional behavior.

## XE Driver GT Accessor API Contracts

`xe_device_get_gt()` can return NULL; direct dereference without a NULL check is a bug. Use `xe_root_mmio_gt()` when specifically needing the root tile's primary GT.

```c
// WRONG:
param->oa_unit = &xe_device_get_gt(oa->xe, 0)->oa.oa_unit[0];
// CORRECT:
param->oa_unit = &xe_root_mmio_gt(oa->xe)->oa.oa_unit[0];
```

**REPORT**: Direct dereference of `xe_device_get_gt()` return value without NULL check.

## DRM GPU VM (drm_gpuvm) IOMMU Requirement

`drm_gpuvm` requires IOMMU; it has no physical address fallback. No-IOMMU fallback paths that returned NULL must return `ERR_PTR(-ENODEV)`.

```c
// WRONG with drm_gpuvm:
if (!mmu) return NULL;
// CORRECT:
if (!mmu) return ERR_PTR(-ENODEV);
```

**REPORT**: In drm_gpuvm conversions, any code path returning NULL or setting `vm = NULL` when IOMMU is unavailable.

## DRM Scheduler KUnit Test Flag Semantics

- **Control flags** (e.g., `DRM_MOCK_SCHED_JOB_DONT_RESET`): govern handler behavior; must persist for the job's lifetime — never clear in the handler.
- **Status flags** (e.g., `DRM_MOCK_SCHED_JOB_RESET_SKIPPED`): record that an event occurred; only set, never cleared.

```c
// WRONG: clearing control flag breaks re-execution
job->flags &= ~DRM_MOCK_SCHED_JOB_DONT_RESET;
// CORRECT: set status flag instead
job->flags |= DRM_MOCK_SCHED_JOB_RESET_SKIPPED;
```

**REPORT**: Test handlers that modify (clear) the control flags they govern.

## XE GuC CT Debug Infrastructure Initialization

`stack_depot_save()` requires prior `stack_depot_init()`. Initialization must be in `xe_guc_ct_init_noalloc()` under the same config guard as the usage site.

```c
// CORRECT: in xe_guc_ct_init_noalloc()
#if IS_ENABLED(CONFIG_DRM_XE_DEBUG_GUC)
    stack_depot_init();
#endif
```

**REPORT**: Calls to `stack_depot_save()` under debug configs without a matching `stack_depot_init()` in the init path.

## MSM VM Lazy Initialization

VMs are not created at context creation; use `msm_context_vm(dev, ctx)` instead of direct `ctx->vm` access in ioctl entry points and early code paths.

```c
// WRONG: ctx->vm may be NULL
if (to_msm_vm(ctx->vm)->unusable) ...
// CORRECT:
if (to_msm_vm(msm_context_vm(dev, ctx))->unusable) ...
```

**REPORT**: Direct `ctx->vm` access in ioctl entry points without a prior `msm_context_vm()` call.

## struct_size() Overflow Semantics

`struct_size()` saturates at `SIZE_MAX`; a check `if (sz > SIZE_MAX)` is dead code.

```c
// WRONG (dead code):
u64 sz = struct_size(job, ops, nr_ops);
if (sz > SIZE_MAX) return -ENOMEM;
// CORRECT:
if (sz == SIZE_MAX) return -ENOMEM;
// OR: let kzalloc fail on SIZE_MAX input
```

**REPORT**: `if (sz > SIZE_MAX)` after `struct_size()`, `array_size()`, or similar saturating size macros.

## Intel GPU Platform and Subplatform Architecture

Platforms use a two-level hierarchy. When a commit adds device IDs for a hardware variant with different IP versions or PHY/PCH configurations, a subplatform registration is required in addition to adding the IDs.

**Files**: `include/drm/intel/pciids.h`, `drivers/gpu/drm/i915/display/intel_display_device.c`, `drivers/gpu/drm/xe/xe_pci.c`.

**REPORT**: Commits adding device IDs where hardware differences are noted but no subplatform registration is included.

### Platform Flag Overloading

A single platform flag (e.g., `display->platform.pantherlake`) may cover multiple variants with different PHY/port configurations. Claims like "there will never be a case where..." are hypotheses, not facts — VBT can enumerate ports in unexpected configurations.

**REPORT**: Conditions extending PHY/port ranges under a shared platform flag without per-variant handling or added subplatform differentiation.

## AMDGPU Buffer Object Allocation Contracts

`amdgpu_bo_create_kernel()` creates a new BO only if `*bo_ptr == NULL`. Wrapper functions accepting opaque `void **` must explicitly set `*bo = NULL` before calling, as callers may pass uninitialized stack memory.

```c
// CORRECT:
*bo = NULL;  // Force new BO creation
return amdgpu_bo_create_kernel(adev, size, align, domain, bo, ...);
```

**REPORT**: Wrapper functions passing `void **` to `amdgpu_bo_create_kernel()` without first setting `*bo = NULL`.

## AMDGPU Address Format APIs

| Function | Returns | Use Case |
|----------|---------|----------|
| `amdgpu_bo_gpu_offset()` | GPU virtual address | General buffer access |
| `amdgpu_gmc_pd_addr()` | PD address (hardware format) | Pagetable/VM root debugfs |

**REPORT**: Debugfs files exporting VM root/pagetable addresses via `amdgpu_bo_gpu_offset()` instead of `amdgpu_gmc_pd_addr()`.

## XE Pcode Mailbox Register Updates

Pcode mailbox registers pack multiple fields; direct assignment (`val0 = uval`) loses all other fields. Always use read-modify-write.

```c
// WRONG: val0 = uval;
// CORRECT: val0 = (val0 & ~clear_mask) | set_value;
```

**REPORT**: Pcode write sequences where the read value is overwritten by direct assignment rather than masked modification.

## AMDGPU Ring Buffer Write Pointer Types

All wptr variables, parameters, and struct fields must be `u64`. Mixed `u64`/`u32` wptr parameters cause truncation on large ring buffers.

**REPORT**: Function signatures with some wptr parameters as `u64` and others as `u32`.

## AMDGPU Fence Sequence Number Wrap-Around

Fence sequence numbers are `uint32_t` cyclic counters. Loop termination using `i <= sync_seq` fails silently when `sync_seq` wraps around. Use masked do-while instead.

```c
// WRONG: i <= ring->fence_drv.sync_seq  (fails on wrap)
// CORRECT: masked do-while with (last_seq != seq) termination
```

**REPORT**: Fence iteration loops using `<=`/`<` against `sync_seq` without masking.

## Display Scaling Mode Semantics (RMX_*)

`RMX_FULL` stretches the image without preserving aspect ratio. Automatic/default scaling must use `RMX_ASPECT`.

```c
// WRONG default: dm_new_connector_state->scaling = RMX_FULL;
// CORRECT default: dm_new_connector_state->scaling = RMX_ASPECT;
```

**REPORT**: `RMX_FULL` set as an automatic or default scaling mode without explicit userspace request.

## i915 CX0 PHY Register Access Protocol

All CX0 PHY register accesses (`intel_cx0_rmw/read/write`) must be wrapped in a transaction or called only from a context that already holds one:

```c
wakeref = intel_cx0_phy_transaction_begin(encoder);
// ... PHY accesses ...
intel_cx0_phy_transaction_end(encoder, wakeref);
```

For C10 PHY, `C10_VDR_CTRL_MSGBUS_ACCESS` must be set before accessing internal registers (Bspec 68962). AUXLess ALPM register access must early-return when the feature is inactive — conditional bit-writes inside loops still access the register.

**REPORT**: New functions calling CX0 PHY access APIs without a transaction wrapper (or without documenting that all callers hold one).

## DisplayPort DPCD Register Access Patterns

Registers in the link training status range (0x202–0x207, e.g., `DP_LANE0_1_STATUS`) may trigger state machine transitions when read. Prefer `DP_TRAINING_PATTERN_SET` (0x102) or `DP_DPCD_REV` (0x000) for probing.

**REPORT**: Changes to DPCD probe/quirk register addresses that switch to the 0x202–0x207 range without documenting safety.

## AMDGPU PSP Firmware Version Checking

New `GFX_CMD_ID_*` PSP commands require both an IP version check and a firmware version check. IP version alone is insufficient because newer hardware may run older firmware.

```c
// CORRECT: both checks required
if (amdgpu_ip_version(adev, MP0_HWIP, 0) == IP_VERSION(14, 0, 2) &&
    adev->psp.sos.fw_version >= MINIMUM_FW_VERSION) { ... }
```

**REPORT**: PSP GFX command calls guarded only by IP version without a `psp.sos.fw_version` check.

## XE SR-IOV Virtual Function (VF) Constraints

VFs cannot access I2C controllers, SOC_BASE MMIO, certain power management features, or GuC firmware loading. New probe functions registering such resources must guard with `IS_SRIOV_VF()`:

```c
if (IS_SRIOV_VF(xe))
    return 0;
```

**REPORT**: New `*_probe()` functions in the xe driver registering platform devices or hardware controllers without an `IS_SRIOV_VF()` guard.

## fwnode API Error Return Conventions

`fwnode_create_software_node()` returns `ERR_PTR()`, not NULL. A NULL check never triggers; the error pointer is later dereferenced, causing a crash.

```c
// WRONG: if (!fwnode) return -ENOMEM;
// CORRECT: if (IS_ERR(fwnode)) return PTR_ERR(fwnode);
```

**REPORT**: NULL checks (`if (!fwnode)`) after `fwnode_create_software_node()` or other fwnode APIs that return `ERR_PTR()`.

## Quick Checks

- `fsleep`/`msleep`/`usleep_range`/`mutex_lock`/`GFP_KERNEL` in hwseq paths or atomic callbacks → atomic context violation
- `xe_pm_resume()`/`xe_pm_suspend()` using `d3cold.allowed` → system/runtime PM confusion
- Direct dereference of `xe_device_get_gt()` without NULL check → NULL deref
- `if (sz > SIZE_MAX)` after `struct_size()` → dead code
- `if (!fwnode)` after `fwnode_create_software_node()` → wrong error check
