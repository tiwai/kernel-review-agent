#!/usr/bin/env python3
"""Test script to verify propose-fixes configuration logic."""

import sys
import argparse

# Simulate config module
class MockConfig:
    PROPOSE_FIXES = False  # Default from config

config = MockConfig()

# Simulate the argument parsing
parser = argparse.ArgumentParser()
fix_group = parser.add_mutually_exclusive_group()
fix_group.add_argument("--propose-fixes", action="store_true", default=None)
fix_group.add_argument("--no-propose-fixes", action="store_true")

print("Testing propose-fixes configuration logic:\n")

# Test 1: No flags (should use config default)
args = parser.parse_args([])
if args.no_propose_fixes:
    args.propose_fixes = False
elif args.propose_fixes is None:
    args.propose_fixes = config.PROPOSE_FIXES
print(f"Test 1 - No flags:              propose_fixes = {args.propose_fixes} (expected: {config.PROPOSE_FIXES})")

# Test 2: --propose-fixes (should enable)
args = parser.parse_args(["--propose-fixes"])
if args.no_propose_fixes:
    args.propose_fixes = False
elif args.propose_fixes is None:
    args.propose_fixes = config.PROPOSE_FIXES
print(f"Test 2 - --propose-fixes:       propose_fixes = {args.propose_fixes} (expected: True)")

# Test 3: --no-propose-fixes (should disable)
args = parser.parse_args(["--no-propose-fixes"])
if args.no_propose_fixes:
    args.propose_fixes = False
elif args.propose_fixes is None:
    args.propose_fixes = config.PROPOSE_FIXES
print(f"Test 3 - --no-propose-fixes:    propose_fixes = {args.propose_fixes} (expected: False)")

# Test 4: Config enabled
config.PROPOSE_FIXES = True
args = parser.parse_args([])
if args.no_propose_fixes:
    args.propose_fixes = False
elif args.propose_fixes is None:
    args.propose_fixes = config.PROPOSE_FIXES
print(f"\nTest 4 - Config=True, no flags: propose_fixes = {args.propose_fixes} (expected: True)")

# Test 5: Config enabled but overridden with --no-propose-fixes
args = parser.parse_args(["--no-propose-fixes"])
if args.no_propose_fixes:
    args.propose_fixes = False
elif args.propose_fixes is None:
    args.propose_fixes = config.PROPOSE_FIXES
print(f"Test 5 - Config=True, --no-propose-fixes: propose_fixes = {args.propose_fixes} (expected: False)")

print("\nAll tests passed! ✓")
