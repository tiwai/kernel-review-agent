# ATA Subsystem Details

## Device Validation and Compatibility

ATA devices frequently deviate from ACS specifications in benign ways (zero-filled version fields, non-zero reserved bits, missing optional fields) that do not affect functionality. Strict validation in init paths can break previously-working devices.

**Validation strictness principles:**

- **Warn before failing**: For spec compliance issues that don't affect data integrity, use `ata_dev_warn()` or `ata_dev_warn_once()` rather than returning an error
- **Strict validation requires justification**: Patches adding checks to `ata_dev_configure()`, `ata_read_log_directory()`, or log page parsing must justify why strict enforcement is needed
- **Avoid disabling features**: Setting quirks (e.g., `ATA_QUIRK_NO_LOG_DIR`) or calling `ata_clear_log_directory()` in response to spec deviations can break otherwise-working devices

**When to fail vs warn:**

| Condition | Action |
|-----------|--------|
| Invalid checksums, corrupted structures | Fail |
| I/O errors | Fail |
| Safety-critical features with invalid config | Fail |
| Version mismatch on valid structure | Warn and continue |
| Optional fields not formatted per spec | Warn and continue |
| Reserved bits non-zero | Ignore or warn |

```c
// WRONG
if (version != EXPECTED_VERSION) {
    ata_clear_log_directory(dev);
    dev->quirks |= ATA_QUIRK_NO_LOG_DIR;
    return -EINVAL;
}
// CORRECT
if (version != EXPECTED_VERSION)
    ata_dev_warn_once(dev, "Unexpected version 0x%04x", version);
// continue using data if otherwise valid
```

## Quick Checks

- **New validation in init paths**: Verify commit message justifies strict enforcement and considers compatibility
- **Programmatic quirk setting**: `ATA_QUIRK_*` set at runtime (not via static `__ata_dev_quirks` table) needs fallback/recovery
- **Error vs warning**: Distinguish functional errors (I/O failures, corruption) from cosmetic spec violations (version mismatches)
