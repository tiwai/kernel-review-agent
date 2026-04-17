"""Configuration defaults for kernel review agent."""

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
