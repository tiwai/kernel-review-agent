# Debug Guide

This guide explains how to use the debugging features of the Linux Kernel Commit Review Agent.

## Overview

Two debug options are available:

1. **`--debug`**: Verbose debug output showing detailed information at each step
2. **`--dump-prompts`**: Save all LLM prompts and responses to files for analysis

## Debug Output (`--debug`)

### What It Shows

The `--debug` flag provides detailed information throughout the review process:

#### Configuration
```
[DEBUG] Configuration:
[DEBUG]   LLM: localhost:8080
[DEBUG]   Model: gpt-4
[DEBUG]   Verbose: True
[DEBUG]   Debug: True
[DEBUG]   Dump prompts: True
[DEBUG]   Dump directory: debug_dumps
[DEBUG]   Output directory: .
[DEBUG]   Upstream branch: upstream
```

#### Task 0: Context Management
```
[DEBUG] Task 0: Context management
[DEBUG] Commit SHA: abc123def456789
[DEBUG] Files changed: 2
[DEBUG] Diff size: 1234 chars
[DEBUG] Context gathered:
[DEBUG]   - Changed functions: ['shrink_page_list', 'reclaim_pages']
[DEBUG]   - Files: ['mm/vmscan.c', 'mm/internal.h']
[DEBUG] Subsystems matched: ['mm-reclaim.md', 'mm-vma.md']
```

#### Task 1: Categorization
```
[DEBUG] Task 1: Categorizing changes
[DEBUG] Calling LLM for categorization...
[DEBUG] LLM call #1: model=gpt-4, max_tokens=4000, temp=0.1
[DEBUG] System prompt length: 15234 chars
[DEBUG] User prompt length: 2456 chars
[DEBUG] Response length: 567 chars
[DEBUG] Token usage: CompletionUsage(completion_tokens=142, prompt_tokens=3891, total_tokens=4033)
[DEBUG] Categories:
[DEBUG]   - CHANGE-1: resource-management - Added folio allocation in e...
[DEBUG]   - CHANGE-2: control-flow - Modified error handling path for ...
```

#### Task 2: Regression Analysis
```
[DEBUG] Task 2: Analyzing for regressions
[DEBUG] Loading subsystem guides: ['mm-reclaim.md', 'mm-vma.md']
[DEBUG] Calling LLM for regression analysis...
[DEBUG] LLM call #2: model=gpt-4, max_tokens=8000, temp=0.1
[DEBUG] System prompt length: 28456 chars
[DEBUG] User prompt length: 3123 chars
[DEBUG] Response length: 1234 chars
[DEBUG] Token usage: CompletionUsage(completion_tokens=245, prompt_tokens=7891, total_tokens=8136)
[DEBUG] Findings:
[DEBUG]   1. memory-leak: Can this leak the folio? The allocation is no...
[DEBUG]   2. null-deref: Missing null check after allocation before use...
```

#### Task 3: Verification
```
[DEBUG] Task 3: Verifying findings
[DEBUG] Applying false-positive checks to 2 findings...
[DEBUG] LLM call #3: model=gpt-4, max_tokens=8000, temp=0.1
[DEBUG] System prompt length: 32123 chars
[DEBUG] User prompt length: 2789 chars
[DEBUG] Response length: 891 chars
[DEBUG] Verification complete: 1 verified, 1 discarded as false positives
```

#### Task 4: Summary
```
[DEBUG] Task 4: Generating summary
[DEBUG] Summary: This commit has a potential memory-leak that should be reviewed.
```

### Usage

```bash
# Basic debug output
python kernel_review_agent.py HEAD --debug

# Combine with verbose for maximum information
python kernel_review_agent.py HEAD --verbose --debug
```

### What To Look For

**Performance Issues:**
- Check prompt/response sizes - very large prompts may hit token limits
- Check token usage - helps estimate costs and identify inefficiencies

**Analysis Issues:**
- Check which subsystems were matched - ensure relevant guides are loaded
- Check categories found - verify changes are properly categorized
- Check findings count - compare initial findings vs. verified findings

**LLM Issues:**
- Check response lengths - very short responses may indicate parsing errors
- Monitor token usage across calls - identify which phase uses most tokens

## Prompt Dumping (`--dump-prompts`)

### What It Creates

The `--dump-prompts` flag saves each LLM interaction to numbered files:

```
debug_dumps/
├── 001_prompt.txt      # First LLM call (categorization)
├── 001_response.txt
├── 002_prompt.txt      # Second LLM call (regression analysis)
├── 002_response.txt
├── 003_prompt.txt      # Third LLM call (verification)
└── 003_response.txt
```

### Prompt File Format

