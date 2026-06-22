"""Anthropic Claude on Google Vertex AI client."""

import time
import os
import sys
from typing import List, Dict, Optional, Any

try:
    from anthropic import AnthropicVertex
    ANTHROPIC_VERTEX_AVAILABLE = True
except ImportError:
    ANTHROPIC_VERTEX_AVAILABLE = False

import config
from .base_client import LLMClient


class AnthropicVertexClient(LLMClient):
    """Client for communicating with Claude on Google Vertex AI."""

    def __init__(
        self,
        project_id: str = None,
        location: str = "us-east5",
        model: str = "claude-3-5-sonnet@20241022",
        verbose: bool = False,
        debug: bool = False,
        dump_prompts: bool = False,
        dump_dir: str = config.DEBUG_DUMP_DIR,
        **kwargs
    ):
        """
        Initialize Anthropic Vertex AI client.

        Args:
            project_id: Google Cloud project ID (or set GOOGLE_CLOUD_PROJECT env var)
            location: Google Cloud region (default: us-east5 for Claude)
            model: Model name (default: claude-3-5-sonnet@20241022)
            verbose: Enable verbose output
            debug: Enable debug output
            dump_prompts: Dump prompts and responses to files
            dump_dir: Directory for prompt/response dumps
        """
        if not ANTHROPIC_VERTEX_AVAILABLE:
            raise RuntimeError(
                "anthropic package with Vertex AI support not installed. "
                "Install with: pip install 'anthropic[vertex]'"
            )

        super().__init__(model, verbose, debug, dump_prompts, dump_dir)

        # Get project ID from parameter or environment
        self.project_id = project_id or os.environ.get('GOOGLE_CLOUD_PROJECT')
        if not self.project_id:
            raise RuntimeError(
                "Google Cloud project ID required. Set GOOGLE_CLOUD_PROJECT environment "
                "variable or pass project_id parameter."
            )

        self.location = location

        # Create dump directory if needed
        if self.dump_prompts and not os.path.exists(self.dump_dir):
            os.makedirs(self.dump_dir)
            if self.debug:
                print(f"Created dump directory: {self.dump_dir}")

        try:
            self.client = AnthropicVertex(
                project_id=self.project_id,
                region=self.location
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Anthropic Vertex AI client: {e}")

        if self.debug:
            print(f"Anthropic Vertex AI client initialized")
            print(f"Project: {self.project_id}, Location: {self.location}")
            print(f"Using model: {self.model}")

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
            stage_name: Stage name for prompt dumping (optional)
            commit_output_dir: Output directory for prompt dumping (optional)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (None = use model default)

        Returns:
            LLM response text
        """
        messages = [
            {"role": "user", "content": user_content}
        ]

        return self._call_with_retry(
            system_prompt, messages, max_tokens, temperature,
            stage_name=stage_name, commit_output_dir=commit_output_dir
        )

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
        temperature: Optional[float],
        stage_name: Optional[str] = None,
        commit_output_dir: Optional[str] = None
    ) -> str:
        """Call Anthropic Vertex AI with exponential backoff retry."""
        last_error = None

        # Increment call counter for dump filenames
        self.call_counter += 1
        call_id = self.call_counter

        # Dump prompt if enabled
        if self.dump_prompts:
            self._dump_prompt(
                call_id, system_prompt, messages, max_tokens, temperature,
                stage_name=stage_name, commit_output_dir=commit_output_dir
            )

        for attempt in range(config.MAX_RETRIES):
            try:
                if self.verbose and attempt > 0:
                    print(f"Retry attempt {attempt + 1}/{config.MAX_RETRIES}")

                if self.debug:
                    temp_str = f"{temperature}" if temperature is not None else "default"
                    print(f"Anthropic Vertex call #{call_id}: model={self.model}, max_tokens={max_tokens}, temp={temp_str}")
                    print(f"System prompt length: {len(system_prompt)} chars")
                    total_msg_len = sum(len(m['content']) for m in messages)
                    print(f"Messages total length: {total_msg_len} chars")

                # Build API call kwargs
                api_kwargs: Dict[str, Any] = {
                    "model": self.model,
                    "system": system_prompt,
                    "messages": messages,
                    "max_tokens": max_tokens
                }
                if temperature is not None:
                    api_kwargs["temperature"] = temperature

                response = self.client.messages.create(**api_kwargs)

                response_text = response.content[0].text
                stop_reason = response.stop_reason

                if self.debug:
                    print(f"Response length: {len(response_text)} chars")
                    print(f"Stop reason: {stop_reason}")
                    print(f"Token usage - input: {response.usage.input_tokens}, output: {response.usage.output_tokens}")

                # Check for truncated response
                if stop_reason == "max_tokens":
                    warning_msg = (
                        f"[WARNING] Response was truncated due to token limit ({max_tokens} tokens). "
                        f"This may cause JSON parsing errors. "
                        f"Increase max_tokens in the calling code or in config.py."
                    )
                    print(f"\n{warning_msg}\n", file=sys.stderr)
                    if self.debug:
                        print(f"Response ended with: ...{response_text[-100:]}")

                # Check if response is close to limit
                completion_tokens = response.usage.output_tokens
                usage_ratio = completion_tokens / max_tokens
                if usage_ratio > config.TRUNCATION_WARNING_THRESHOLD:
                    if self.verbose or self.debug:
                        print(f"[WARNING] Response used {completion_tokens}/{max_tokens} tokens "
                              f"({usage_ratio*100:.1f}%) - may be truncated")

                # Dump response if enabled
                if self.dump_prompts:
                    self._dump_response(
                        call_id, response_text,
                        stage_name=stage_name, commit_output_dir=commit_output_dir
                    )

                return response_text

            except Exception as e:
                last_error = e
                error_type = type(e).__name__

                # Check for timeout/connection errors
                if 'timeout' in str(e).lower() or isinstance(e, TimeoutError):
                    error_msg = f"Anthropic Vertex request timed out"
                    if self.verbose or self.debug:
                        print(f"[TIMEOUT] {error_msg}")
                elif 'connection' in str(e).lower() or 'permission' in str(e).lower():
                    error_msg = f"Failed to connect to Anthropic on Vertex AI"
                    if self.verbose or self.debug:
                        print(f"[CONNECTION ERROR] {error_msg}")
                        print(f"[CONNECTION ERROR] Ensure you're authenticated: gcloud auth application-default login")
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
                f"Anthropic Vertex request timed out after {config.MAX_RETRIES} attempts. "
                f"Try using a faster model or reducing the prompt size."
            )
        else:
            raise RuntimeError(f"Anthropic Vertex AI call failed after {config.MAX_RETRIES} attempts: {last_error}")

    def _dump_prompt(
        self,
        call_id: int,
        system_prompt: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: Optional[float],
        stage_name: Optional[str] = None,
        commit_output_dir: Optional[str] = None
    ):
        """Dump prompt to file for debugging."""
        # Determine output directory and filename
        if commit_output_dir and stage_name:
            prompts_dir = os.path.join(commit_output_dir, "prompts")
            os.makedirs(prompts_dir, exist_ok=True)
            filename = os.path.join(prompts_dir, f"{stage_name}-{call_id:03d}-prompt.txt")
        elif commit_output_dir:
            prompts_dir = os.path.join(commit_output_dir, "prompts")
            os.makedirs(prompts_dir, exist_ok=True)
            filename = os.path.join(prompts_dir, f"{call_id:03d}_prompt.txt")
        else:
            os.makedirs(self.dump_dir, exist_ok=True)
            filename = os.path.join(self.dump_dir, f"{call_id:03d}_prompt.txt")

        try:
            with open(filename, 'w') as f:
                f.write(f"=== Anthropic Vertex AI Call #{call_id} ===\n")
                f.write(f"Model: {self.model}\n")
                f.write(f"Project: {self.project_id}\n")
                f.write(f"Location: {self.location}\n")
                f.write(f"Max Tokens: {max_tokens}\n")
                temp_str = f"{temperature}" if temperature is not None else "default"
                f.write(f"Temperature: {temp_str}\n")
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
                print(f"Dumped prompt to: {filename}")

        except Exception as e:
            print(f"Warning: Failed to dump prompt: {e}")

    def _dump_response(
        self,
        call_id: int,
        response: str,
        stage_name: Optional[str] = None,
        commit_output_dir: Optional[str] = None
    ):
        """Dump response to file for debugging."""
        # Determine output directory and filename
        if commit_output_dir and stage_name:
            prompts_dir = os.path.join(commit_output_dir, "prompts")
            os.makedirs(prompts_dir, exist_ok=True)
            filename = os.path.join(prompts_dir, f"{stage_name}-{call_id:03d}-response.txt")
        elif commit_output_dir:
            prompts_dir = os.path.join(commit_output_dir, "prompts")
            os.makedirs(prompts_dir, exist_ok=True)
            filename = os.path.join(prompts_dir, f"{call_id:03d}_response.txt")
        else:
            os.makedirs(self.dump_dir, exist_ok=True)
            filename = os.path.join(self.dump_dir, f"{call_id:03d}_response.txt")

        try:
            with open(filename, 'w') as f:
                f.write(f"=== Anthropic Vertex AI Response #{call_id} ===\n\n")
                f.write(response)
                f.write("\n")

            if self.debug:
                print(f"Dumped response to: {filename}")

        except Exception as e:
            print(f"Warning: Failed to dump response: {e}")
