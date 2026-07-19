# KVM Subsystem Details

## API and ABI Quick Checks

- **New guest-visible features default off and are enumerable.** New ioctls, capabilities, exit reasons, or emulated instructions must be off by default and discoverable via `KVM_CHECK_EXTENSION`/`KVM_CAP_*`, `KVM_GET_SUPPORTED_CPUID2` (x86), or ID-register bits (ARM64).
- **No guest/host-userspace-reachable `WARN_ON`/`BUG_ON`.** Adversary-reachable assertions are host-side DoS. Convert to `pr_warn_once()`, return an error, or drop the assertion.
- **Long loops over guest-driven counts are a known bug class.** Loops over memslots, vCPUs, GFN ranges, rmaps/SPTEs with per-iteration MMU activity risk soft-lockup/RCU stalls. No universal fix—treat as background context for new long-running paths.
- **New memslot and vCPU flags default to immutable.** Flags must be set-once unless explicitly justified; mutable flags create state-machine transitions callers are not prepared for.

## KVM Locking Hierarchy

Authoritative order: `Documentation/virt/kvm/locking.rst`. The bullets below capture specific reviewer-actionable failure modes.

- **SRCU Constraint:** `synchronize_srcu(&kvm->srcu)` is called while holding `kvm->lock`, `vcpu->mutex`, or `kvm->slots_lock`; therefore none of these may be acquired inside `srcu_read_lock(&kvm->srcu)`.
- **`slots_arch_lock` Exception:** May be acquired inside an SRCU read-side critical section.
- **MMU Notifier Sleep Safety:** `invalidate_range_start`/`_end` MUST NOT take `kvm->slots_lock` or `kvm->slots_arch_lock`.

**REPORT as bugs:**
- Acquiring `kvm->lock`, `vcpu->mutex`, or `kvm->slots_lock` inside SRCU read-side critical section.
- Holding `vcpu->mutex` then acquiring `kvm->lock`.
- Sleepable operations (`kzalloc` without `GFP_ATOMIC`, `mutex_lock`, `copy_from_user`) while holding `kvm->mmu_lock`.

## Memory Management and Memslots

- **Memslot Read-Side:** Fast-path access (page faults, emulation) requires `kvm->srcu` held.
- **Writer Exception:** Access without SRCU is permitted only with `kvm->slots_lock` held.
- **Update API:** All memslot changes MUST go through `kvm_set_memory_region()`; manual struct modification is forbidden.

**REPORT as bugs:**
- Accessing memslots or calling `gfn_to_hva()` without `kvm->srcu` (outside writer context).
- Manual flag modification in memslot structs outside the official update path.

```c
// CORRECT
int idx = srcu_read_lock(&kvm->srcu);
struct kvm_memslots *slots = kvm_vcpu_memslots(vcpu);
hva = __gfn_to_hva_memslots(slots, gfn);
srcu_read_unlock(&kvm->srcu, idx);
```

## Invalidation Retry Protocol (MMU Notifiers)

**Mandatory sequence for page fault handling:**
1. Capture `mmu_invalidate_seq`.
2. Resolve GPA/HVA to PFN.
3. Acquire `kvm->mmu_lock`.
4. Check `!mmu_invalidate_retry(kvm, captured_seq)`.
5. Install mapping.
6. Release `kvm->mmu_lock`.

- `mmu_invalidate_retry_gfn_unsafe()` is a valid fast-path optimization; it does NOT replace the gating check under `kvm->mmu_lock`.

**REPORT as bugs:**
- Installing a mapping based only on an unsafe retry check without re-checking under `kvm->mmu_lock`.
- Resolving PFN before capturing the sequence or after acquiring the lock.
- Dropping `kvm->mmu_lock` between the retry check and page table entry installation.

## VCPU Lifecycle and Preemption

`vcpu_load()`/`vcpu_put()` MUST be paired around operations touching physical-CPU-dependent state. `vcpu_load()` registers preempt notifiers; missing `vcpu_put()` causes leaked notifiers and NULL dereferences in `kvm_sched_out()`.

**REPORT as bugs:** Missing `vcpu_load()`/`vcpu_put()` around KVM IOCTLs modifying architectural or hardware-switched state.

## Quick Checks

- **VCPU Requests:** `kvm_make_request()` issues `smp_wmb()` internally; callers MUST NOT add manual barriers around it.
- **SPTE hardware-shared bits:** Updates to Dirty/Access bits on leaf SPTEs must use atomic operations (XCHG, atomic AND, `cmpxchg`); non-leaf SPTEs for bits the arch doesn't track can use plain writes.
- **`cpus_read_lock()` placement:** Must be taken outside `kvm_lock`. Flag any new path calling `cpus_read_lock()` with `kvm_lock` already held.
- **MMU Notifier Pairing:** Each `invalidate_range_start()` must be paired with exactly one `invalidate_range_end()` on the same memslots array.

## Dirty Ring and Dirty Bitmap

- **Ring-to-Bitmap Flush:** When dirty ring is full, dirty info MUST be flushed unconditionally to backup bitmap before clearing. Conditional flushes silently lose pages.
- **Bitmap Range Alignment:** `KVM_CLEAR_DIRTY_LOG` ranges must be 64-bit aligned; unaligned ranges corrupt adjacent dirty state.

**REPORT as bugs:** Conditional dirty-ring bitmap flush paths; `KVM_CLEAR_DIRTY_LOG` handlers without alignment checks.

## pfn Cache and Private Memslots

- **gfn→pfn Cache Refresh:** MUST re-check `mmu_invalidate_seq` after pinning the page; uses the same sequence-counter discipline as the MMU notifier retry protocol.
- **Private Memslot Overlap:** Public and private (guest_memfd) memslots MUST NOT overlap in GPA space; enforced during `KVM_SET_USER_MEMORY_REGION2` handling.

**REPORT as bugs:** Cache refresh paths skipping post-pin sequence re-check; `KVM_SET_USER_MEMORY_REGION2` handlers permitting GPA overlap between private and public memslots.
