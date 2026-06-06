#!/usr/bin/env python3
"""Test JSON repair functionality for common LLM formatting issues."""

import json
from analysis.workflow import ReviewWorkflow
from llm_integration import OpenAIClient
from prompt_management import PromptLoader, SubsystemMatcher


def test_missing_comma_after_bracket():
    """Test repair of missing comma after closing bracket."""
    # Mock objects needed for ReviewWorkflow
    llm_client = None  # We won't use it for this test
    prompt_loader = None
    subsystem_matcher = None

    # Create workflow instance (we only need the repair method)
    workflow = ReviewWorkflow(
        llm_client=llm_client,
        prompt_loader=prompt_loader,
        subsystem_matcher=subsystem_matcher,
        verbose=True
    )

    # Test case 1: Missing comma after closing bracket (from user's error)
    malformed_json = '''[
  {
    "category": "CHANGE-1",
    "type": "race-condition",
    "evidence": [
      "spin_unlock_irqrestore(&hif_dev->tx.tx_lock, flags);"
    ]
    "severity": "high"
  }
]'''

    print("Test 1: Missing comma after closing bracket")
    print("Original (malformed):")
    print(malformed_json)
    print()

    repaired = workflow._attempt_json_repair(malformed_json)
    print("Repaired:")
    print(repaired)
    print()

    try:
        parsed = json.loads(repaired)
        print(f"✓ Successfully parsed! Found {len(parsed)} items")
        print(json.dumps(parsed, indent=2))
    except json.JSONDecodeError as e:
        print(f"✗ Failed to parse: {e}")

    print("\n" + "="*60 + "\n")

    # Test case 2: Missing comma between array elements
    malformed_json2 = '''[
  {
    "id": "CHANGE-1",
    "type": "control-flow"
  }
  {
    "id": "CHANGE-2",
    "type": "resource-management"
  }
]'''

    print("Test 2: Missing comma between array elements")
    print("Original (malformed):")
    print(malformed_json2)
    print()

    repaired2 = workflow._attempt_json_repair(malformed_json2)
    print("Repaired:")
    print(repaired2)
    print()

    try:
        parsed2 = json.loads(repaired2)
        print(f"✓ Successfully parsed! Found {len(parsed2)} items")
        print(json.dumps(parsed2, indent=2))
    except json.JSONDecodeError as e:
        print(f"✗ Failed to parse: {e}")

    print("\n" + "="*60 + "\n")

    # Test case 3: Trailing comma before closing bracket
    malformed_json3 = '''[
  {
    "id": "CHANGE-1",
    "type": "control-flow",
  }
]'''

    print("Test 3: Trailing comma before closing bracket")
    print("Original (malformed):")
    print(malformed_json3)
    print()

    repaired3 = workflow._attempt_json_repair(malformed_json3)
    print("Repaired:")
    print(repaired3)
    print()

    try:
        parsed3 = json.loads(repaired3)
        print(f"✓ Successfully parsed! Found {len(parsed3)} items")
        print(json.dumps(parsed3, indent=2))
    except json.JSONDecodeError as e:
        print(f"✗ Failed to parse: {e}")


if __name__ == "__main__":
    test_missing_comma_after_bracket()
