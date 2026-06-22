"""OpenAI-compatible API client for LLM communication."""

import time
import os
import sys
from typing import List, Dict, Optional, Any
from openai import OpenAI
from openai import APITimeoutError, APIConnectionError

import config
from .base_client import LLMClient


class OpenAIClient(LLMClient):
    """Client for communicating with OpenAI-compatible LLM API."""

    def __init__(
        self,
        host: str = config.DEFAULT_HOST,
        port: int = config.DEFAULT_PORT,
        api_key: str = config.DEFAULT_API_KEY,
        model: str = config.DEFAULT_MODEL,
        verbose: bool = False,
        debug: bool = False,
        dump_prompts: bool = False,
        dump_dir: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize OpenAI client.

        Args:
            host: API server host
            port: API server port
            api_key: API key (use "dummy" for local servers)
            model: Model name to use
            verbose: Enable verbose output
            debug: Enable debug output
            dump_prompts: Save prompts and responses to commit output directories
            dump_dir: (Deprecated) Legacy dump directory
            reasoning_effort: Reasoning effort level for models that support it
        """
        super().__init__(model, verbose, debug, dump_prompts, dump_dir)

        self.base_url = f"http://{host}:{port}/v1"
        self.api_key = api_key
        self.reasoning_effort = reasoning_effort

        try:
            # For HTTP connections (local servers), disable SSL verification
            # to avoid certificate issues
            import httpx
            http_client = None
            if self.base_url.startswith('http://'):
                http_client = httpx.Client(verify=False)

            self.client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=config.LLM_TIMEOUT,
                http_client=http_client
            )
        except Exception as e:
            import traceback
            raise RuntimeError(f"Failed to initialize OpenAI client: {e}\nTraceback: {traceback.format_exc()}")

        if self.debug:
            print(f"[DEBUG] OpenAI client initialized with timeout: {config.LLM_TIMEOUT}s")

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

        response_text, _ = self._call_with_retry(messages, max_tokens, temperature, stage_name, commit_output_dir)
        return response_text

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
        response_text, _ = self._call_with_retry(messages, max_tokens, temperature, stage_name, commit_output_dir)
        return response_text

    def _call_with_retry(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: Optional[float],
        stage_name: Optional[str] = None,
        commit_output_dir: Optional[str] = None
    ) -> tuple[str, Dict[str, int]]:
        """
        Call LLM API with exponential backoff retry.

        Args:
            messages: List of message dicts with 'role' and 'content'
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            stage_name: Stage name for prompt dumping
            commit_output_dir: Output directory for prompt dumping

        Returns:
            Tuple of (response_text, usage_dict) where usage_dict contains
            'prompt_tokens', 'completion_tokens', and 'total_tokens'
        """
        last_error = None

        # Increment call counter for dump filenames
        self.call_counter += 1
        call_id = self.call_counter

        # Dump prompt if enabled
        if self.dump_prompts:
            self._dump_prompt(call_id, messages, max_tokens, temperature, stage_name, commit_output_dir)

        for attempt in range(config.MAX_RETRIES):
            try:
                if self.verbose and attempt > 0:
                    print(f"Retry attempt {attempt + 1}/{config.MAX_RETRIES}")

                if self.debug:
                    temp_str = f"{temperature}" if temperature is not None else "default"
                    print(f"[DEBUG] LLM call #{call_id}: model={self.model}, max_tokens={max_tokens}, temp={temp_str}")
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
                if self.reasoning_effort is not None:
                    api_kwargs["reasoning_effort"] = self.reasoning_effort

                response = self.client.chat.completions.create(**api_kwargs)

                response_text = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason

                # Extract thinking/reasoning blocks if present
                thinking_text = None
                if hasattr(response.choices[0].message, 'extended_thinking'):
                    thinking_text = response.choices[0].message.extended_thinking
                elif hasattr(response.choices[0].message, 'reasoning'):
                    thinking_text = response.choices[0].message.reasoning

                # Extract token usage if available
                usage_dict = {
                    'prompt_tokens': 0,
                    'completion_tokens': 0,
                    'total_tokens': 0
                }
                if hasattr(response, 'usage') and response.usage:
                    usage_dict['prompt_tokens'] = response.usage.prompt_tokens
                    usage_dict['completion_tokens'] = response.usage.completion_tokens
                    usage_dict['total_tokens'] = response.usage.total_tokens
                    # Accumulate to totals
                    self.total_prompt_tokens += usage_dict['prompt_tokens']
                    self.total_completion_tokens += usage_dict['completion_tokens']
                    self.total_tokens += usage_dict['total_tokens']

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

                # Dump response and thinking if enabled
                if self.dump_prompts:
                    self._dump_response(call_id, response_text, thinking_text, usage_dict, finish_reason, stage_name, commit_output_dir)

                return response_text, usage_dict

            except APITimeoutError as e:
                last_error = e
                error_msg = f"LLM request timed out after {config.LLM_TIMEOUT}s"
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
                error_msg = f"Failed to connect to LLM server at {self.base_url}"
                if self.verbose or self.debug:
                    print(f"[CONNECTION ERROR] {error_msg}")

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
                f"LLM request timed out after {config.MAX_RETRIES} attempts. "
                f"Each request times out after {config.LLM_TIMEOUT}s. "
                f"Try increasing LLM_TIMEOUT in config.py or using a faster model."
            )
        elif isinstance(last_error, APIConnectionError):
            raise RuntimeError(
                f"Failed to connect to LLM server at {self.base_url} after {config.MAX_RETRIES} attempts. "
                f"Ensure the server is running and accessible."
            )
        else:
            raise RuntimeError(f"LLM API call failed after {config.MAX_RETRIES} attempts: {last_error}")

    def _dump_prompt(
        self,
        call_id: int,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: Optional[float],
        stage_name: Optional[str] = None,
        commit_output_dir: Optional[str] = None
    ):
        """Dump prompt to file for training data export."""
        # Determine output directory and filename
        if commit_output_dir and stage_name:
            # New structure: output_dir/prompts/stage-prompt.txt
            prompts_dir = os.path.join(commit_output_dir, "prompts")
            os.makedirs(prompts_dir, exist_ok=True)
            filename = os.path.join(prompts_dir, f"{stage_name}-prompt.txt")
        else:
            # Fallback to old structure for compatibility
            os.makedirs(self.dump_dir, exist_ok=True)
            filename = os.path.join(self.dump_dir, f"{call_id:03d}_prompt.txt")

        try:
            with open(filename, 'w') as f:
                f.write(f"=== LLM Call #{call_id} ===\n")
                f.write(f"Model: {self.model}\n")
                f.write(f"Max Tokens: {max_tokens}\n")
                temp_str = f"{temperature}" if temperature is not None else "default"
                f.write(f"Temperature: {temp_str}\n")
                if self.reasoning_effort:
                    f.write(f"Reasoning Effort: {self.reasoning_effort}\n")
                if stage_name:
                    f.write(f"Stage: {stage_name}\n")
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

    def _dump_response(
        self,
        call_id: int,
        response: str,
        thinking: Optional[str] = None,
        usage_dict: Optional[Dict] = None,
        finish_reason: Optional[str] = None,
        stage_name: Optional[str] = None,
        commit_output_dir: Optional[str] = None
    ):
        """Dump response, thinking, and metadata to files for training data export."""
        # Determine output directory and filenames
        if commit_output_dir and stage_name:
            # New structure: output_dir/prompts/stage-*.txt and stage-metadata.json
            prompts_dir = os.path.join(commit_output_dir, "prompts")
            os.makedirs(prompts_dir, exist_ok=True)
            response_file = os.path.join(prompts_dir, f"{stage_name}-response.txt")
            thinking_file = os.path.join(prompts_dir, f"{stage_name}-thinking.txt")
            metadata_file = os.path.join(prompts_dir, f"{stage_name}-metadata.json")
        else:
            # Fallback to old structure
            os.makedirs(self.dump_dir, exist_ok=True)
            response_file = os.path.join(self.dump_dir, f"{call_id:03d}_response.txt")
            thinking_file = None
            metadata_file = None

        try:
            # Dump response
            with open(response_file, 'w') as f:
                f.write(f"=== LLM Response #{call_id} ===\n\n")
                f.write(response)
                f.write("\n")

            if self.debug:
                print(f"[DEBUG] Dumped response to: {response_file}")

            # Dump thinking if present (only in new structure)
            if thinking and thinking_file:
                with open(thinking_file, 'w') as f:
                    f.write(thinking)
                if self.debug:
                    print(f"[DEBUG] Dumped thinking to: {thinking_file}")

            # Dump metadata (only in new structure)
            if metadata_file and stage_name:
                import json
                from datetime import datetime, timezone
                metadata = {
                    "stage": stage_name,
                    "model": self.model,
                    "max_tokens": usage_dict.get('total_tokens', 0) if usage_dict else 0,
                    "temperature": None,  # Would need to be passed from caller
                    "reasoning_effort": self.reasoning_effort,
                    "input_tokens": usage_dict.get('prompt_tokens', 0) if usage_dict else 0,
                    "output_tokens": usage_dict.get('completion_tokens', 0) if usage_dict else 0,
                    "total_tokens": usage_dict.get('total_tokens', 0) if usage_dict else 0,
                    "finish_reason": finish_reason,
                    "has_thinking": thinking is not None and len(thinking) > 0,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f, indent=2)
                if self.debug:
                    print(f"[DEBUG] Dumped metadata to: {metadata_file}")

        except Exception as e:
            print(f"Warning: Failed to dump response: {e}")

    def stream_response(
        self,
        system_prompt: str,
        user_content: str,
        max_tokens: int = config.DEFAULT_MAX_TOKENS,
        temperature: Optional[float] = None
    ):
        """
        Stream LLM response for better UX (yields chunks).

        Args:
            system_prompt: System prompt
            user_content: User content
            max_tokens: Maximum tokens
            temperature: Sampling temperature (None = use model default)

        Yields:
            Response chunks as they arrive
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        try:
            # Build API call kwargs
            api_kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": True
            }
            if temperature is not None:
                api_kwargs["temperature"] = temperature

            response = self.client.chat.completions.create(**api_kwargs)

            for chunk in response:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            raise RuntimeError(f"Streaming failed: {e}")
