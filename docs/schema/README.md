# JSON schemas

| File | Describes |
|------|-----------|
| `verified-result.schema.json` | `verified-result.json` (schema-version 2), written by the `re-verify-kreview` command (`~/.claude/commands/re-verify-kreview.md`). Strict, kebab-case keys only. |
| `review-inline.schema.json` | `review-inline.json` written by this agent. Findings are open-ended (`additionalProperties`). |

Later-fix keys, identical in both files:

- `fix-status`: `fixed` (a later commit already in `origin/<target>`), `fixed-upstream` (fix exists upstream only), `not-fixed`; null for pruned findings.
- `future-fix`: fixing commits with location, e.g. `5bf62f727580 (origin/SL-16.0); 89f0addeee3c (upstream)`; null if none.

The agent sets them in the later-fix check (`analysis/fix_checker.py`): it searches `<commit>..origin/<target>` of the current repository (`--target-branch`, default `$TARGET`) and `<upstream-commit>..origin/master` of the upstream repository. Disable with `--no-fix-check`.

Naming caveat: top-level keys of `review-inline.json` are kebab-case, but per-finding keys written by the LLM stay underscore (`upstream_status`, with values `present_in_upstream`/`downstream_only`), whereas `verified-result.json` uses `upstream-status` with `present-in-upstream`/`downstream-only`.
