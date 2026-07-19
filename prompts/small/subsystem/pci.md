# PCI Subsystem Details

## PCI Endpoint Error Return Conventions

`pci_epc_get()` and `pci_epf_create()` return `ERR_PTR()` on failure, not NULL; always check with `IS_ERR()`. `pci_epf_destroy()` dereferences its argument unconditionally — passing an ERR_PTR crashes. `pci_epc_put()` is safe (checks `IS_ERR_OR_NULL()` internally).

## Legacy PCI MSI APIs

`pci_enable_msi()` / `pci_disable_msi()` are legacy and lack MSI-X support. Use `pci_alloc_irq_vectors()` / `pci_free_irq_vectors()` instead:

```c
/* Modern replacement supporting MSI, MSI-X, INTx */
ret = pci_alloc_irq_vectors(pdev, 1, 1, PCI_IRQ_ALL_TYPES);
if (ret < 0)
    return ret;
```

## PCI IRQ Vector Cleanup in Error Paths

Every error path after a successful `pci_alloc_irq_vectors()` must call `pci_free_irq_vectors()` before returning, or IRQ resources leak.

## Device Naming Conventions

Drivers must NOT call `dev_set_name()` on `&pdev->dev` or other bus-owned devices. The PCI subsystem owns device naming; drivers may only name child devices they themselves allocate.

## Quick Checks

- **EPC/EPF return values**: check `pci_epc_get()` / `pci_epf_create()` with `IS_ERR()`, not `!ptr`; never pass error pointers to `pci_epf_destroy()`
- **Legacy MSI API**: flag `pci_enable_msi()` / `pci_disable_msi()` in new code
- **IRQ vector cleanup**: verify all error paths after `pci_alloc_irq_vectors()` call `pci_free_irq_vectors()`
- **Device naming**: verify `dev_set_name()` is not called on `&pdev->dev` or bus-owned structures
