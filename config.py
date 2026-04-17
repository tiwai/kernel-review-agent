"""Configuration defaults for kernel review agent."""

import os

# Installation directory (where this config.py is located)
# Can be overridden with KREVIEW_HOME environment variable
INSTALL_DIR = os.environ.get('KREVIEW_HOME', os.path.dirname(os.path.abspath(__file__)))

# LLM API defaults
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8080
DEFAULT_API_KEY = "dummy"

# Output defaults
DEFAULT_OUTPUT_DIR = "."

# Git defaults
DEFAULT_UPSTREAM_BRANCH = None

# LLM parameters
DEFAULT_MAX_TOKENS = 8000
DEFAULT_MODEL = "gpt-4"
DEFAULT_TEMPERATURE = 0.1

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # seconds
RETRY_BACKOFF = 2.0  # exponential backoff multiplier

# Debug options
DEBUG_DUMP_DIR = "debug_dumps"  # Directory for prompt/response dumps
