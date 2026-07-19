# SMB/ksmbd Subsystem Details

## SMB Direct (RDMA) Credit Grant Ordering

The negotiate response must be the first message that grants credits to the peer; sending credit-granting messages before it causes protocol violations.

Both `smb_direct_send_negotiate_response()` and `smb_direct_create_header()` set `credits_granted` via `manage_credits_prior_sending()`.

Work items that can trigger premature credit grants:

| Work item | Handler | Effect |
|---|---|---|
| `recv_io.posted.refill_work` | `smb_direct_post_recv_credits()` | Posts recv buffers, queues `idle.immediate_work` if credits posted |
| `idle.immediate_work` | `smb_direct_send_immediate_work()` | Sends empty PDU carrying `credits_granted` |

**Required initialization order** (`smbdirect_socket_init()` initializes all work items with a dummy disabled handler; real handlers assigned later):

```c
// 1. refill_work gets real handler and runs; idle.immediate_work still disabled
INIT_WORK(&sc->recv_io.posted.refill_work, smb_direct_post_recv_credits);
smb_direct_post_recv_credits(&sc->recv_io.posted.refill_work);
// 2. Now idle.immediate_work gets real handler
INIT_WORK(&sc->idle.immediate_work, smb_direct_send_immediate_work);
// 3. Negotiate response sent (first actual credit grant)
ret = smb_direct_send_negotiate_response(sc, ret);
```

## Quick Checks

- Removing `disable_work_sync()` calls or reordering `INIT_WORK()` in `smbdirect_socket_init()` can expose premature credit grants.
- Converting `delayed_work` to `work_struct` (or vice versa) may open a timing window before the negotiate response.
