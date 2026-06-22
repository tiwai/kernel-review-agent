"""Resilient LLM client wrapper with automatic host reset on fatal errors."""

import sys
from typing import List, Dict, Optional
from .base_client import LLMClient
from .error_detector import is_fatal_host_error
import config


class ResilientLLMClient(LLMClient):
    """
    LLM client wrapper that adds automatic host reset on fatal connection errors.

    This wrapper delegates all operations to a wrapped LLM client but intercepts
    fatal host errors (proxy errors, connection failures, etc.). When detected,
    it attempts to reset the host by:
    1. Creating a temporary client with a lightweight fallback model
    2. Sending a minimal test query to "wake up" the host
    3. Retrying the original operation with the original client

    This is a transparent wrapper - callers don't need to know it's being used.
    """

    # Default fallback models by provider
    DEFAULT_FALLBACK_MODELS = {
        'openai': 'gpt-3.5-turbo',
        'anthropic': 'claude-3-haiku-20240307',
        'anthropic-vertex': 'claude-3-haiku@20240307',
        'google': 'gemini-1.5-flash',
        'ollama': 'llama2',
    }

    def __init__(
        self,
        wrapped_client: LLMClient,
        enable_reset: bool = True,
        fallback_model: Optional[str] = None,
        max_reset_attempts: int = 0,
        provider: str = 'openai',
        verbose: bool = False,
        debug: bool = False,
        **factory_kwargs
    ):
        """
        Initialize resilient LLM client wrapper.

        Args:
            wrapped_client: The actual LLM client to wrap
            enable_reset: Enable automatic reset on fatal errors
            fallback_model: Model to use for reset test query (None = use provider default)
            max_reset_attempts: Maximum reset attempts per operation (0 = unlimited)
            provider: Provider name (for selecting default fallback model)
            verbose: Enable verbose output
            debug: Enable debug output
            **factory_kwargs: Additional kwargs for creating clients (host, port, api_key, etc.)
        """
        # Initialize base class with wrapped client's model
        super().__init__(
            model=wrapped_client.model,
            verbose=verbose,
            debug=debug,
            dump_prompts=wrapped_client.dump_prompts,
            dump_dir=wrapped_client.dump_dir
        )

        self.client = wrapped_client
        self.enable_reset = enable_reset
        self.max_reset_attempts = max_reset_attempts
        self.provider = provider
        self.factory_kwargs = factory_kwargs

        # Determine fallback model
        if fallback_model:
            self.fallback_model = fallback_model
        else:
            # Use provider-specific default
            self.fallback_model = self.DEFAULT_FALLBACK_MODELS.get(
                provider.lower(),
                'gpt-3.5-turbo'  # Ultimate fallback
            )

        # Track token usage from wrapped client
        self.total_prompt_tokens = wrapped_client.total_prompt_tokens
        self.total_completion_tokens = wrapped_client.total_completion_tokens
        self.total_tokens = wrapped_client.total_tokens

    def analyze_code(
        self,
        system_prompt: str,
        user_content: str,
        stage_name: Optional[str] = None,
        commit_output_dir: Optional[str] = None,
        max_tokens: int = config.DEFAULT_MAX_TOKENS,
        temperature: Optional[float] = None
    ) -> str:
        """
        Send single prompt to LLM with automatic reset on fatal errors.

        Args:
            system_prompt: System prompt (instructions, context)
            user_content: User content (diff, code, etc.)
            stage_name: Stage name for prompt dumping
            commit_output_dir: Output directory for prompt dumping
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (None = use model default)

        Returns:
            LLM response text
        """
        return self._call_with_reset(
            lambda: self.client.analyze_code(
                system_prompt, user_content, stage_name, commit_output_dir, max_tokens, temperature
            )
        )

    def analyze_with_context(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = config.DEFAULT_MAX_TOKENS,
        temperature: Optional[float] = None
    ) -> str:
        """
        Send multi-turn conversation to LLM with automatic reset on fatal errors.

        Args:
            messages: List of message dicts with 'role' and 'content'
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (None = use model default)

        Returns:
            LLM response text
        """
        return self._call_with_reset(
            lambda: self.client.analyze_with_context(
                messages, max_tokens, temperature
            )
        )

    def analyze_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        max_iterations: int = 10,
        max_tokens: int = config.DEFAULT_MAX_TOKENS,
        temperature: Optional[float] = None
    ) -> str:
        """
        Analyze with tool calling enabled (automatic reset on fatal errors).

        Args:
            system_prompt: System instructions
            user_prompt: User query/task
            max_iterations: Maximum tool calling iterations
            max_tokens: Maximum tokens per response
            temperature: Sampling temperature (None = use model default)

        Returns:
            Final LLM response after all tool calls
        """
        # Check if wrapped client supports tool calling
        if not hasattr(self.client, 'analyze_with_tools'):
            raise AttributeError(
                f"Wrapped client ({type(self.client).__name__}) does not support tool calling"
            )

        return self._call_with_reset(
            lambda: self.client.analyze_with_tools(
                system_prompt, user_prompt, max_iterations, max_tokens, temperature
            )
        )

    def _call_with_reset(self, operation):
        """
        Execute operation with automatic host reset on fatal errors.

        Args:
            operation: Callable that performs the actual LLM operation

        Returns:
            Result from operation

        Raises:
            RuntimeError: If operation fails after all reset attempts
        """
        if not self.enable_reset:
            # Reset disabled, just call operation directly
            return operation()

        last_error = None
        reset_attempt = 0

        # Loop until success or max attempts reached (0 = unlimited)
        while True:
            try:
                result = operation()

                # Sync token usage from wrapped client
                self.total_prompt_tokens = self.client.total_prompt_tokens
                self.total_completion_tokens = self.client.total_completion_tokens
                self.total_tokens = self.client.total_tokens

                return result

            except RuntimeError as e:
                last_error = e

                # Check if this is a fatal host error
                if not is_fatal_host_error(e):
                    # Not a fatal error, propagate immediately
                    raise

                # Fatal error detected - check if we should continue trying
                reset_attempt += 1

                # Check if we've exhausted attempts (0 = unlimited)
                if self.max_reset_attempts > 0 and reset_attempt >= self.max_reset_attempts:
                    # Out of reset attempts
                    if self.verbose or self.debug:
                        print(
                            f"[HOST RESET] Max reset attempts ({self.max_reset_attempts}) "
                            f"exhausted, giving up",
                            file=sys.stderr
                        )
                    raise

                # Perform reset and continue loop
                self._perform_host_reset(attempt=reset_attempt)

    def _perform_host_reset(self, attempt: int):
        """
        Perform host reset by creating temp client and sending test query.

        Args:
            attempt: Current reset attempt number (1-indexed)
        """
        if self.max_reset_attempts > 0:
            print(
                f"[HOST RESET] Detected fatal error, attempting reset "
                f"(attempt {attempt}/{self.max_reset_attempts})...",
                file=sys.stderr
            )
        else:
            print(
                f"[HOST RESET] Detected fatal error, attempting reset "
                f"(attempt {attempt})...",
                file=sys.stderr
            )

        try:
            # Import here to avoid circular dependency
            from .client_factory import create_llm_client

            # Create temporary client with fallback model
            temp_kwargs = self.factory_kwargs.copy()
            temp_kwargs['model'] = self.fallback_model
            temp_kwargs['verbose'] = False  # Quiet during reset
            temp_kwargs['debug'] = False

            if self.debug:
                print(
                    f"Creating temp client with model: {self.fallback_model}",
                    file=sys.stderr
                )

            temp_client = create_llm_client(**temp_kwargs)

            # Send minimal test query
            test_response = temp_client.analyze_code(
                system_prompt="You are a helpful assistant.",
                user_content="Respond with OK",
                max_tokens=10
            )

            if self.debug:
                print(
                    f"Reset test response: {test_response}",
                    file=sys.stderr
                )

            print(
                f"[HOST RESET] Reset successful, retrying operation...",
                file=sys.stderr
            )

        except Exception as e:
            # Reset failed, but continue anyway - original operation might work now
            if self.verbose or self.debug:
                print(
                    f"[HOST RESET] Reset test query failed: {e}",
                    file=sys.stderr
                )
                print(
                    f"[HOST RESET] Continuing anyway, will retry original operation...",
                    file=sys.stderr
                )

    def get_token_usage(self) -> Dict[str, int]:
        """
        Get total token usage including wrapped client.

        Returns:
            Dictionary with 'prompt_tokens', 'completion_tokens', 'total_tokens'
        """
        # Sync from wrapped client first
        self.total_prompt_tokens = self.client.total_prompt_tokens
        self.total_completion_tokens = self.client.total_completion_tokens
        self.total_tokens = self.client.total_tokens

        return super().get_token_usage()

    def reset_token_usage(self):
        """Reset token usage counters."""
        super().reset_token_usage()
        self.client.reset_token_usage()
