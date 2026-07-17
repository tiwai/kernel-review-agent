# Fixes: Tag Verification

When a Fixes: tag is present, verify each tag:

1. **SHA-1**: minimum 12 hex characters
   - Check: `git cat-file -t <sha>` returns "commit"
   - Check: `git merge-base --is-ancestor <sha> HEAD` succeeds

2. **Format**: `Fixes: <12+char-sha> ("<original subject>")`
   - Subject in double quotes, on a single line (no wrapping)
   - Verify subject with: `git log -1 --format=%s <sha>`

3. **Placement**: in sign-off area, above the `---` separator

4. **Bug relationship**: confirm the referenced commit actually introduced
   the bug being fixed

5. **Stable tag**: if bug affects released kernels (past 12 months),
   check for `Cc: stable@vger.kernel.org`

Output for each tag: Issues found: [none OR list]
