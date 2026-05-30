"""Error detection for LLM host connection issues."""


def is_fatal_host_error(error: Exception) -> bool:
    """
    Detect errors indicating LLM host is in bad state requiring reset.

    Fatal errors include:
    - Proxy errors: "proxy error", "could not establish connection"
    - Server errors: HTTP 502/503/504, "InternalServerError"
    - Connection errors after retry exhaustion

    Args:
        error: Exception to analyze

    Returns:
        True if error indicates host needs reset, False otherwise
    """
    error_msg = str(error).lower()

    # Check for fatal error patterns
    fatal_patterns = [
        "proxy error",
        "could not establish connection",
        "internalservererror",
        "502",  # Bad Gateway
        "503",  # Service Unavailable
        "504",  # Gateway Timeout
        "connection refused",
        "connection reset",
        "connection aborted",
        "network is unreachable",
    ]

    # Check if any fatal pattern matches
    for pattern in fatal_patterns:
        if pattern in error_msg:
            return True

    # Not a fatal host error
    return False
