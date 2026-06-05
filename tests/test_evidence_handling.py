#!/usr/bin/env python3
"""
Test that evidence field handling works with both string and list types.
This prevents AttributeError: 'list' object has no attribute 'split'
"""

def normalize_evidence(evidence):
    """Normalize evidence to string, handling both str and list types."""
    if isinstance(evidence, list):
        return '\n'.join(str(item) for item in evidence)
    return evidence


def test_evidence_string():
    """Test that string evidence works."""
    finding = {
        'type': 'test',
        'message': 'test finding',
        'evidence': 'line1\nline2\nline3'
    }

    evidence = finding.get('evidence', '')
    evidence = normalize_evidence(evidence)

    lines = evidence.split('\n')
    assert len(lines) == 3
    assert lines[0] == 'line1'
    print("✓ String evidence works")


def test_evidence_list():
    """Test that list evidence is normalized to string."""
    finding = {
        'type': 'test',
        'message': 'test finding',
        'evidence': ['line1', 'line2', 'line3']
    }

    evidence = finding.get('evidence', '')
    evidence = normalize_evidence(evidence)

    # Should now be a string and splittable
    lines = evidence.split('\n')
    assert len(lines) == 3
    assert lines[0] == 'line1'
    print("✓ List evidence is normalized to string")


def test_evidence_empty():
    """Test that empty evidence works."""
    finding = {
        'type': 'test',
        'message': 'test finding',
        'evidence': ''
    }

    evidence = finding.get('evidence', '')
    evidence = normalize_evidence(evidence)

    assert evidence == ''
    print("✓ Empty evidence works")


def test_evidence_missing():
    """Test that missing evidence field works."""
    finding = {
        'type': 'test',
        'message': 'test finding'
    }

    evidence = finding.get('evidence', '')
    evidence = normalize_evidence(evidence)

    assert evidence == ''
    print("✓ Missing evidence field works")


if __name__ == '__main__':
    test_evidence_string()
    test_evidence_list()
    test_evidence_empty()
    test_evidence_missing()
    print("\nAll tests passed!")
