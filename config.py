"""Configuration defaults for kernel review agent."""

import os

# Installation directory (where this config.py is located)
INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))

# Default prompts directory
# Can be overridden with --prompts-dir command-line option
DEFAULT_PROMPTS_DIR = os.path.join(INSTALL_DIR, 'prompts')

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
