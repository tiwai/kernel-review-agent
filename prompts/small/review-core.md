# Linux Kernel Patch Analysis Protocol (Condensed)

Deep regression analysis of Linux kernel patches.

If given a git range, print numbered list of commits (oldest first, asterisk on analyzed commit).
Analyze only the specified commit, but consider the series when looking for fixes.

## Analysis Philosophy
- Assume patch has bugs including in comments and commit message
- Every change must be proven correct - otherwise report as regression
- New APIs checked for consistency
- C best practice deviations are regressions

## Exclusions
- fs/bcachefs regressions
- Test program issues unless system crash
- Assertion/WARN/BUG removals

## Task 0: Context Management
- Discard non-essential details after each task
- Keep function/type context if needed later
- Plan context gathering before proceeding
- Read full diff line-by-line before analysis
- Document commit intent first

## Task 1: Context Gathering
**Goal**: Build complete understanding of changed code

1. **Identify**: Parse diff for all modified functions and files
2. **Load**: Use `git show <commit>:<path>` for complete functions (never fragments)
3. **Trace**: Find callers and callees, check calling conventions
4. **Search**: Use `git grep` for pattern searches
5. **Read**: Load headers and related files

## Task 1B: Categorize Changes
For each modified function, create categories:
- Control flow (one per loop, per return/break/continue)
- Function return values/conditions changes
- Resource management (alloc/free/init)
- Locking changes

Label as CHANGE-1, CHANGE-2, etc.

## Task 1C: Output Categories
Print: CHANGE-N: short description, sample code line

## Task 2: Analyze for Regressions
**Reachability gate**: Verify changed code paths are reachable given config dependencies, feature flags, protocol constraints.

**Kconfig check**: If patch modifies Kconfig/defconfig or adds CONFIG_* usage, verify dependencies, select safety, silent disable issues, and symbol existence.

For each change category:
1. **Control flow bugs**: New paths, edge cases, error handling gaps
2. **Locking violations**: Missing locks, lock ordering, deadlocks
3. **Resource leaks**: Missing cleanup, early returns bypassing free
4. **Use-after-free**: Access after free, dangling pointers
5. **Race conditions**: Concurrent access without sync
6. **NULL dereference**: Missing NULL checks before use
7. **API misuse**: Incorrect function contracts
8. **Type safety**: Casts, size mismatches

## Task 3: Deep-Dive Verification
For each potential regression:
- Trace concrete execution path proving bug exists
- Check if existing checks prevent the bug
- Verify bug is reachable in practice
- Consult false-positive guide

## Task 4: Output Results
For each verified regression:
- Regression type
- Evidence (code snippets, call traces)
- Impact (crash, leak, data corruption)
- Affected functions/files

## Analysis Methodology
- Systematic: Don't skip steps
- Evidence-based: Require concrete proof
- Context-aware: Understand surrounding code
- Subsystem-specific: Load relevant guides
