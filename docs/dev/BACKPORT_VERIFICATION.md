# Backport Verification

The kernel review agent now includes **automated backport verification** to detect and analyze differences between downstream patches and their upstream sources.

## Overview

When reviewing downstream Linux kernel commits that are backports from upstream, the agent:

1. **Detects upstream references** via `Git-commit:` tags in commit messages
2. **Fetches upstream commits** from the upstream Linux repository
3. **Compares patches** to identify differences
4. **Flags issues** when backports differ from upstream
5. **Performs deep verification** when differences are detected

## How It Works

### Phase 0: Backport Comparison

Before the standard review begins, the agent:

1. Checks if the commit has an `upstream_commit` reference (from `Git-commit:` tag)
2. Fetches the upstream commit from the configured upstream repository
3. Compares the downstream diff vs upstream diff
4. Detects:
   - **File path changes**: Different files modified
   - **Line number shifts**: Patch applied at different line numbers
   - **Context mismatches**: Surrounding code doesn't match
   - **Missing hunks**: Parts of upstream patch missing downstream
   - **Extra hunks**: Additional changes not in upstream

### Deep Review Trigger

If any of the following are detected, the agent performs **deep backport verification**:

- Context mismatches (patch applied to different code)
- Missing hunks (incomplete backport)
- Extra hunks (additional changes)
- File path changes (wrong files modified)

### Verification Process

When deep review is needed:

1. **Backport verification guide** is loaded into the LLM context
2. **Backport analysis** is appended to the commit information
3. LLM is instructed to verify:
   - Patch applied to functionally equivalent location
   - All critical parts present
   - Logic/semantics match upstream intent
   - No missing error handling or cleanup

## Configuration

### Required Setup

To enable backport verification, configure the upstream Linux repository path:

**Option 1: Command-line**
```bash
kernel_review_agent.py <commit> \
    --upstream-repo /path/to/linux.git \
    --host localhost --port 8080
```

**Option 2: Config file** (`~/.config/kernel-review-agent/config.json`)
```json
{
    "UPSTREAM_REPO": "/path/to/upstream/linux.git"
}
```

### Automatic Detection

The agent automatically:
- Detects `Git-commit:` tags in commit messages
- Fetches upstream commits when available
- Performs backport comparison if upstream repository is configured
- Skips backport verification if upstream repo not available

## Output

### Console Output

When backport differences are detected:

```
=== Phase 0: Backport Verification ===
  Upstream commit: abc123def456
  Backport differences detected: 2 line number shift(s), 1 context mismatch(es)
  → Deep review required - backport differences detected
```

### Review Report

Backport issues are reported with detailed analysis:

```
**Backport Issue**: Patch applied to wrong function with different locking context

**Upstream (v6.1)**:
The patch adds a NULL check in `process_request()` which runs under spinlock.

**Downstream (v5.10)**:
The patch was applied to `handle_request()` which runs in process context.

**Analysis**:
The upstream patch fixes a race condition by adding a NULL check under spinlock.
The downstream backport applies the check to a different function without locking,
so it doesn't fix the race condition.

**Impact**:
The original race condition remains unfixed. Use-after-free vulnerability persists.

**Recommendation**:
Apply the NULL check in the correct location under the same spinlock.
```

## Backport Verification Guide

The agent includes comprehensive guidance for LLMs on how to verify backports:

- **Understanding upstream intent**: What the patch is trying to fix
- **Verifying downstream context**: Is the patch in the right place?
- **Handling context mismatches**: When are differences acceptable?
- **Detecting red flags**: Function name mismatches, missing code, etc.
- **Acceptable differences**: API adaptations, variable renames, etc.

See `prompts/backport-verification.md` for the complete guide.

## Common Backport Issues Detected

### 1. Wrong Function
- Patch applied to different function than upstream
- Different call context or locking

### 2. Missing Critical Code
- Error handling omitted
- Cleanup code not backported
- Only partial fix applied

### 3. Context Mismatch
- Surrounding code differs significantly
- Patch may not work correctly in older codebase

### 4. Incomplete Backport
- Multiple hunks in upstream, only some in downstream
- May leave vulnerability partially fixed

### 5. Logic Inversion
- Condition inverted compared to upstream
- Opposite behavior introduced

## Implementation Details

### Components

1. **BackportVerifier** (`analysis/backport_verifier.py`)
   - Compares downstream vs upstream diffs
   - Parses hunks and detects differences
   - Generates comparison reports

2. **Backport Verification Guide** (`prompts/backport-verification.md`)
   - Instructions for LLM on verifying backports
   - Red flags and acceptable differences
   - Verification process and reporting format

3. **Hybrid Workflow Integration** (`analysis/hybrid_workflow.py`)
   - Phase 0: Backport comparison before standard review
   - Appends backport analysis to commit context
   - Loads verification guide when needed

4. **Upstream Repository Support** (`kernel_review_agent.py`)
   - Configuration for upstream Linux repo
   - MultiRepoExtractor for fetching upstream commits

### Diff Comparison Algorithm

The BackportVerifier:

1. **Parses diffs** into hunks (file, line numbers, added/removed lines, context)
2. **Matches hunks** between downstream and upstream based on content similarity
3. **Compares context** to detect if patch applied to different code
4. **Calculates shifts** in line numbers
5. **Identifies missing/extra hunks**
6. **Scores similarity** to determine if deep review is needed

## Benefits

1. **Prevents regression from bad backports**
   - Catches patches applied to wrong locations
   - Detects incomplete backports
   - Identifies missing critical code

2. **Reduces false negatives**
   - Finds issues that code-only review might miss
   - Context-aware analysis of backport quality

3. **Automated verification**
   - No manual comparison needed
   - Consistent backport quality checks
   - Scales to large volumes of backports

## Limitations

1. **Requires upstream repository access**
   - Must have local clone of upstream Linux kernel
   - Repository must be up-to-date with upstream commits

2. **Depends on Git-commit tags**
   - Commit must reference upstream SHA
   - Tag format: `Git-commit: <sha>` in commit message

3. **Heuristic-based comparison**
   - May miss complex refactoring
   - Relies on LLM understanding of semantics

## Future Enhancements

Potential improvements:

1. **Automatic upstream lookup**
   - Search for upstream commit by subject/patch content
   - Handle commits without Git-commit tags

2. **Backport dependency tracking**
   - Identify required prerequisite commits
   - Detect missing dependencies

3. **API mapping database**
   - Track API changes across kernel versions
   - Suggest correct API adaptations

4. **Backport confidence scoring**
   - Quantify backport quality
   - Flag high-risk backports for manual review
