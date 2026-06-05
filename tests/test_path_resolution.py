#!/usr/bin/env python3
"""
Test script to verify path resolution works from any directory.
"""

import os
import sys

# Add the installation directory to path
install_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, install_dir)

import config
from prompt_management import PromptLoader

print("=== Path Resolution Test ===\n")

print(f"Current working directory: {os.getcwd()}")
print(f"Script location: {__file__}")
print(f"Installation directory: {install_dir}")
print()

print(f"config.INSTALL_DIR: {config.INSTALL_DIR}")
print()

# Test PromptLoader
loader = PromptLoader()
print(f"PromptLoader.prompts_dir: {loader.prompts_dir}")
print()

# Verify prompts directory exists
if not os.path.exists(loader.prompts_dir):
    print(f"✗ ERROR: Prompts directory does not exist: {loader.prompts_dir}")
    sys.exit(1)

print(f"✓ Prompts directory exists")

# Try to load a prompt file
try:
    content = loader.load_review_core()
    print(f"✓ Successfully loaded review-core.md ({len(content)} chars)")
except Exception as e:
    print(f"✗ ERROR: Failed to load review-core.md: {e}")
    sys.exit(1)

# Test loading subsystem guide
try:
    rcu_guide = loader.load_subsystem_guide("rcu.md")
    print(f"✓ Successfully loaded rcu.md ({len(rcu_guide)} chars)")
except Exception as e:
    print(f"✗ ERROR: Failed to load rcu.md: {e}")
    sys.exit(1)

print()
print("=== All Tests Passed ===")
print()
print("The agent can find its prompts from any working directory!")
print()
print("Examples:")
print(f"  cd /tmp && python {install_dir}/kernel_review_agent.py HEAD")
print(f"  cd ~/linux && {install_dir}/kernel_review_agent.py HEAD~5..HEAD")
