# Selftests Subsystem Details

## Build System and Installation

Makefile variables controlling installation:

| Variable | Purpose |
|----------|---------|
| `TEST_PROGS` | Executable test scripts run directly |
| `TEST_FILES` | Supporting files (libraries, sourced scripts, Python modules) |
| `TEST_GEN_FILES` | Generated files produced during build |
| `TEST_GEN_PROGS` | Generated executable test programs |

Key invariants:
- Files referenced via `source`/`.` (bash) or `import` (Python) must be in `TEST_FILES`
- Executable scripts go in `TEST_PROGS`; helper binaries go in `TEST_GEN_PROGS`/`TEST_GEN_FILES`
- Missing `TEST_FILES` entry: tests work in source tree but fail after `make install`

## KVM Selftests: IRQ Chip Setup and `vm_create` vs `vm_create_with_one_vcpu`

`vm_create(nr_runnable_vcpus)` sizes memory but does **not** create vCPUs or finalize the IRQ chip. On arm64, VGIC finalization requires all vCPUs present first. On riscv/loongarch, IRQ chip ioctls fail with `-ENODEV`.

`kvm_arch_has_default_irqchip()` returns:
- `true`: x86 (IOAPIC/PIC/LAPIC), s390, arm64 (when GICv3 available)
- `false`: riscv, loongarch

Tests using `KVM_IRQFD`, `KVM_IRQ_LINE`, or IRQ routing must:
1. Call `TEST_REQUIRE(kvm_arch_has_default_irqchip())` to skip unsupported architectures
2. Use `vm_create_with_one_vcpu()` (not `vm_create()`) to ensure vCPU creation and IRQ chip finalization

```c
// WRONG
vm = vm_create(1);
kvm_irqfd(vm, gsi, eventfd, 0);

// CORRECT
TEST_REQUIRE(kvm_arch_has_default_irqchip());
vm = vm_create_with_one_vcpu(&vcpu, NULL);
kvm_irqfd(vm, gsi, eventfd, 0);
```

## Quick Checks

- **New shared files**: Verify sourced/imported files are in `TEST_FILES` in the Makefile
- **`TEST_PROGS` vs `TEST_FILES`**: Mixing causes execution failures or missing installations
- **KVM IRQ chip tests**: Require `vm_create_with_one_vcpu()` and `TEST_REQUIRE(kvm_arch_has_default_irqchip())`
