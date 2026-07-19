# I/O Accessors Subsystem Details

## MMIO Accessor Semantics and Endianness

Mixing I/O accessor families on the same FIFO/buffer causes data corruption on big-endian systems.

**Register I/O (with byteswapping):** `readb/w/l()`, `writeb/w/l()` — perform CPU-to-LE endianness conversion plus memory barriers. Use for control/status registers.

**FIFO/Stream I/O (no byteswapping):** `readsb/w/l()`, `writesb/w/l()` — map to `__raw_readN/writeN()`, preserve byte order, no barriers. Use for data FIFOs and stream-oriented hardware.

Bug pattern: using `writesl()`/`readsl()` for bulk transfers but `writel()`/`readl()` for remainder bytes to the same FIFO address. The remainder gets byte-swapped on big-endian; the bulk does not.

```c
// WRONG: mixed families on same FIFO
writesl(fifo, buf, len / 4);
writel(tmp, fifo);           // byteswaps on big-endian

// CORRECT: consistent stream accessors
writesl(fifo, buf, len / 4);
writesl(fifo, &tmp, 1);      // no byteswap
```

Same applies to reads: use `readsl(&tmp, 1)` not `readl()` for FIFO remainders. Reference correct pattern: `i3c_writel_fifo()`/`i3c_readl_fifo()` in `drivers/i3c/internals.h`.

## Quick Checks

- **Bulk vs remainder consistency**: Verify both paths use the same accessor family.
- **FIFO vs register**: FIFOs must use stream accessors exclusively.
- **Big-endian risk**: Flag any FIFO helper that mixes accessor types.
