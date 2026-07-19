# ARM64 KVM (Host/EL1) Subsystem Details

## VM & VCPU Lifecycle Initialization

- **Virtual ID Register Init:** `VMPIDR_EL2`/`VPIDR_EL2` reset to UNKNOWN; MUST be initialized before first EL1 entry.
- **Feature Locking:** Architectural features MUST be finalized via `kvm_arm_vcpu_finalize()` before first VCPU entry; reject modification once guest is RUNNING.
- **"Has guest run" predicate:** Use `vcpu_has_run_once(vcpu)`, NOT `kvm_vcpu_initialized()`. The latter only checks if `KVM_ARM_VCPU_INIT` was called and stays true post-run, silently accepting post-run reconfiguration.
  ```c
  /* WRONG */ if (!kvm_vcpu_initialized(vcpu)) return -EBUSY;
  /* CORRECT */ if (vcpu_has_run_once(vcpu)) return -EBUSY;
  ```
- **First-run ordering:** VGIC mapping (`kvm_vgic_map_resources()`) and `kvm_calculate_traps()` MUST complete before first VCPU entry.
- **UAPI Feature Exposure:** Every exposed `ID_AA64*` field must have a corresponding trap/enablement entry in `HCR_EL2`, `CPTR_EL2`, or `MDCR_EL2`.

**Report:** `kvm_vcpu_initialized()` used as "has guest run" gate; `ID_AA64*` exposed without trap config; VGIC/trap finalization missing before first run.

## Architectural State Management (PSCI & Reset)

- **Warm Reset:** Most sysregs reset to UNKNOWN; software MUST initialize `HCR_EL2`, `CPTR_EL2`, `CNTHCTL_EL2`, and ensure `HCR_EL2.RW == 1` for AArch64 guests.
- **Guest Affinity Sanity:** `MPIDR_EL1` affinity values and GIC target IDs MUST be unique and ARM-ARM-compliant across all VCPUs; KVM must not add workarounds for non-unique affinities.
- **Exception Injection:** Must preserve `ELR_EL1`/`SPSR_EL1` across exit/entry; miscoordination between injection state and sync-abort/SError path causes ELR clobber.
- **Stage-2 Teardown:** Must serialize against concurrent `mmu_notifier` callbacks; freeing page tables while a notifier walker is active causes UAF/double-free.

**Report:** Non-unique affinity workarounds; exception paths modifying `ELR_EL1`/`SPSR_EL1` non-atomically; teardown racing with `mmu_notifier`.

## VGIC CPU Interface Access

- **Priority Register Writes:** `ICV_AP<0|1>R<n>_EL1` must only be written with the last-read value or zero; out-of-order writes (AP0 must precede AP1) are UNPREDICTABLE.
- **Self-Synchronization:** `ICV_IAR0/1_EL1` reads self-synchronize when interrupts are masked; `ICV_PMR_EL1` writes are strictly self-synchronizing (no ISB needed).
- **GICV Access Gating:** `GICV_*` access is gated by `ICC_SRE_EL1_NS.SRE`, not `GICD_CTLR.ARE`; when SRE==1, use sysreg interface.

## Quick Checks

- **HCR_EL2 Sync:** Writes to TLB-cached fields (`RW`, `NV1`, `NV`, `E2H`, `FWB`, `DCT`) require TLB invalidation; `ERET` alone does not flush them. Verify nVHE and VHE barrier placement independently.
- **MTE Filtering:** Verify MTE features are filtered in guest ID registers based on hardware support AND VM type (Protected vs. Non-Protected).
- **Feature ID RESx Mask:** Every new `ID_AA64*` field exposure must pair with correct `kvm_id_reg_rw_mask`/RESx entry and a corresponding trap in `HCR_EL2`/`CPTR_EL2`/`MDCR_EL2`.

## VGIC LPI and vLPI Invariants

- **Lock ordering:** `irq_lock` and LPI xarray lock must not be held simultaneously unless ordering is documented; releasing/re-acquiring `irq_lock` while xarray lock is held causes deadlock.
- **Atomic context:** `vgic_put_irq()` must not be called from raw spinlock context while xarray lock is held.
- **vLPI unmapping:** Unmap MUST succeed on all paths; failed unmaps leave dangling forwarding entries — WARN and treat as bugs.
- **vPE allocation gating:** vLPI mappings MUST NOT proceed without verifying vPE allocation is enabled.

**Report:** New VGIC code taking xarray lock while holding `irq_lock`; forwarding setup without vPE availability check; silent vLPI unmap errors.

## Stage-2 Page-Fault Handler Races

- **PFN Leak on Error:** Every error path in `user_mem_abort()` that has resolved a PFN must release it before returning.
- **Memcache Init:** `kvm_mmu_memory_cache` pointer must be initialized before use; uninitialized pointer causes NULL-deref.
- **vma_shift Staleness:** `vma_shift` computed at fault-entry may be stale after concurrent VMA modification; re-check after taking `mmu_lock`.

**Report:** Error paths returning without releasing PFN; uninitialized `kvm_mmu_memory_cache` dereference.

## GICv3 Trap Ordering (ICH_HCR_EL2)

- **ICH_HCR_EL2.En:** Changes are not visible to subsequent guest execution without a forced guest exit; always follow En changes with an exit cycle.
- **Entry ordering:** GICv3 trap bits in `ICH_HCR_EL2` must be resynchronized before loading LRs/VMCR on guest entry.
- **pKVM divergence:** Protected and non-protected guests have different GICv3 trap init paths; the wrong path silently disables traps.

**Report:** `ICH_HCR_EL2.En` modified without subsequent guest exit; guest-entry loading LRs before resynchronizing trap bits.
