"""Factory for creating LLM clients based on provider."""

from typing import Optional
import config


def create_llm_client(
    provider: str = "openai",
    verbose: bool = False,
    debug: bool = False,
    dump_prompts: bool = False,
    dump_dir: str = config.DEBUG_DUMP_DIR,
    **kwargs
):
    """
    Create an LLM client based on provider.

    Args:
        provider: Provider name (openai, anthropic, google, ollama)
        verbose: Enable verbose output
        debug: Enable debug output
        dump_prompts: Dump prompts and responses to files
        dump_dir: Directory for prompt/response dumps
        **kwargs: Provider-specific arguments

    Returns:
        LLMClient instance

    Raises:
        ValueError: If provider is unknown
        RuntimeError: If provider library is not installed
    """
    provider = provider.lower()

    if provider == "openai":
        from .openai_client import OpenAIClient
        return OpenAIClient(
            verbose=verbose,
            debug=debug,
            dump_prompts=dump_prompts,
            dump_dir=dump_dir,
            **kwargs
        )

    elif provider == "anthropic":
        from .anthropic_client import AnthropicClient
        return AnthropicClient(
            verbose=verbose,
            debug=debug,
            dump_prompts=dump_prompts,
            dump_dir=dump_dir,
            **kwargs
        )

    elif provider == "google":
        from .google_client import GoogleClient
        return GoogleClient(
            verbose=verbose,
            debug=debug,
            dump_prompts=dump_prompts,
            dump_dir=dump_dir,
            **kwargs
        )

    elif provider == "ollama":
        from .ollama_client import OllamaClient
        return OllamaClient(
            verbose=verbose,
            debug=debug,
            dump_prompts=dump_prompts,
            dump_dir=dump_dir,
            **kwargs
        )

    else:
        raise ValueError(
            f"Unknown provider: {provider}. "
            f"Supported providers: openai, anthropic, google, ollama"
        )


def get_provider_from_args(args) -> str:
    """
    Determine provider from command-line arguments.

    Args:
        args: Parsed command-line arguments

    Returns:
        Provider name (openai, anthropic, google, ollama)
    """
    # Explicit provider takes precedence
    if hasattr(args, 'provider') and args.provider:
        return args.provider

    # Auto-detect from other arguments
    if hasattr(args, 'anthropic_api_key') and args.anthropic_api_key:
        return 'anthropic'

    if hasattr(args, 'google_project') and args.google_project:
        return 'google'

    # Check if using Ollama default port
    if hasattr(args, 'port') and args.port == 11434:
        return 'ollama'

    # Default to OpenAI-compatible
    return 'openai'
