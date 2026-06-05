# Evidence Type Handling Fix

## Issue

The kernel review agent crashed with the following error when processing commit `abf5e4cdeb369dcbabcceac78146e7f933d1c179`:

```
AttributeError: 'list' object has no attribute 'split'
```

### Root Cause

The code assumed that the `evidence` field in findings would always be a string. However, the LLM sometimes returns `evidence` as a JSON array (list) instead of a string. When the JSON is parsed, this creates a Python list, which doesn't have a `.split()` method, causing the crash.

### Example Problematic Finding

```json
{
  "type": "use-after-free",
  "message": "potential UAF issue",
  "evidence": ["line1", "line2", "line3"]  // List instead of string!
}
```

## Solution

Added type checking and normalization for the `evidence` field in all places where it's accessed. The fix converts list evidence to a newline-separated string:

```python
evidence = finding.get('evidence', '')
# Handle both string and list types for evidence (LLM might return either)
if isinstance(evidence, list):
    evidence = '\n'.join(str(item) for item in evidence)
```

## Files Modified

1. **analysis/suse_verifier.py** (2 locations)
   - Line ~251: `_finding_exists_in_upstream()` - evidence splitting for code extraction
   - Line ~504: `_determine_if_finding_exists_in_upstream()` - evidence in prompt

2. **analysis/workflow.py** (1 location)
   - Line ~878: `_verify_evidence_physical_existence()` - regex matching on evidence

3. **analysis/hybrid_workflow.py** (3 locations)
   - Line ~198: `_verify_finding_generic()` - evidence in prompt
   - Line ~377: `_verify_lock_findings()` - regex matching for function extraction
   - Line ~502: `_verify_uaf_findings()` - regex matching for variable extraction

4. **output/formatter.py** (1 location)
   - Line ~180: `format_inline()` - evidence formatting in output

## Testing

Created `tests/test_evidence_handling.py` to verify the fix handles:
- String evidence (original expected format)
- List evidence (problematic format from LLM)
- Empty evidence
- Missing evidence field

All tests pass successfully.

## Impact

This fix makes the code more robust to variations in LLM output format. The review agent will no longer crash when the LLM returns evidence as a list, and will properly normalize it to a string for all downstream processing.
