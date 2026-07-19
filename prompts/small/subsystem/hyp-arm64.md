# ARM64 Hyp (EL2) Subsystem Details

## pKVM Threat Model and Scope

pKVM at EL2 provides fixed guarantees against a defined adversary hierarchy. Scope findings against this model: violations inside are bugs; behavior outside (e.g. host self-DoS) is a hardening improvement.

**What pKVM guarantees:**
- Guest confidentiality vs. Host (EL1 cannot read protected-VM memory/registers)
- Guest integrity vs. Host (EL1 cannot modify protected-VM memory/registers out-of-band)
- Hypervisor integrity vs. Host AND Guests (neither can corrupt EL2 memory or escape stage-2)
- Host availability vs. Guests (a guest cannot crash the host or take down EL2)

**What pKVM does NOT guarantee:**
- Host availability vs. itself (host can panic itself or trigger hyp panic via its own privileged hypercall paths)
- Reliability against firmware/hardware faults (EL3, SMMU, GIC misbehavior is out of scope)

**Reachability test for any panic-reachable EL2 path** (who can trigger it?):

| Trigger source | Verdict |
|---|---|
| EL2 internal invariant violation | Bug in EL2 itself |
| Hardware/firmware error | Out of scope |
| Host kernel, via privileged code paths | Not a bug; hardening if cheap |
| Guest, via DMA/hypercall side-effects/shared memory | **Bug** |
| Host userspace, via syscall/ioctl -> host kernel -> hypercall | **Bug** |

## Host De-Privilege Boundary (pKVM Lifecycle)

The boundary is `finalize_pkvm()` (`arch/arm64/kvm/pkvm.c`, `device_initcall_sync`), which calls `pkvm_drop_host_privileges()`. Before it: host runs at EL2 and can directly set up EL2 state. After it: host is at EL1 and can only invoke EL2 via hypercalls; EL2-private memory becomes inaccessible.

**Grep markers:**
- `__init`/`__initdata`: pre-de-privilege only
- Initcall levels before `device_initcall_sync` (through `device_initcall`) are pre-de-privilege; `late_initcall` and later are post-de-privilege. `module_init` expands to `device_initcall`.
- `__pkvm_init_finalise` (`nvhe/setup.c`): executes during de-privilege, last chance for EL2-private setup from privileged context
- `is_kvm_arm_initialised()`: true post-de-privilege
- `is_protected_kvm_enabled()`: true from cpufeature detection; independent of de-privilege. Privileged window = `is_protected_kvm_enabled() && !is_kvm_arm_initialised()`

**REPORT as bugs:**
- Host-shared memory handling without identifying which side of de-privilege it runs on
- Setup code moved across `finalize_pkvm` boundary without updating trust assumptions
- Runtime hypercall handlers referencing `__init`/`__initdata` symbols (freed after de-privilege)

## EL2 Security & Trust Boundary (pKVM)

Post-de-privilege, the Host (EL1) is an adversary. EL2 MUST NOT derive security-sensitive values from any host-controlled source.

**Untrusted host data sources:**
- **Host memory** (`kern_hyp_va` dereferences): subject to TOCTOU. MUST be copied to private EL2 memory before validating or acting on it.
- **System registers** carrying host-written state (e.g. `SCTLR_EL1`, `HCR_EL2`): use hardcoded architectural constants or EL2-private state instead.
- **Hypercall arguments**: every host-supplied value MUST be validated and bounds-checked. Register-passed scalars (captured via `DECLARE_REG`) are EL2-private once in a local variable; the copy-then-validate rule applies to host-memory pointers via `kern_hyp_va`.

**Double-Fetch Rule:** Never dereference a host-provided pointer more than once. Copy needed fields to EL2 private memory once.

**VA Translation:** Use `AT S12E1R` for stage 1+2 translation of Host VA. Failure reported in `PAR_EL1` (bit `.F = 1`). Targeted regime (EL1&0 vs EL2&0) depends on `HCR_EL2.{E2H, TGE}`.

**REPORT as bugs:**
- Dereferencing a host pointer multiple times without an intervening copy to private EL2 memory
- Logic assuming a value in host-shared structure remains constant between check and use
- Reading security-sensitive state from host-writable registers

```c
// WRONG: double fetch + stack overflow risk
void handle_hcall(struct kvm_vcpu *host_vcpu) {
    if (vcpu_has_sve(kern_hyp_va(host_vcpu)))  // fetch 1
        do_sve(kern_hyp_va(host_vcpu));         // fetch 2
    struct kvm_vcpu local_vcpu = *kern_hyp_va(host_vcpu); // ~4KB stack
}
// CORRECT: copy once to private memory, then validate
void handle_hcall(struct vcpu_reset_args *host_args) {
    struct vcpu_reset_args local_args;
    memcpy(&local_args, kern_hyp_va(host_args), sizeof(local_args));
    if (local_args.flags & VALID_FLAG)
        update_hyp_state(&local_args);
}
```

## pKVM/nVHE Invariants (EL2)

