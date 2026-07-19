# USB Storage Subsystem Details

## unusual_devs.h Entry Conventions

Specifying unnecessary subclass/protocol overrides causes `get_device_info()` to emit a `dev_notice` on every device insertion. Use `USB_SC_DEVICE`/`USB_PR_DEVICE` unless the device mis-reports its values.

`UNUSUAL_DEV()` positional args (7th=subclass, 8th=protocol):

```c
UNUSUAL_DEV(idVendor, idProduct, bcdDeviceMin, bcdDeviceMax,
            vendor_name, product_name,
            use_protocol,   /* USB_SC_* subclass */
            use_transport,  /* USB_PR_* protocol */
            init_function, Flags)
```

Note: field names are confusing -- `useProtocol` holds `USB_SC_*`, `useTransport` holds `USB_PR_*`.

| Value | Meaning |
|---|---|
| `USB_SC_DEVICE` (0xff) | Use device's self-reported `bInterfaceSubClass` |
| `USB_PR_DEVICE` (0xff) | Use device's self-reported `bInterfaceProtocol` |
| Specific `USB_SC_*`/`USB_PR_*` | Override device values (only when device mis-reports) |

`US_FL_NEED_OVERRIDE` suppresses the redundancy warning for intentional overrides. ~85% of entries use `USB_SC_DEVICE, USB_PR_DEVICE`.

Cross-check with `/sys/kernel/debug/usb/devices`: `Sub=06` = `USB_SC_SCSI`, `Prot=50` = `USB_PR_BULK`. If the entry specifies these explicitly and the device already reports them, the overrides are redundant.

```c
// CORRECT
UNUSUAL_DEV(0x1234, 0x5678, 0x0100, 0x0100, "Vendor", "Product",
    USB_SC_DEVICE, USB_PR_DEVICE, NULL, US_FL_NO_ATA_1X)

// WRONG: redundant when device reports Sub=06 Prot=50
UNUSUAL_DEV(0x1234, 0x5678, 0x0100, 0x0100, "Vendor", "Product",
    USB_SC_SCSI, USB_PR_BULK, NULL, US_FL_NO_ATA_1X)
```

## Quick Checks

- Patch adding explicit `USB_SC_*`/`USB_PR_*` values must explain in commit message why the override is needed.
- If commit includes device descriptor output, compare `Sub=` and `Prot=` fields against the entry's 7th and 8th arguments to detect redundant overrides.
