"""Ollama client for LLM communication."""

import time
import os
import sys
from typing import List, Dict, Optional, Any

try:
    from openai import OpenAI
    from openai import APITimeoutError, APIConnectionError
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

import config
from .base_client import LLMClient


class OllamaClient(LLMClient):
    """Client for communicating with Ollama (OpenAI-compatible API)."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 11434,
        model: str = "llama3.1",
        verbose: bool = False,
        debug: bool = False,
        dump_prompts: bool = False,
        dump_dir: str = config.DEBUG_DUMP_DIR,
        **kwargs
    ):
        """
        Initialize Ollama client.

        Args:
            host: Ollama server host (default: localhost)
            port: Ollama server port (default: 11434)
            model: Model name (default: llama3.1)
            verbose: Enable verbose output
            debug: Enable debug output
            dump_prompts: Dump prompts and responses to files
            dump_dir: Directory for prompt/response dumps
        """
        if not OPENAI_AVAILABLE:
            raise RuntimeError(
                "openai package not installed. Install with: pip install openai"
            )

        super().__init__(model, verbose, debug, dump_prompts, dump_dir)

        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}/v1"

        # Create dump directory if needed
        if self.dump_prompts and not os.path.exists(self.dump_dir):
            os.makedirs(self.dump_dir)
            if self.debug:
                print(f"[DEBUG] Created dump directory: {self.dump_dir}")

        try:
            self.client = OpenAI(
                base_url=self.base_url,
                api_key="ollama",  # Ollama doesn't require real API key
                timeout=config.LLM_TIMEOUT
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Ollama client: {e}")

        if self.debug:
            print(f"[DEBUG] Ollama client initialized with timeout: {config.LLM_TIMEOUT}s")
            print(f"[DEBUG] Server: {self.base_url}")
            print(f"[DEBUG] Using model: {self.model}")

    def analyze_code(
        self,
        system_prompt: str,
        user_content: str,
        max_tokens: int = config.DEFAULT_MAX_TOKENS,
        temperature: Optional[float] = None
    ) -> str:
        """
        Send single prompt to LLM and get response.

        Args:
            system_prompt: System prompt (instructions, context)
            user_content: User content (diff, code, etc.)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (None = use model default)

        Returns:
            LLM response text
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        return self._call_with_retry(messages, max_tokens, temperature)

    def analyze_with_context(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = config.DEFAULT_MAX_TOKENS,
        temperature: Optional[float] = None
    ) -> str:
        """
        Send multi-turn conversation to LLM.

        Args:
            messages: List of message dicts with 'role' and 'content'
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (None = use model default)

        Returns:
            LLM response text
        """
        return self._call_with_retry(messages, max_tokens, temperature)

    def _call_with_retry(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: Optional[float]
    ) -> str:
        """Call Ollama API with exponential backoff retry."""
        last_error = None

        # Increment call counter for dump filenames
        self.call_counter += 1
        call_id = self.call_counter

        # Dump prompt if enabled
        if self.dump_prompts:
            self._dump_prompt(call_id, messages, max_tokens, temperature)

        for attempt in range(config.MAX_RETRIES):
            try:
                if self.verbose and attempt > 0:
                    print(f"Retry attempt {attempt + 1}/{config.MAX_RETRIES}")

                if self.debug:
                    temp_str = f"{temperature}" if temperature is not None else "default"
                    print(f"[DEBUG] Ollama call #{call_id}: model={self.model}, max_tokens={max_tokens}, temp={temp_str}")
                    print(f"[DEBUG] System prompt length: {len(messages[0]['content'])} chars")
                    if len(messages) > 1:
                        print(f"[DEBUG] User prompt length: {len(messages[1]['content'])} chars")

                # Build API call kwargs
                api_kwargs: Dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "stream": False
                }
                if temperature is not None:
                    api_kwargs["temperature"] = temperature

                response = self.client.chat.completions.create(**api_kwargs)

                response_text = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason

                if self.debug:
                    print(f"[DEBUG] Response length: {len(response_text)} chars")
                    print(f"[DEBUG] Finish reason: {finish_reason}")
                    if hasattr(response, 'usage'):
                        print(f"[DEBUG] Token usage: {response.usage}")

                # Check for truncated response
                if finish_reason == "length":
                    warning_msg = (
                        f"[WARNING] Response was truncated due to token limit ({max_tokens} tokens). "
                        f"This may cause JSON parsing errors. "
                        f"Increase max_tokens in the calling code or in config.py."
                    )
                    print(f"\n{warning_msg}\n", file=sys.stderr)
                    if self.debug:
                        print(f"[DEBUG] Response ended with: ...{response_text[-100:]}")

                # Check if response is close to limit (may be cut off)
                if hasattr(response, 'usage'):
                    completion_tokens = response.usage.completion_tokens
                    usage_ratio = completion_tokens / max_tokens
                    if usage_ratio > config.TRUNCATION_WARNING_THRESHOLD:
                        if self.verbose or self.debug:
                            print(f"[WARNING] Response used {completion_tokens}/{max_tokens} tokens "
                                  f"({usage_ratio*100:.1f}%) - may be truncated")

                # Dump response if enabled
                if self.dump_prompts:
                    self._dump_response(call_id, response_text)

                return response_text

            except APITimeoutError as e:
                last_error = e
                error_msg = f"Ollama request timed out after {config.LLM_TIMEOUT}s"
                if self.verbose or self.debug:
                    print(f"[TIMEOUT] {error_msg}")

                if attempt < config.MAX_RETRIES - 1:
                    delay = config.RETRY_DELAY * (config.RETRY_BACKOFF ** attempt)
                    if self.verbose:
                        print(f"Retrying in {delay:.1f}s... (attempt {attempt + 2}/{config.MAX_RETRIES})")
                    time.sleep(delay)
                else:
                    if self.verbose:
                        print(f"All retry attempts exhausted")

            except APIConnectionError as e:
                last_error = e
                error_msg = f"Failed to connect to Ollama server at {self.base_url}"
                if self.verbose or self.debug:
                    print(f"[CONNECTION ERROR] {error_msg}")
                    print(f"[CONNECTION ERROR] Make sure Ollama is running: ollama serve")

                if attempt < config.MAX_RETRIES - 1:
                    delay = config.RETRY_DELAY * (config.RETRY_BACKOFF ** attempt)
                    if self.verbose:
                        print(f"Retrying in {delay:.1f}s... (attempt {attempt + 2}/{config.MAX_RETRIES})")
                    time.sleep(delay)
                else:
                    if self.verbose:
                        print(f"All retry attempts exhausted")

            except Exception as e:
                last_error = e
                error_type = type(e).__name__
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

        # Provide specific error message based on error type
        if isinstance(last_error, APITimeoutError):
            raise RuntimeError(
                f"Ollama request timed out after {config.MAX_RETRIES} attempts. "
                f"Each request times out after {config.LLM_TIMEOUT}s. "
                f"Try increasing LLM_TIMEOUT in config.py or using a faster model."
            )
        elif isinstance(last_error, APIConnectionError):
            raise RuntimeError(
                f"Failed to connect to Ollama server at {self.base_url} after {config.MAX_RETRIES} attempts. "
                f"Ensure Ollama is running (ollama serve) and accessible."
            )
        else:
            raise RuntimeError(f"Ollama API call failed after {config.MAX_RETRIES} attempts: {last_error}")

    def _dump_prompt(
        self,
        call_id: int,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: Optional[float]
    ):
        """Dump prompt to file for debugging."""
        filename = os.path.join(self.dump_dir, f"{call_id:03d}_prompt.txt")

        try:
            with open(filename, 'w') as f:
                f.write(f"=== Ollama Call #{call_id} ===\n")
                f.write(f"Server: {self.base_url}\n")
                f.write(f"Model: {self.model}\n")
                f.write(f"Max Tokens: {max_tokens}\n")
                temp_str = f"{temperature}" if temperature is not None else "default"
                f.write(f"Temperature: {temp_str}\n")
                f.write(f"\n{'='*80}\n\n")

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
                f.write(f"=== Ollama Response #{call_id} ===\n\n")
                f.write(response)
                f.write("\n")

            if self.debug:
                print(f"[DEBUG] Dumped response to: {filename}")

        except Exception as e:
            print(f"Warning: Failed to dump response: {e}")
