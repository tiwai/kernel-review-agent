"""Anthropic Claude API client for LLM communication."""

import time
import os
import sys
from typing import List, Dict

try:
    import anthropic
    from anthropic import Anthropic, APITimeoutError, APIConnectionError
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

import config
from .base_client import LLMClient


class AnthropicClient(LLMClient):
    """Client for communicating with Anthropic Claude API."""

    def __init__(
        self,
        api_key: str = None,
        model: str = "claude-3-5-sonnet-20241022",
        verbose: bool = False,
        debug: bool = False,
        dump_prompts: bool = False,
        dump_dir: str = config.DEBUG_DUMP_DIR,
        **kwargs
    ):
        """
        Initialize Anthropic client.

        Args:
            api_key: Anthropic API key (or set ANTHROPIC_API_KEY env var)
            model: Model name (default: claude-3-5-sonnet-20241022)
            verbose: Enable verbose output
            debug: Enable debug output
            dump_prompts: Dump prompts and responses to files
            dump_dir: Directory for prompt/response dumps
        """
        if not ANTHROPIC_AVAILABLE:
            raise RuntimeError(
                "anthropic package not installed. Install with: pip install anthropic"
            )

        super().__init__(model, verbose, debug, dump_prompts, dump_dir)

        # Get API key from parameter or environment
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise RuntimeError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY environment variable "
                "or pass api_key parameter."
            )

        # Create dump directory if needed
        if self.dump_prompts and not os.path.exists(self.dump_dir):
            os.makedirs(self.dump_dir)
            if self.debug:
                print(f"[DEBUG] Created dump directory: {self.dump_dir}")

        try:
            self.client = Anthropic(
                api_key=self.api_key,
                timeout=config.LLM_TIMEOUT
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Anthropic client: {e}")

        if self.debug:
            print(f"[DEBUG] Anthropic client initialized with timeout: {config.LLM_TIMEOUT}s")
            print(f"[DEBUG] Using model: {self.model}")

    def analyze_code(
        self,
        system_prompt: str,
        user_content: str,
        max_tokens: int = config.DEFAULT_MAX_TOKENS,
        temperature: float = config.DEFAULT_TEMPERATURE
    ) -> str:
        """
        Send single prompt to LLM and get response.

        Args:
            system_prompt: System prompt (instructions, context)
            user_content: User content (diff, code, etc.)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature

        Returns:
            LLM response text
        """
        messages = [
            {"role": "user", "content": user_content}
        ]

        return self._call_with_retry(system_prompt, messages, max_tokens, temperature)

    def analyze_with_context(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = config.DEFAULT_MAX_TOKENS,
        temperature: float = config.DEFAULT_TEMPERATURE
    ) -> str:
        """
        Send multi-turn conversation to LLM.

        Args:
            messages: List of message dicts with 'role' and 'content'
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature

        Returns:
            LLM response text
        """
        # Extract system prompt if present
        system_prompt = ""
        user_messages = []

        for msg in messages:
            if msg['role'] == 'system':
                system_prompt = msg['content']
            else:
                user_messages.append(msg)

        return self._call_with_retry(system_prompt, user_messages, max_tokens, temperature)

    def _call_with_retry(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float
    ) -> str:
        """Call Anthropic API with exponential backoff retry."""
        last_error = None

        # Increment call counter for dump filenames
        self.call_counter += 1
        call_id = self.call_counter

        # Dump prompt if enabled
        if self.dump_prompts:
            self._dump_prompt(call_id, system_prompt, messages, max_tokens, temperature)

        for attempt in range(config.MAX_RETRIES):
            try:
                if self.verbose and attempt > 0:
                    print(f"Retry attempt {attempt + 1}/{config.MAX_RETRIES}")

                if self.debug:
                    print(f"[DEBUG] Anthropic call #{call_id}: model={self.model}, max_tokens={max_tokens}, temp={temperature}")
                    print(f"[DEBUG] System prompt length: {len(system_prompt)} chars")
                    total_msg_len = sum(len(m['content']) for m in messages)
                    print(f"[DEBUG] Messages total length: {total_msg_len} chars")

                response = self.client.messages.create(
                    model=self.model,
                    system=system_prompt,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature
                )

                response_text = response.content[0].text
                stop_reason = response.stop_reason

                if self.debug:
                    print(f"[DEBUG] Response length: {len(response_text)} chars")
                    print(f"[DEBUG] Stop reason: {stop_reason}")
                    print(f"[DEBUG] Token usage - input: {response.usage.input_tokens}, output: {response.usage.output_tokens}")

                # Check for truncated response
                if stop_reason == "max_tokens":
                    warning_msg = (
                        f"[WARNING] Response was truncated due to token limit ({max_tokens} tokens). "
                        f"This may cause JSON parsing errors. "
                        f"Increase max_tokens in the calling code or in config.py."
                    )
                    print(f"\n{warning_msg}\n", file=sys.stderr)
                    if self.debug:
                        print(f"[DEBUG] Response ended with: ...{response_text[-100:]}")

                # Check if response is close to limit
                completion_tokens = response.usage.output_tokens
                usage_ratio = completion_tokens / max_tokens
                if usage_ratio > config.TRUNCATION_WARNING_THRESHOLD:
                    if self.verbose or self.debug:
                        print(f"[WARNING] Response used {completion_tokens}/{max_tokens} tokens "
                              f"({usage_ratio*100:.1f}%) - may be truncated")

                # Dump response if enabled
                if self.dump_prompts:
                    self._dump_response(call_id, response_text)

                return response_text

            except Exception as e:
                last_error = e
                error_type = type(e).__name__

                # Check for timeout/connection errors
                if 'timeout' in str(e).lower() or isinstance(e, TimeoutError):
                    error_msg = f"Anthropic request timed out after {config.LLM_TIMEOUT}s"
                    if self.verbose or self.debug:
                        print(f"[TIMEOUT] {error_msg}")
                elif 'connection' in str(e).lower():
                    error_msg = f"Failed to connect to Anthropic API"
                    if self.verbose or self.debug:
                        print(f"[CONNECTION ERROR] {error_msg}")
                else:
                    if self.verbose or self.debug:
                        print(f"[ERROR] {error_type}: {e}")

                if attempt < config.MAX_RETRIES - 1:
                    delay = config.RETRY_DELAY * (config.RETRY_BACKOFF ** attempt)
                    if self.verbose:
                        print(f"Retrying in {delay:.1f}s... (attempt {attempt + 2}/{config.MAX_RETRIES})")
                    time.sleep(delay)
                else:
                    if self.verbose:
                        print(f"All retry attempts exhausted")

        # Provide specific error message
        if 'timeout' in str(last_error).lower():
            raise RuntimeError(
                f"Anthropic request timed out after {config.MAX_RETRIES} attempts. "
                f"Each request times out after {config.LLM_TIMEOUT}s. "
                f"Try increasing LLM_TIMEOUT in config.py or using a faster model."
            )
        else:
            raise RuntimeError(f"Anthropic API call failed after {config.MAX_RETRIES} attempts: {last_error}")

    def _dump_prompt(
        self,
        call_id: int,
        system_prompt: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float
    ):
        """Dump prompt to file for debugging."""
        filename = os.path.join(self.dump_dir, f"{call_id:03d}_prompt.txt")

        try:
            with open(filename, 'w') as f:
                f.write(f"=== Anthropic Call #{call_id} ===\n")
                f.write(f"Model: {self.model}\n")
                f.write(f"Max Tokens: {max_tokens}\n")
                f.write(f"Temperature: {temperature}\n")
                f.write(f"\n{'='*80}\n\n")

                if system_prompt:
                    f.write(f"--- SYSTEM PROMPT ---\n\n")
                    f.write(system_prompt)
                    f.write(f"\n\n{'='*80}\n\n")

                for i, msg in enumerate(messages):
                    role = msg['role'].upper()
                    content = msg['content']
                    f.write(f"--- {role} MESSAGE ---\n\n")
                    f.write(content)
                    f.write(f"\n\n{'='*80}\n\n")

            if self.debug:
                print(f"[DEBUG] Dumped prompt to: {filename}")

        except Exception as e:
            print(f"Warning: Failed to dump prompt: {e}")

    def _dump_response(self, call_id: int, response: str):
        """Dump response to file for debugging."""
        filename = os.path.join(self.dump_dir, f"{call_id:03d}_response.txt")

        try:
            with open(filename, 'w') as f:
                f.write(f"=== Anthropic Response #{call_id} ===\n\n")
                f.write(response)
                f.write("\n")

            if self.debug:
                print(f"[DEBUG] Dumped response to: {filename}")

        except Exception as e:
            print(f"Warning: Failed to dump response: {e}")
