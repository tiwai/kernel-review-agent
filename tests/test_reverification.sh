#!/bin/bash
#
# Test script for re-verification functionality
#

set -e

echo "=========================================="
echo "Re-Verification Test Script"
echo "=========================================="
echo

# Configuration
TEST_REPO="$HOME/tmp/kreviews/base"
TEST_BRANCH="sle12-sp5-gpt-oss-20b"
EXAMPLE_JSON="$TEST_REPO/e8/e8f48bf4d4d5e3bdccedc3de0dc9cc4a36955b75/review-pre-verification.json"

# Check if test repository exists
if [ ! -d "$TEST_REPO" ]; then
    echo "Error: Test repository not found at $TEST_REPO"
    exit 1
fi

# Check if example JSON exists
if [ ! -f "$EXAMPLE_JSON" ]; then
    echo "Error: Example pre-verification JSON not found"
    echo "Expected: $EXAMPLE_JSON"
    exit 1
fi

echo "Test repository: $TEST_REPO"
echo "Example JSON: $EXAMPLE_JSON"
echo

# Show example JSON structure
echo "=========================================="
echo "Example Pre-Verification JSON Structure:"
echo "=========================================="
python3 -c "
import json
import sys

with open('$EXAMPLE_JSON', 'r') as f:
    data = json.load(f)

# Show available fields
print('Available fields:')
for key in sorted(data.keys()):
    if isinstance(data[key], list):
        print(f'  {key}: list with {len(data[key])} items')
    elif isinstance(data[key], dict):
        print(f'  {key}: dict with {len(data[key])} keys')
    elif isinstance(data[key], str) and len(data[key]) > 100:
        print(f'  {key}: string ({len(data[key])} chars)')
    else:
        print(f'  {key}: {type(data[key]).__name__}')

print()
print('Missing fields needed for full re-verification:')
needed = ['diff', 'message', 'categories', 'subsystems', 'code_context']
missing = [f for f in needed if f not in data]
if missing:
    for f in missing:
        print(f'  ❌ {f}')
else:
    print('  ✓ All fields present')

print()
print('Re-verification status:')
has_diff = 'diff' in data
has_findings = 'findings' in data and len(data['findings']) > 0
if has_diff and has_findings:
    print('  ✓ Can re-verify (has diff and findings)')
    print(f'  Findings to verify: {len(data[\"findings\"])}')
elif not has_diff:
    print('  ❌ Cannot re-verify - missing diff field')
elif not has_findings:
    print('  ⚠ Can re-verify but no findings to process')
"

echo
echo "=========================================="
echo "Extended Schema Example:"
echo "=========================================="
echo "New review-pre-verification.json files will include:"
echo "  - diff: Full commit diff (required for verification)"
echo "  - message: Full commit message (context for verification)"
echo "  - categories: Change categories from Task 1"
echo "  - subsystems: Matched subsystems"
echo "  - code_context: Full source code context"
echo
echo "To generate new files with extended schema:"
echo "  ./kernel_review_agent.py <commit> --output-dir ./output/"
echo
echo "To re-verify existing files:"
echo "  ./kernel_review_agent.py --reverify ./output/"
echo

# Check for actual reverify capability
if [ "$1" == "--demo" ]; then
    echo "=========================================="
    echo "Running Re-Verification Demo"
    echo "=========================================="
    echo
    echo "This would run:"
    echo "  ./kernel_review_agent.py --reverify \"$EXAMPLE_JSON\" --verbose --debug"
    echo
    echo "Note: Requires LLM service running and proper configuration"
    echo "Add your LLM parameters (--host, --port, --model, etc.)"
fi

echo
echo "Test complete!"
