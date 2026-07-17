# Subjective Review

**Risk**: None, subjective code quality assessment

**When to check**: when subjective reviews are requested (upstream review mode)

IMPORTANT: never flag single dumb grammar changes unless a collection makes the
commit message hard to understand.

**Mandatory commit message validation**
- step 1: Compare commit title and message against actual code changes
  - Output: Commit title, line count of message
- step 2: Verify the changelog is complete (describes all significant changes)
- step 3: Verify the changelog is concise (no unnecessary verbosity)
- step 4: Check that the "why" is explained, not just the "what"
- step 5: Flag missing context that would help reviewers/maintainers

**After analysis:** Issues found: [none OR list]
