# JSON Repair Enhancement

## Problem

LLMs sometimes return malformed JSON with missing commas or other formatting issues. The original code would fail completely when encountering these errors, even though the JSON could potentially be repaired.

Example error from logs:
```
Failed to parse regression analysis JSON: Expecting ',' delimiter: line 7 column 1316 (char 1640)
Context around error position 1640: ...qrestore(&hif_dev->tx.tx_lock, flags);\n  ]\n    "severity": "high"
```

## Solution

Added a tolerant JSON parser that attempts to repair common formatting issues before giving up on parsing.

### Changes Made

1. **New Method**: `_attempt_json_repair()` in `analysis/workflow.py`
   - Fixes missing commas after closing brackets/braces
   - Fixes missing commas between object elements
   - Removes trailing commas before closing brackets
   - Handles other common LLM JSON formatting issues

2. **Enhanced Error Handling** in both:
   - `_analyze_regressions()` - for regression analysis JSON
   - `_categorize_changes()` - for categorization JSON

3. **Repair Flow**:
   - First attempt: Parse JSON as-is
   - On failure: Check if truncated (don't repair if truncated)
   - If not truncated: Attempt repair and parse again
   - Report success/failure with appropriate logging

### Supported Repair Cases

✅ Missing comma after closing bracket before quote: `]  "key"` → `], "key"`
✅ Missing comma between objects: `}  {` → `}, {`
✅ Missing comma after string before quote: `"value"  "key"` → `"value", "key"`
✅ Trailing commas: `"key": "value",  }` → `"key": "value"  }`
✅ Missing comma before array/object: `null  {` → `null, {`

### Testing

Run `python3 test_json_repair.py` to verify all repair scenarios work correctly.

### Example Output

When repair succeeds:
```
[ERROR] Failed to parse regression analysis JSON: Expecting ',' delimiter...
[WARNING] Attempting to repair malformed JSON...
[SUCCESS] JSON repair successful, parsed 2 findings
```

When repair fails:
```
[ERROR] Failed to parse regression analysis JSON: Expecting ',' delimiter...
[WARNING] Attempting to repair malformed JSON...
[ERROR] JSON repair failed: Unexpected end of JSON input
```

## Benefits

- More tolerant of LLM formatting issues
- Allows processing to continue even with minor JSON errors
- Provides clear logging of repair attempts
- No change to behavior when JSON is already valid
- Fails gracefully if repair is not possible