### Security Metadata Initialization
Security-critical metadata (e.g. `hyp_vmemmap`) MUST use initialization that evaluates to least-privileged/"unowned" state. pKVM uses complement-based state where zero-init evaluates to `PKVM_NOPAGE`.
- **REPORT:** Code comparing page state directly to zero or assuming zero-filled metadata means "owned by hypervisor."

### Stage-2 VMID & Consistency
`VTTBR_EL2` and `VTCR_EL2` need not be identical across PEs for a VMID provided `VTTBR_EL2.CnP == 0`.
- **REPORT:** Setting `VTTBR_EL2.CnP = 1` when translation table pointers differ for the same VMID (CONSTRAINED UNPREDICTABLE).

### Fine-Grained Traps (FEAT_FGT)
FGT register accesses may be reordered. A CSE (e.g. `isb` or exception return) MUST follow enabling a trap to guarantee it is active for subsequent instructions.

### SMC Trapping
AArch64 guest `SMC` trapped via `HCR_EL2.TSC=1`: `ESR_EL2.EC = 0x17`. AArch32 `SMC32`: `EC = 0x13`. `SPSR_EL2.SS` captures `PSTATE.SS` of trapped EL1 context.

## State Divergence & Initialization Boundaries

| Host State | EL2 Hyp State | Sync Mechanism |
| :--- | :--- | :--- |
| `struct kvm` | `struct pkvm_hyp_vm` | `pkvm_create_hyp_vm()` |
| `struct kvm_vcpu` | `struct pkvm_hyp_vcpu` | Hypercall Parameters |
| ID Registers | Hyp-Private ID Regs | Sanitisation in `pkvm_hyp_vm` |

- `pkvm_hyp_vm` embeds `struct kvm kvm` (EL2-private, trusted after init) and holds `struct kvm *host_kvm` (untrusted, TOCTOU applies). Same distinction for `pkvm_hyp_vcpu`: `hyp_vcpu->vcpu` is EL2-private; `hyp_vcpu->host_vcpu` is untrusted.
- **Persistent State Rule:** Stack copies from host memory are for validation only. Persistent changes MUST be synchronized to EL2-private hyp structures.

## EL2 Buddy Allocator (`hyp_pool`)

Only page allocator at EL2 (no `kmalloc`, no `alloc_pages`). One global pool (`hpool`) plus one per protected VM (`hyp_vm->pool`).

**API** (EL2-only):
- `hyp_alloc_pages(pool, order)`: returns refcount=1 zeroed page; NULL on OOM
- `hyp_get_page(pool, addr)`: increments refcount
- `hyp_put_page(pool, addr)`: decrements; on last ref, page is **zeroed and returned to buddy tree**
- `hyp_split_page(page)`: breaks high-order block into order-0 pages; each must be put separately
- `hyp_pool_init(pool, pfn, nr_pages, reserved_pages)`: `reserved_pages` kept at refcount 1, never enter free tree
- `hyp_page_count(addr)`: returns current refcount

**Invariants:**
- `pool->lock` protects both the buddy tree and per-page metadata (`refcount`, `order`). Refcount changes that may trigger tree updates MUST happen inside the same critical section.
- `HYP_NO_ORDER` convention: only head `struct hyp_page` of a high-order block carries its order; tail pages carry `HYP_NO_ORDER`. Walkers inspecting `->order` must handle this.
- Every `hyp_put_page` must use the same pool the page was allocated from.
- `__hyp_attach_page` accepts pages outside `[range_start, range_end)` at order 0 without coalescing (host donations); this is not a bug.

**REPORT as bugs:**
- Touching `page->refcount` or `page->order` without `pool->lock`
- Treating `hyp_alloc_pages()` failure as fatal (`WARN_ON`/`BUG_ON`); `-ENOMEM` is normal
- Allocating from one pool and freeing into another

## pKVM Page-Ownership Transitions

Ownership transitions (share, unshare, donate) are the highest-density pKVM bug pattern and are directly reachable from the host.

- **Validate before transition:** Every hypercall initiating an ownership transition MUST validate the supplied range (base, size) against current ownership state BEFORE modifying EL2 metadata.
- **Cross-check after transition:** EL2 MUST verify the resulting ownership state is consistent with what was requested.
- **Atomicity:** Ownership metadata and page-table entries MUST be updated atomically from EL2's perspective. Partial updates create TOCTOU windows.
- **Reclaim path:** Must enumerate pages by recorded ownership state, not page-table walk. Pages donated but not metadata-updated are leaked.

**REPORT as bugs:**
- Ownership transition hypercalls proceeding without fully validating the supplied range against current EL2 metadata
- Reclaim/teardown paths walking the page table rather than ownership metadata

## FF-A Interface Validation

- **Offset and Length:** Every FF-A memory-sharing hypercall accepting a buffer descriptor MUST validate `offset` and `length` against actual buffer size before dereferencing. Missing checks allow out-of-bounds EL2 memory reads.
- **Version Negotiation:** EL2 MUST enforce the agreed FF-A version; downgrade responses from EL3 must be rejected, not silently used as a higher version. Correct acquire/release ordering required for version-negotiation state.
- **Unsupported Interface Masking:** Optional FF-A 1.1/1.2 interfaces pKVM does not implement MUST be masked in `FFA_FEATURES` responses.