```
=== LLM Call #1 ===
Model: gpt-4
Max Tokens: 4000
Temperature: 0.1

================================================================================

--- SYSTEM MESSAGE ---

# ADAPTATION FOR CODE-ONLY REVIEW

This review focuses ONLY on code changes. Do NOT evaluate:
- Commit message quality or formatting
- Fixes tags or commit tags
...

================================================================================

--- USER MESSAGE ---

Analyze this commit and categorize the changes.

For each distinct change, create a category with:
- id: CHANGE-1, CHANGE-2, etc.
...

Commit: mm: fix use-after-free in page reclaim

Diff:
diff --git a/mm/vmscan.c b/mm/vmscan.c
...
```

### Response File Format

```
=== LLM Response #1 ===

[
  {
    "id": "CHANGE-1",
    "type": "resource-management",
    "description": "Added folio allocation in error path",
    "location": "mm/vmscan.c:shrink_page_list"
  },
  {
    "id": "CHANGE-2",
    "type": "control-flow",
    "description": "Modified error handling path for reclaim failure",
    "location": "mm/vmscan.c:reclaim_pages"
  }
]
```

### Usage

```bash
# Dump to default directory (debug_dumps/)
python kernel_review_agent.py HEAD --dump-prompts

# Dump to custom directory
python kernel_review_agent.py HEAD --dump-prompts --dump-dir ./analysis/

# Combine all debug features
python kernel_review_agent.py HEAD --verbose --debug --dump-prompts
```

### Use Cases

**Prompt Engineering:**
1. Review the system prompts to understand what instructions are sent
2. Analyze which subsystem guides are loaded and how they affect prompts
3. Measure prompt sizes to optimize for token limits
4. Test different prompt modifications offline

**Debugging LLM Issues:**
1. Check if LLM is returning valid JSON
2. Identify why certain regressions aren't detected
3. Understand why findings are marked as false positives
4. Analyze prompt/response patterns for specific commit types

**Analysis & Optimization:**
1. Calculate actual token usage for cost estimation
2. Identify redundant information in prompts
3. Test prompt modifications before changing code
4. Compare prompts across different subsystems

**Training & Learning:**
1. Understand how the 5-task protocol works in practice
2. See concrete examples of subsystem-specific patterns
3. Learn kernel review techniques by studying the prompts
4. Understand false-positive verification logic

## Example Workflows

### Basic Debugging Session

```bash
# Review a commit with debug output
cd /path/to/linux-kernel
python /path/to/kernel_review_agent.py HEAD --verbose --debug

# Check what's happening at each step
# Look for:
# - Which subsystems matched
# - How many categories were found
# - How many findings before/after verification
# - Token usage per LLM call
```

### Prompt Analysis Session

```bash
# Review a commit and dump prompts
python kernel_review_agent.py abc123 --dump-prompts --dump-dir ./analysis/

# Analyze the dumps
cat analysis/001_prompt.txt    # Categorization prompt
cat analysis/002_prompt.txt    # Regression analysis prompt
cat analysis/003_prompt.txt    # Verification prompt

# Check prompt sizes
wc -c analysis/*_prompt.txt

# Check which subsystem guides were included
grep "# SUBSYSTEM GUIDE:" analysis/002_prompt.txt
```

### Performance Investigation

```bash
# Review with all debug features
python kernel_review_agent.py HEAD~10..HEAD --verbose --debug --dump-prompts

# Analyze token usage
grep "Token usage:" kernel_review_agent.log

# Check prompt sizes
ls -lh debug_dumps/*_prompt.txt

# Identify bottlenecks
# - Large prompts → reduce subsystem guide content
# - Many retries → check LLM server stability
# - Long response times → check network/server load
```

### False Positive Analysis

```bash
# Review a commit that has false positives
python kernel_review_agent.py abc123 --dump-prompts

# Compare findings before/after verification
# 1. Check 002_response.txt for initial findings
# 2. Check 003_response.txt for verified findings
# 3. Understand why certain findings were discarded
# 4. Improve false-positive-guide.md if needed
```

## Tips

**Performance:**
- Use `--debug` alone for quick checks (no file I/O overhead)
- Use `--dump-prompts` when you need to analyze prompts offline
- Set `--dump-dir` to different directories for different commits

**Troubleshooting:**
- If no categories found → check 001_response.txt for LLM output
- If no findings → check 002_response.txt and subsystems matched
- If all findings discarded → check 003_response.txt for reasoning
- If JSON parse errors → check response files for malformed JSON

**Optimization:**
- Review dump files to identify unnecessary content in prompts
- Measure token usage to estimate costs for large-scale reviews
- Compare prompts across commits to identify patterns
- Use findings to fine-tune subsystem matching triggers

## Cleaning Up

Debug dumps can accumulate quickly:

```bash
# Remove all debug dumps
rm -rf debug_dumps/

# Remove specific review's dumps
rm -f debug_dumps/00[1-3]_*.txt

# Archive dumps before removing
tar -czf debug_archive.tar.gz debug_dumps/
rm -rf debug_dumps/
```

The `debug_dumps/` directory is excluded from git via `.gitignore`.
