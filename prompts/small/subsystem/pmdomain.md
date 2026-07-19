# Power Domain Subsystem Details

## genpd stay_on and sync_state Interaction

When `CONFIG_PM_GENERIC_DOMAINS_OF` is enabled and a domain initializes as on (`is_off=false`), `pm_genpd_init()` calls `genpd_set_stay_on()`, setting `genpd->stay_on = true` unless `GENPD_FLAG_NO_STAY_ON` is set. `genpd_power_off()` refuses to act while `stay_on` is true.

`stay_on` is cleared when the provider's `sync_state` callback runs (`genpd_provider_sync_state()` or `of_genpd_sync_state()`). `sync_state` only fires after all consumers probe; if a consumer never probes, `sync_state` never fires in strict mode, and the domain stays on forever, wasting power.

- `fw_devlink.sync_state=timeout` / `CONFIG_FW_DEVLINK_SYNC_STATE_TIMEOUT` gives up waiting after `deferred_probe_timeout`.
- `GENPD_FLAG_NO_STAY_ON` skips setting `stay_on`, allowing power-off without waiting for `sync_state`.
- Platforms using `GENPD_FLAG_NO_STAY_ON`: Renesas R-Car, R-Mobile, Rockchip, Tegra BPMP.
- Without `CONFIG_PM_GENERIC_DOMAINS_OF`, `genpd_set_stay_on()` sets `stay_on = false` unconditionally (mechanism inactive).

## genpd_power_off_unused and Regulator Cleanup Ordering

`genpd_power_off_unused()` runs at `late_initcall_sync`, skipping domains with `stay_on == true`. `regulator_init_complete()` also runs at `late_initcall_sync` but delays regulator disable by 30 seconds via `regulator_init_complete_work`. If `stay_on` is never cleared (no `sync_state`), the domain may still be powered when the regulator is finally disabled, causing hardware malfunction. Rockchip sets `GENPD_FLAG_NO_STAY_ON` specifically to avoid this.

## Platform-Specific Workaround Conditionals

Workarounds must be gated on the affected platform using:
- Architecture checks (`IS_ENABLED(CONFIG_ARM)`)
- Device compatibility checks (`of_device_is_compatible()`)
- Platform-specific DT properties

Bootloader handover power resets must occur early in probe, before `pm_genpd_init()` registers the domain in `gpd_list`. Prefer explicit per-driver power-off functions (e.g., `exynos_pd_power_off()`) over `of_genpd_sync_state()`, which iterates and powers off all domains for a provider.

## Platform Default Domain States

- MediaTek: `MTK_SCPD_KEEP_DEFAULT_OFF` flag causes `pm_genpd_init()` with `is_off=true`.
- Renesas/Rockchip: use `GENPD_FLAG_NO_STAY_ON` to allow power-off without `sync_state`.
- Core genpd changes altering default on/off behavior must be verified against platform drivers relying on these mechanisms.

## Quick Checks

- **`of_genpd_sync_state()` as sync_state callback**: Iterates all provider domains and powers each off — verify this is correct for all domains, not just specific ones.
- **`GENPD_FLAG_NO_STAY_ON` on new drivers**: Required for platforms with regulator-supplied power domains or unreliable `sync_state` invocation.
- **Core genpd timing changes**: Any new default that delays or prevents power-off must provide a `GENPD_FLAG_*` opt-out for platforms that cannot tolerate it.