**REPORT as bugs:**
- FF-A handlers using host-supplied offset or length without bounds-checking
- `FFA_FEATURES` responses advertising unimplemented optional interfaces

## Trap Register Initialization and Protected-vs-Unprotected Divergence

- Trap registers (`HFGRTR_EL2`, `MDCR_EL2`, etc.) MUST be initialized in EL2-private context, not from host-written values. Protected VMs: init from hardcoded constants. Non-protected VMs: copy host-set values on VCPU load.
- **FGT registers are EL2-only:** `HFGRTR_EL2`, `HFGWTR_EL2`, `HFGITR_EL2`, `HDFGRTR_EL2`, `HDFGWTR_EL2`, `HAFGRTR_EL2` UNDEF on EL1/EL0. Reading them back after an EL2-side write is safe and NOT a "reading host-written state" violation. The trust rule applies to host-writable registers like `SCTLR_EL1` or `HCR_EL2`.
- **Copy on VCPU Load:** Non-protected guests: FGT registers MUST be copied from `hyp_vcpu->host_vcpu->arch.fgt` to `hyp_vcpu->vcpu.arch.fgt` on each VCPU load.
- MTE and ID register initialization for protected VMs must follow the protected-VM path, not non-protected.

**REPORT as bugs:**
- Hyp code reading trap configuration from host-written registers
- VCPU-load paths not refreshing the hyp-side FGT copy from host VCPU

## SMC imm16 / SMCCC Pass-Through Rules

The host is only permitted to use `SMC` with `imm16 == 0`. Any `SMC` with non-zero `imm16` MUST be rejected by EL2 before forwarding to EL3.

**REPORT as bugs:**
- SMC pass-through paths forwarding to EL3 without checking `imm16 == 0`

## Huge-Page Handling under pKVM

- **Protected-Mode Size Validation:** When installing a stage-2 mapping for a protected VM, the mapping granule MUST be validated against the requested fault granule. Installing a larger block mapping for a page-size fault silently breaks isolation.
- **Range Adjustment on Stage-2 Fault:** Range covered by a fault must be computed from the IPA and the level of the faulting entry, not from the host-supplied VMA shift.

**REPORT as bugs:**
- Protected-mode fault handlers installing block descriptors without verifying granule matches fault size
- Fault handlers deriving mapping range from host VMA shift without re-validating against IPA alignment

## `WARN_ON` Semantics at EL2

At EL2 nVHE, both `BUG_ON()` and `WARN_ON()` expand to `BRK`, which the hyp panic handler treats as **fatal**. There is no "warn and continue" at EL2. Code after a triggered `WARN_ON` is unreachable.

**Test for any `WARN_ON(cond)` at EL2:** can `cond` evaluate true through contract-permitted input, or only through violation of EL2's own invariants?
- *Through contracted inputs* (`WARN_ON` wrong): host-supplied input post-de-privilege, allocator/lookup outcomes, hardware return values, concurrency races — function should error-return instead.
- *Only through invariant violation* (`WARN_ON` correct): values from EL2's own just-completed state (a slot EL2 just populated being NULL, a refcount EL2 just incremented being zero).

A `WARN_ON` wrong by this test is a *correctness* finding. Whether it is also a *bug* is judged by the reachability test: host-kernel-only reachable = hardening improvement; guest- or host-userspace-reachable = bug.

**Dead-branch trap:** `WARN_ON(err); do_fallback();` or `if (WARN_ON(err)) goto out;` at EL2 does NOT execute recovery — the WARN path panics. The error-handling code is dead.

### BUG() and hyp_panic() are equivalent at EL2 nVHE

`BUG()` at EL2 nVHE expands to `BRK BUG_BRK_IMM`, caught by `kvm_unexpected_el2_exception`, which calls `hyp_panic()`. Both forms terminate with a hyp panic. `BUG()` is the house style (6 call sites in `nvhe/` vs. 2 direct `hyp_panic()`). **Do not flag a `BUG()` <-> `hyp_panic()` substitution as a regression.**

## Quick Checks

- **Dead State Invariant:** On any fatal initialization error or host-triggered corruption, the VM MUST be marked "dead" (e.g. `is_dying` in `struct kvm_protected_vm`) to prevent resource reassignment logic from running on corrupted metadata.
- **Asynchronous Engine Synchronization:** Clearing control/enable bits for async hardware engines (profiling, tracing, debug extensions) is insufficient to stop speculative page table walks. When switching translation regimes (Guest <-> Host), software MUST execute the architecturally mandated synchronization sequence (e.g. `PSB CSYNC` for profiling) followed by a speculative execution barrier (`SB`, or `DSB` + `ISB`).
  - **REPORT:** Code disabling an async feature without a subsequent synchronization barrier before changing translation context (e.g. updating `VTTBR_EL2` or `TTBRn_ELx`).
