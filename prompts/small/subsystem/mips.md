# MIPS Subsystem Details

## TLB Duplicate Entry Hazards

TLB shutdown (`ST0_TS` bit in `CP0_Status`) is fatal — the processor halts and `do_mcheck()` cannot recover. Triggered by duplicate TLB entries during `TLBP`, `TLBWI`, or `TLBWR`.

**Affected CPU families:** R4x00, microAptiv/M5150, Cavium OCTEON3, SB1.

**Dangerous initial states:** Bootloaders may leave pathological TLB state (e.g., SGI IP22 PROM sets all entries to the same VPN). Never assume clean TLB at kernel entry.

**Safe vs unsafe during init:**

| Operation | Instruction | Safety |
|-----------|-------------|--------|
| Indexed read | `TLBR` via `tlb_read()` | Safe |
| Content probe | `TLBP` via `tlb_probe()` | Unsafe |
| Indexed write | `TLBWI` via `tlb_write_indexed()` | Unsafe if creates duplicate |
| Random write | `TLBWR` via `tlb_write_random()` | Unsafe if creates duplicate |

**Safe initialization pattern** (`r4k_tlb_uniquify()` in `arch/mips/mm/tlb-r4k.c`): read all entries by index first, detect duplicates in software, then overwrite duplicates with unique values via indexed writes.

```c
// WRONG: probe before TLB is validated
tlb_probe();  // DANGER: shutdown if duplicates exist

// CORRECT: indexed reads, then software duplicate detection
for (i = 0; i < tlbsize; i++) {
    write_c0_index(i);
    mtc0_tlbr_hazard();
    tlb_read();           // safe indexed read
    tlb_read_hazard();
    existing_vpns[i] = read_c0_entryhi() & vpn_mask;
}
// detect duplicates in software, overwrite with tlb_write_indexed()
```

Wrappers and hazard barriers defined in `arch/mips/include/asm/mipsregs.h`.

## Quick Checks

- **`tlb_probe()` during init**: Any early-boot use before TLB is uniquified is suspect.
- **`TLBWI`/`TLBWR` creating duplicates**: Only write values known to be unique during init.
- **Bootloader state assumptions**: Never assume zeroed/clean TLB; different bootloaders behave differently.
- **Hazard barriers**: Required between CP0 writes and TLB instructions — `mtc0_tlbr_hazard()`, `tlb_read_hazard()`, `mtc0_tlbw_hazard()`, `tlbw_use_hazard()`.
