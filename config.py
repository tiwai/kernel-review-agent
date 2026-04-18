"""Configuration management for kernel review agent."""

import os
import sys
import json


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


def load_config_file(config_path):
    """
    Load configuration from JSON file.

    Args:
        config_path: Path to JSON config file

    Returns:
        dict: Configuration dictionary, or {} if file doesn't exist or is invalid
    """
    if not os.path.isfile(config_path):
        return {}

    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
            return config if isinstance(config, dict) else {}
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Failed to load config file {config_path}: {e}", file=sys.stderr)
        return {}


def load_configuration():
    """
    Load configuration from system and user config files.

    Configuration is loaded in this order (later overrides earlier):
    1. Hardcoded defaults (in this file)
    2. System-wide config: /etc/kernel-review-agent/config.json
    3. User config: ~/.config/kernel-review-agent/config.json

    Returns:
        dict: Merged configuration
    """
    # Start with hardcoded defaults
    config = {
        # LLM API defaults
        'DEFAULT_HOST': 'localhost',
        'DEFAULT_PORT': 8080,
        'DEFAULT_API_KEY': 'dummy',
        'DEFAULT_MODEL': 'gpt-4',

        # LLM parameters
        'DEFAULT_MAX_TOKENS': 16000,
        'DEFAULT_TEMPERATURE': 0.1,

        # Task-specific token limits
        'CATEGORIZE_MAX_TOKENS': 8000,
        'ANALYZE_MAX_TOKENS': 16000,
        'VERIFY_MAX_TOKENS': 16000,

        # Response truncation detection
        'TRUNCATION_WARNING_THRESHOLD': 0.95,

        # Retry configuration
        'MAX_RETRIES': 3,
        'RETRY_DELAY': 1.0,
        'RETRY_BACKOFF': 2.0,

        # Timeout configuration
        'LLM_TIMEOUT': 300,
        'CONNECT_TIMEOUT': 10,

        # Output defaults
        'DEFAULT_OUTPUT_DIR': '.',

        # Debug options
        'DEBUG_DUMP_DIR': 'debug_dumps',

        # SUSE kernel-source repository paths
        'SUSE_KERNEL_SOURCE_REPO': None,  # Path to SUSE kernel-source git repo
        'UPSTREAM_LINUX_REPO': None,      # Path to upstream Linux kernel repo (optional)
    }

    # Load system-wide config
    system_config_paths = [
        '/etc/kernel-review-agent/config.json',
        '/usr/local/etc/kernel-review-agent/config.json',
    ]

    for system_path in system_config_paths:
        system_config = load_config_file(system_path)
        if system_config:
            config.update(system_config)
            break  # Use first found system config

    # Load user config (overrides system config)
    user_config_path = os.path.expanduser('~/.config/kernel-review-agent/config.json')
    user_config = load_config_file(user_config_path)
    if user_config:
        config.update(user_config)

    return config


# Load configuration from files
_config = load_configuration()

# Installation directory (where this config.py is located)
INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))

# Default prompts directory
# Can be overridden with --prompts-dir command-line option
DEFAULT_PROMPTS_DIR = find_prompts_directory()

# Export configuration values
DEFAULT_HOST = _config['DEFAULT_HOST']
DEFAULT_PORT = _config['DEFAULT_PORT']
DEFAULT_API_KEY = _config['DEFAULT_API_KEY']
DEFAULT_MODEL = _config['DEFAULT_MODEL']
DEFAULT_MAX_TOKENS = _config['DEFAULT_MAX_TOKENS']
DEFAULT_TEMPERATURE = _config['DEFAULT_TEMPERATURE']
CATEGORIZE_MAX_TOKENS = _config['CATEGORIZE_MAX_TOKENS']
ANALYZE_MAX_TOKENS = _config['ANALYZE_MAX_TOKENS']
VERIFY_MAX_TOKENS = _config['VERIFY_MAX_TOKENS']
TRUNCATION_WARNING_THRESHOLD = _config['TRUNCATION_WARNING_THRESHOLD']
MAX_RETRIES = _config['MAX_RETRIES']
RETRY_DELAY = _config['RETRY_DELAY']
RETRY_BACKOFF = _config['RETRY_BACKOFF']
LLM_TIMEOUT = _config['LLM_TIMEOUT']
CONNECT_TIMEOUT = _config['CONNECT_TIMEOUT']
DEFAULT_OUTPUT_DIR = _config['DEFAULT_OUTPUT_DIR']
DEBUG_DUMP_DIR = _config['DEBUG_DUMP_DIR']
SUSE_KERNEL_SOURCE_REPO = _config['SUSE_KERNEL_SOURCE_REPO']
UPSTREAM_LINUX_REPO = _config['UPSTREAM_LINUX_REPO']
