"""Configuration defaults for kernel review agent."""

import os
import sys


def find_prompts_directory():
    """
    Find the prompts directory in various installation locations.

    Checks in order:
    1. Relative to this config.py file (development/local install)
    2. System-wide installation (/usr/share/kernel-review-agent/prompts)
    3. User installation (~/.local/share/kernel-review-agent/prompts)
    4. Python package data directory

    Returns:
        str: Path to prompts directory
    """
    # Method 1: Relative to config.py (development, local install)
    config_dir = os.path.dirname(os.path.abspath(__file__))
    local_prompts = os.path.join(config_dir, 'prompts')
    if os.path.isdir(local_prompts):
        return local_prompts

    # Method 2: System-wide installation
    system_prompts = '/usr/share/kernel-review-agent/prompts'
    if os.path.isdir(system_prompts):
        return system_prompts

    # Method 3: User installation
    user_prompts = os.path.expanduser('~/.local/share/kernel-review-agent/prompts')
    if os.path.isdir(user_prompts):
        return user_prompts

    # Method 4: Python package data (when installed via pip)
    try:
        import pkg_resources
        pkg_prompts = pkg_resources.resource_filename('kernel_review_agent', 'prompts')
        if os.path.isdir(pkg_prompts):
            return pkg_prompts
    except (ImportError, Exception):
        pass

    # Fallback: Return local path even if it doesn't exist
    # (will be caught by validation in main script)
    return local_prompts


# Installation directory (where this config.py is located)
INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))

# Default prompts directory
# Can be overridden with --prompts-dir command-line option
DEFAULT_PROMPTS_DIR = find_prompts_directory()

# LLM API defaults
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8080
DEFAULT_API_KEY = "dummy"

# Output defaults
DEFAULT_OUTPUT_DIR = "."

# Git defaults
DEFAULT_UPSTREAM_BRANCH = None

# LLM parameters
DEFAULT_MAX_TOKENS = 16000  # Increased for complex kernel reviews
DEFAULT_MODEL = "gpt-4"
DEFAULT_TEMPERATURE = 0.1

# Task-specific token limits
CATEGORIZE_MAX_TOKENS = 8000    # Task 1: Categorize changes
ANALYZE_MAX_TOKENS = 16000       # Task 2: Analyze for regressions
VERIFY_MAX_TOKENS = 16000        # Task 3: Verify findings

# Response truncation detection
TRUNCATION_WARNING_THRESHOLD = 0.95  # Warn if response uses >95% of max_tokens

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # seconds
RETRY_BACKOFF = 2.0  # exponential backoff multiplier

# Timeout configuration
LLM_TIMEOUT = 300  # seconds (5 minutes) - timeout for LLM API calls
CONNECT_TIMEOUT = 10  # seconds - timeout for initial connection

# Debug options
DEBUG_DUMP_DIR = "debug_dumps"  # Directory for prompt/response dumps
