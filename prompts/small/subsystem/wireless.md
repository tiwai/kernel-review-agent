# Wireless Subsystem Details

## mac80211 MLO Callback Structure

mac80211 MLO splits the legacy `bss_info_changed()` into two callbacks in `struct ieee80211_ops`:

- `vif_cfg_changed()`: VIF-global config from `struct ieee80211_vif_cfg`
- `link_info_changed()`: per-link config from `struct ieee80211_bss_conf`

Fallback to `bss_info_changed()` only when neither MLO callback is implemented. Misrouting any flag triggers `WARN_ON_ONCE`. **Authoritative split**: `BSS_CHANGED_VIF_CFG_FLAGS` in `net/mac80211/main.c` — flags in that macro are VIF-global, all others are link-specific.

**VIF-global** (`vif_cfg_changed()`):

| Event | Data location |
|-------|---------------|
| `BSS_CHANGED_ASSOC` | `vif->cfg.assoc` |
| `BSS_CHANGED_IDLE` | `vif->cfg.idle` |
| `BSS_CHANGED_PS` | `vif->cfg.ps` |
| `BSS_CHANGED_IBSS` | `vif->cfg.ibss_joined` |
| `BSS_CHANGED_ARP_FILTER` | `vif->cfg.arp_addr_list` |
| `BSS_CHANGED_SSID` | `vif->cfg.ssid` |
| `BSS_CHANGED_MLD_VALID_LINKS` | `vif->valid_links` |
| `BSS_CHANGED_MLD_TTLM` | MLD TID-to-link mapping |

**Link-specific** (`link_info_changed()`): `BSS_CHANGED_BSSID`, `BSS_CHANGED_BEACON_INFO`, `BSS_CHANGED_BEACON`, `BSS_CHANGED_BEACON_INT`, `BSS_CHANGED_ERP_CTS_PROT`, `BSS_CHANGED_ERP_PREAMBLE`, `BSS_CHANGED_ERP_SLOT`, `BSS_CHANGED_HT`, `BSS_CHANGED_BASIC_RATES`, `BSS_CHANGED_TXPOWER`, `BSS_CHANGED_BANDWIDTH`, `BSS_CHANGED_HE_BSS_COLOR`, `BSS_CHANGED_TPE`.

## Quick Checks

- **VIF vs. link**: consult `BSS_CHANGED_VIF_CFG_FLAGS` in `net/mac80211/main.c` — in macro = VIF-global, else link-specific
- **MLO migration**: every `BSS_CHANGED_*` flag must route to the correct callback; misrouting = `WARN_ON_ONCE`
- **Power save is VIF-global**: `BSS_CHANGED_PS` reads `vif->cfg.ps`, belongs in `vif_cfg_changed()`
