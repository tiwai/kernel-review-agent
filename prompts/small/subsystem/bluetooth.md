# Bluetooth Subsystem Details

## Advertisement Instance State Tracking

Using incorrect state indicators for advertisement instances causes silent functional failures (wrongly enabled/disabled advertising).

**Instance 0x00 rules:**
- NOT tracked in `adv_instances` list; `hci_add_adv_instance()` rejects `instance < 1`
- `hdev->cur_adv_instance == 0` means "current selection", NOT that instance 0x00 is active
- `HCI_LE_ADV` flag tracks whether *any* advertising is active, not instance 0x00 specifically
- Only correct check for instance 0x00 enabled state: `hci_dev_test_flag(hdev, HCI_LE_ADV_0)`

**Common mistakes:**
- Using `!hdev->cur_adv_instance` as proxy for "instance 0x00 is active"
- Using `hci_dev_test_flag(hdev, HCI_LE_ADV)` to infer instance 0x00 state

## MGMT Pending Command Lifecycle

`mgmt_pending_valid()` atomically checks AND removes the command from the pending list. After it succeeds, the callback OWNS the memory and MUST call `mgmt_pending_free(cmd)` on ALL exit paths.

**Critical rules:**
- Call `mgmt_pending_free(cmd)` before every return after `mgmt_pending_valid()` succeeds
- Never call `mgmt_pending_remove()` after `mgmt_pending_valid()` -- causes double `list_del` and double free
- If `mgmt_pending_valid()` returns false or `err == -ECANCELED`, do NOT free (callback does not own memory)

```c
// CORRECT
void complete(struct hci_dev *hdev, void *data, int err) {
    struct mgmt_pending_cmd *cmd = data;
    if (err == -ECANCELED || !mgmt_pending_valid(hdev, cmd))
        return;
    if (err) {
        mgmt_cmd_status(...);
        mgmt_pending_free(cmd);  // must free on error path too
        return;
    }
    // success handling...
    mgmt_pending_free(cmd);
}
```

## Variable-Length MGMT Command Structures

Copying variable-length MGMT structs to fixed-size stack variables causes stack-out-of-bounds; `sizeof()` excludes flexible array members.

**Structs with flexible array members:**
- `struct mgmt_cp_set_mesh` -- `u8 ad_types[]`
- `struct mgmt_cp_load_irks` -- `struct mgmt_irk_info irks[]`
- `struct mgmt_cp_load_long_term_keys` -- `struct mgmt_ltk_info keys[]`

**Rules:** Use `DEFINE_FLEX()` to allocate stack space including the flexible array, or work directly via `cmd->param` pointer. Use `min(__struct_size(var), len)` to bound copies.

```c
// WRONG: sizeof excludes FAM, stack-out-of-bounds on access
struct mgmt_cp_set_mesh cp;
memcpy(&cp, cmd->param, sizeof(cp));

// CORRECT
DEFINE_FLEX(struct mgmt_cp_set_mesh, cp, ad_types, num_ad_types, MAX_SIZE);
memcpy(cp, cmd->param, min(__struct_size(cp), len));
```

## Quick Checks

- **Instance 0x00**: verify code does not assume standard `adv_instances` list tracking applies
- **State indicator accuracy**: flag/field checked must track enabled state, not just current selection
- **MGMT completion callbacks**: `mgmt_pending_free()` called on ALL exit paths after `mgmt_pending_valid()` succeeds
- **Variable-length MGMT structs**: structs with flexible array members must not be copied to fixed-size stack variables
