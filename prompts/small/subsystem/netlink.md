# Netlink / Generic Netlink uAPI Details

Source: `Documentation/userspace-api/netlink/` and `Documentation/core-api/netlink.rst`. Apply when reviewing Netlink families, commands, attributes, dumps, extended ACK, or YAML specs under `Documentation/netlink/specs/`.

Netlink messages reaching user space are uAPI and cannot be changed after release.

## Design rules for new families

Rules below apply to new families only; ignore if already broken within the family.

- First attribute and command ID must be `1`; avoid `unspec` (value `0`).
- Use the same command ID for request and reply; use a separate command ID per notification.
- New families must use the `unified` message-ID model; `directional` is legacy only.
- A `do` operation must never reply with multiple messages / `NLM_F_MULTI`; use a filtered dump instead.
- `kernel-policy` must be `per-op` (default) or `split`; never `global` for new families.
- Do not introduce new uses of request-type-specific flags (`NLM_F_REPLACE`, `NLM_F_EXCL`, `NLM_F_CREATE`, `NLM_F_APPEND`, `NLM_F_NONREC`, `NLM_F_BULK`, `NLM_F_ATOMIC`, `NLM_F_ROOT`, `NLM_F_MATCH`); deprecated outside legacy families.

## Replies, ACKs and notifications

- All operations (especially `NEW`/`ADD`) must reply with a full message carrying identifying info (e.g. allocated ID); do not rely on `NLM_F_ECHO` for created-object info.
- When emitting a notification in response to a request, pass request info to `genl_notify()` so `NLM_F_ECHO` is honored.

## Dumps

- If iteration may skip or repeat objects (e.g. lockless structures), set `NLM_F_DUMP_INTR`; implement via generation counter recorded in `netlink_callback.seq`.

## Extended ACK

- Provide extended ACK on errors and in the success path (warnings) where useful.
- Prefer `NL_SET_BAD_ATTR` (bad attribute) and `NL_SET_ERR_ATTR_MISS` (missing attribute) over plain text messages. Omit plain text if errno + attribute info sufficiently explain the problem.

## Attribute design

Always verify `nla_get_*`/`nla_put_*` type agrees with the YAML spec and validation policy.

- Prefer repeated (`multi-attr`) attributes for arrays; no extra nesting, `indexed-array`, or `type-value` for new families.
- Avoid binary structures inside attributes; break each member into its own attribute.
- Prefer `uint`/`sint` (variable-width 64-bit) over fixed-width integers.
- Avoid integer types smaller than 32 bits; they save no memory due to 4-byte alignment, unless the value is genuinely u8/u16 (e.g. a protocol header field).
- For 64-bit integers in legacy fixed structs, use the `pad` attribute (one per attribute set max).
- Strings default to NUL-terminated (`NLA_NUL_STRING`); only set `unterminated-ok` for legacy. `max-len` excludes the terminator (write `max-len: CONST - 1`).

## Validation policy

- New Generic Netlink families must reject unknown attributes (default for new families and those opting into strict checking).
- Declare the correct `NLA_POLICY_*` instead of open-coded validation.

## YAML spec hygiene

- An attribute's `value` is defined only in its main set, never in a `subset-of` fractional set.
- License must be `((GPL-2.0 WITH Linux-syscall-note) OR BSD-3-Clause)`.
- Specs must be self-contained; use `header` property only for shared constants (e.g. `IFNAMSIZ`).
- Each major property should carry a `doc`.
- Prefer `notify:` over `event:` unless information is never queried directly via GET.
- For `netlink-raw` sub-messages: selector attribute must appear before the sub-message attribute; resolution uses value closest to the selector; missing selector is an error.
- YAML structs are implicitly C-packed; add explicit padding members for natural alignment.
- Names in YAML specs use dashes, not underscores (code gen converts them).
