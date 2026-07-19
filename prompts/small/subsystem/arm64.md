# ARM64 Subsystem Details

## Memory Tagging Extension (MTE) and Tagged Addresses

TBI allows MMU to ignore bits [63:56], but software arithmetic MUST call `untagged_addr()` before bit-shifts/masks to prevent tag bits corrupting page-table index calculations. A DSB is required between tag stores (`STG`/`STZG`) and PTE update. Shared pages (e.g., huge zero folio) MUST have tags cleared and visible before the page is mapped.

**REPORT as bugs:**
- Bit-shift/mask on virtual address to find PTE without `untagged_addr()`.
- PTE update for MTE-enabled page without preceding `DSB` after tag writes.
- Shared page made accessible before tag clearing is globally visible.

## System Register and Context Synchronization

Every write to a control-plane system register MUST be followed by `isb()` as the **very next instruction** — not "somewhere later." Any instruction between the write and `isb()` observes architecturally undefined pipeline state.

```c
/* BUG: read-back before isb() */
write_sysreg_s(val, SYS_HFGRTR_EL2);
if (read_sysreg_s(SYS_HFGRTR_EL2) != val)  /* undefined state */
    return -EIO;
isb();  /* too late */
/* CORRECT: write -> isb() -> read-back */
```

- `ICC_*_EL1` writes require `isb()`, except `ICC_PMR_EL1` (self-synchronizing).
- Memory-mapped GIC writes to tracked registers require polling `GICD_CTLR.RWP` or `GICR_CTLR.RWP`. Priority, routing, and enable-set writes are NOT tracked by RWP.

**REPORT as bugs:**
- Any instruction between sysreg write and `isb()`.
- `ICC_*_EL1` write (except `ICC_PMR_EL1`) without `isb()`.
- Tracked GIC MMIO writes without polling RWP.

## TLB Invalidation and Break-Before-Make (BBM)

`TLBI` completion is guaranteed only by a `DSB` on the **same PE** that issued it. Remote PEs cannot use their own `DSB` to complete another PE's `TLBI`. Each observing PE must independently execute `isb()` after the issuing PE's `DSB`.

**BBM required when:** changing block/table size, creating global entry overlapping non-global entries, changing Output Address, or changing memory attributes.

**BBM sequence:** (1) write invalid entry → (2) `DSB` → (3) broadcast `TLBI` → (4) `DSB` → (5) write new entry → (6) `DSB`.

**REPORT as bugs:**
- `TLBI` without subsequent `DSB` + `isb()` on issuing CPU.
- Missing `isb()` after TLBI in mode-entry paths (`enter_vhe()`, `__tlb_switch_to_guest()`, `__primary_switch()`).
- Live PTE update (OA change or attribute change) without invalidation.
- Block/page mapping changes without gating on `FEAT_BBML2` support.

## Instruction and Data Coherency (PoC vs PoU)

**Self-modifying code (JIT):** DC CVAU → DSB ISH → IC IVAU → DSB ISH → `isb()` on all observing CPUs.

**Instruction patching (CMODX):** Safe without `isb()` only for: `B`, `B.cond`, `BL`, `BRK`, `CB<cc>`, `CBB<cc>`, `CBH<cc>`, `CBNZ`, `CBZ`, `HVC`, `ISB`, `NOP`, `SMC`, `SVC`, `TBNZ`, `TBZ`, `TRCIT`, `UDF`. All other instructions require `isb()`/CSE on all observing CPUs.

**External agents:** Non-coherent DMA requires clean/invalidate to PoC (`DC CVAC`).

**REPORT as bugs:**
- Instruction patching outside the CMODX set without `isb()`/CSE on all executing CPUs.

## Lockless Page Table Walks

- Use `READ_ONCE()` for all descriptor loads from shared page tables in lockless walks.
- Account for folded levels (`PGTABLE_LEVELS <= 2`); standard multi-level patterns on folded levels observe stale state.

**REPORT as bugs:**
- Shared PTE/PMD/PUD/PGD dereference in lockless walk without `READ_ONCE()`.
- Lockless walk assuming all levels are live without checking folded-level conditions.

## Exception Handling and Stack Management

- DAIF asynchronous exceptions MUST be masked during stack transitions/pivots (e.g., Shadow Call Stack switch). An exception mid-transition causes fatal recursive faults.
- `SCTLR_ELx.SA` enforces 16-byte SP alignment on memory access via SP at ELx; `SCTLR_EL1.SA0` for EL0.

**REPORT as bugs:**
- SP manipulation or stack switching without masking DAIF.

## SVE, SME, and FPSIMD Register State

- VL change MUST invalidate/rebuild all context derived from old VL (buffers, register views, ptrace payloads).
- Entering streaming SVE mode requires explicit SVE payload; inheriting non-streaming state is incorrect.
- Signal return MUST merge FPSIMD and SVE state in a single coherent step; partial or misordered merges corrupt Z-register upper halves.

**REPORT as bugs:**
- VL-change paths skipping SVE/SME context invalidation for new length.
- Signal-return paths with incorrect or non-atomic FPSIMD/SVE merge.

## Quick Checks

- **Fixed-register instructions:** Inline asm for instructions requiring specific registers (e.g., GIC CDEOI requiring `XZR`) MUST hardcode the register; compiler constraint `r` may select a wrong register causing CONSTRAINED UNPREDICTABLE.
- **CONSTRAINED UNPREDICTABLE:** From invalid encodings or register overlaps; behavior is UNKNOWN (NOP, UNDEFINED, or fault). MUST NOT be relied upon.
- **TLBI range operands:** `SCALE`/`NUM` must be correctly encoded; `TG` mismatch with current granule makes the TLBI CONSTRAINED UNPREDICTABLE.
- **PTE barrier batching:** Batching DSB/ISB across multiple PTE updates is only safe in non-interruptible contexts; interrupt contexts break the window and require an explicit barrier.
