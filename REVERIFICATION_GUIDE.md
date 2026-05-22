# Re-Verification Guide

## Overview

The kernel review agent now supports re-verification of previously identified findings. This allows you to:
- Re-run the verification step (Task 3) with updated models or parameters
- Test different verification strategies without re-analyzing commits
- Evaluate findings that were identified but not yet verified

## Extended Pre-Verification JSON Format

The `review-pre-verification.json` file now includes all information needed for complete re-verification:

### Required Fields for Re-Verification

```json
{
  "sha": "commit-sha",
  "author": "Author Name <email@domain.com>",
  "subject": "Commit subject line",
  "message": "Full commit message including subject",
  "diff": "Full unified diff of the commit",
  "files": ["path/to/file1.c", "path/to/file2.h"],
  "potential_issues_found": 2,
  "findings": [
    {
      "category": "CHANGE-1",
      "type": "issue-type",
      "message": "Description of the issue",
      "evidence": "Code snippets supporting the finding",
      "severity": "low|medium|high",
      "upstream_status": "present_in_upstream|downstream_only"
    }
  ],
  "verification_status": "pre_verification"
}
```

### Optional Fields (for Enhanced Re-Verification)

```json
{
  "categories": [
    {
      "id": "CHANGE-1",
      "type": "resource-management",
      "description": "Description of the change",
      "location": "file.c:function_name"
    }
  ],
  "subsystems": ["drivers/net", "mm"],
  "code_context": "Full source code context including function definitions and callers",
  "suse_upstream_verification": {
    "suse_commit_sha": "suse-commit-sha",
    "upstream_commit_sha": "upstream-commit-sha",
    "upstream_subject": "Upstream commit subject",
    "findings_in_upstream": 1,
    "findings_downstream_only": 1
  },
  "upstream_commit": "upstream-commit-sha-if-backport"
}
```

## Usage

### Re-verify a Single File

```bash
./kernel_review_agent.py --reverify /path/to/review-pre-verification.json \
    --host localhost --port 11434
```

### Re-verify All Files in a Directory Tree

```bash
./kernel_review_agent.py --reverify ~/tmp/kreviews/base \
    --host localhost --port 11434 --verbose
```

This will find all `review-pre-verification.json` files in the directory tree and re-verify each one.

### Re-verification Output

Re-verification produces the same outputs as normal review:
- `review-inline.txt` - Human-readable report (overwrites existing)
- `review-metadata.json` - Machine-readable metadata (overwrites existing)

The `review-pre-verification.json` file is **not modified** during re-verification.

## Workflow Comparison

### Normal Review Workflow
1. Task 0: Gather context (code context, changed functions)
2. Task 1: Categorize changes
3. Task 2: Analyze for regressions → **Save to review-pre-verification.json**
4. Task 2.5: SUSE upstream verification (if applicable)
5. Task 3: Verify findings (false-positive elimination)
6. Task 4: Generate summary
7. Task 5: Propose fixes (optional)

### Re-Verification Workflow
1. Load from `review-pre-verification.json`
2. Reconstruct commit and context from saved data
3. **Task 3: Verify findings** (same as normal workflow)
4. Generate summary
5. Save results to `review-inline.txt` and `review-metadata.json`

## Benefits

1. **Faster iteration**: Skip expensive Tasks 0-2, focus only on verification
2. **Model comparison**: Re-verify same findings with different models
3. **Parameter tuning**: Test verification with different prompts or settings
4. **Batch processing**: Re-verify many commits efficiently

## Backward Compatibility

Old `review-pre-verification.json` files (missing new fields) can still be re-verified, but:
- Without `diff`: Re-verification will fail (diff is required)
- Without `message`: Subject will be used instead
- Without `code_context`: Verification will use only the diff
- Without `categories`/`subsystems`: Less context for verification

For best results, re-run the full review to generate new pre-verification files with all fields.

## Example: Comparing Verification Strategies

```bash
# First, run initial review (saves pre-verification data)
./kernel_review_agent.py HEAD --output-dir ./reviews/

# Re-verify with different model
./kernel_review_agent.py --reverify ./reviews/ \
    --model different-model --output-dir ./reviews-model2/

# Re-verify with verification disabled (to see all findings)
./kernel_review_agent.py --reverify ./reviews/ \
    --skip-verification --output-dir ./reviews-unverified/
```

## Implementation Details

### New Fields in ReviewResult

The `ReviewResult` dataclass now includes:
- `pre_verification_findings`: Findings before Task 3 verification
- `categories`: Change categories from Task 1
- `code_context_formatted`: Full code context for re-verification

### New Method: `reverify_from_json()`

Both `ReviewWorkflow` and `HybridReviewWorkflow` now support:

```python
result = workflow.reverify_from_json('path/to/review-pre-verification.json')
```

This method:
1. Loads and validates the JSON file
2. Reconstructs the commit object
3. Reconstructs the context
4. Runs Task 3 (verification) using the same logic as normal reviews
5. Returns a `ReviewResult` with verified findings
