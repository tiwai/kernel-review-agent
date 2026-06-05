#!/usr/bin/env python3
"""Compare results from different prompt set tests."""

import json
import sys
import os
from pathlib import Path

def load_review(path):
    """Load review.json from a test result directory."""
    review_file = Path(path) / "review.json"
    if not review_file.exists():
        return None

    try:
        with open(review_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {review_file}: {e}", file=sys.stderr)
        return None

def count_findings(review):
    """Count findings in a review."""
    if not review:
        return 0
    return len(review.get('findings', []))

def extract_finding_types(review):
    """Extract finding types from review."""
    if not review:
        return []
    return [f.get('type', 'unknown') for f in review.get('findings', [])]

def compare_reviews(name1, review1, name2, review2):
    """Compare two reviews."""
    print(f"\n{'='*60}")
    print(f"Comparing: {name1} vs {name2}")
    print(f"{'='*60}")

    count1 = count_findings(review1)
    count2 = count_findings(review2)

    print(f"{name1}: {count1} findings")
    print(f"{name2}: {count2} findings")

    types1 = set(extract_finding_types(review1))
    types2 = set(extract_finding_types(review2))

    print(f"\nFinding types in {name1}: {', '.join(sorted(types1)) if types1 else 'none'}")
    print(f"Finding types in {name2}: {', '.join(sorted(types2)) if types2 else 'none'}")

    common = types1 & types2
    only1 = types1 - types2
    only2 = types2 - types1

    if common:
        print(f"\nCommon finding types: {', '.join(sorted(common))}")
    if only1:
        print(f"Only in {name1}: {', '.join(sorted(only1))}")
    if only2:
        print(f"Only in {name2}: {', '.join(sorted(only2))}")

    # Calculate similarity
    if types1 or types2:
        all_types = types1 | types2
        similarity = len(common) / len(all_types) * 100 if all_types else 0
        print(f"\nType overlap: {similarity:.1f}%")

    return count1, count2

def main():
    base_dir = Path("/home/tiwai/tmp/claude-test9/test-results")

    tests = {
        "Small model + small prompts (auto)": base_dir / "test1-small-auto",
        "Small model + default prompts (forced)": base_dir / "test2-small-default",
        "Large model + default prompts (auto)": base_dir / "test3-large-default",
    }

    print("="*60)
    print("Prompt Set Comparison Results")
    print("="*60)

    # Load all reviews
    reviews = {}
    for name, path in tests.items():
        review = load_review(path)
        if review:
            reviews[name] = review
            print(f"✓ Loaded: {name}")
        else:
            print(f"✗ Missing: {name}")

    if not reviews:
        print("\nNo reviews found to compare.")
        return 1

    # Compare small+small vs small+default
    # This tests whether small prompts produce equivalent results
    if "Small model + small prompts (auto)" in reviews and "Small model + default prompts (forced)" in reviews:
        compare_reviews(
            "Small model + small prompts",
            reviews["Small model + small prompts (auto)"],
            "Small model + default prompts",
            reviews["Small model + default prompts (forced)"]
        )

    # Compare small vs large model
    if "Small model + small prompts (auto)" in reviews and "Large model + default prompts (auto)" in reviews:
        compare_reviews(
            "Small model + small prompts",
            reviews["Small model + small prompts (auto)"],
            "Large model + default prompts",
            reviews["Large model + default prompts (auto)"]
        )

    print("\n" + "="*60)
    print("Summary")
    print("="*60)

    for name, review in reviews.items():
        count = count_findings(review)
        types = extract_finding_types(review)
        print(f"\n{name}:")
        print(f"  Findings: {count}")
        if types:
            print(f"  Types: {', '.join(types)}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
