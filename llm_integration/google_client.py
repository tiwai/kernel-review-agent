"""Google Vertex AI client for LLM communication."""

import time
import os
import sys
from typing import List, Dict, Optional, Any

try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    VERTEXAI_AVAILABLE = True
except ImportError:
    VERTEXAI_AVAILABLE = False

import config
from .base_client import LLMClient


class GoogleClient(LLMClient):
    """Client for communicating with Google Vertex AI."""

    def __init__(
        self,
        project_id: str = None,
        location: str = "us-central1",
        model: str = "gemini-1.5-pro",
        verbose: bool = False,
        debug: bool = False,
        dump_prompts: bool = False,
        dump_dir: str = config.DEBUG_DUMP_DIR,
        **kwargs
    ):
        """
        Initialize Google Vertex AI client.

        Args:
            project_id: Google Cloud project ID (or set GOOGLE_CLOUD_PROJECT env var)
            location: Google Cloud region (default: us-central1)
            model: Model name (default: gemini-1.5-pro)
            verbose: Enable verbose output
            debug: Enable debug output
            dump_prompts: Dump prompts and responses to files
            dump_dir: Directory for prompt/response dumps
        """
        if not VERTEXAI_AVAILABLE:
            raise RuntimeError(
                "google-cloud-aiplatform package not installed. "
                "Install with: pip install google-cloud-aiplatform"
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
                print(f"[DEBUG] Created dump directory: {self.dump_dir}")

        try:
            vertexai.init(project=self.project_id, location=self.location)
            self.client = GenerativeModel(self.model)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Google Vertex AI client: {e}")

        if self.debug:
            print(f"[DEBUG] Google Vertex AI client initialized")
            print(f"[DEBUG] Project: {self.project_id}, Location: {self.location}")
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
        # Combine system and user prompts for Gemini
        combined_prompt = f"{system_prompt}\n\n{user_content}"

        return self._call_with_retry(combined_prompt, max_tokens, temperature)

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
        # Combine all messages for Gemini
        combined_prompt = "\n\n".join(
            f"{msg['role'].upper()}: {msg['content']}"
            for msg in messages
        )

        return self._call_with_retry(combined_prompt, max_tokens, temperature)

    def _call_with_retry(
        self,
        prompt: str,
        max_tokens: int,
        temperature: Optional[float]
    ) -> str:
        """Call Google Vertex AI with exponential backoff retry."""
        last_error = None

        # Increment call counter for dump filenames
        self.call_counter += 1
        call_id = self.call_counter

        # Dump prompt if enabled
        if self.dump_prompts:
            self._dump_prompt(call_id, prompt, max_tokens, temperature)

        # Configure generation parameters
        generation_config = {
            'max_output_tokens': max_tokens,
        }
        if temperature is not None:
            generation_config['temperature'] = temperature

        for attempt in range(config.MAX_RETRIES):
            try:
                if self.verbose and attempt > 0:
                    print(f"Retry attempt {attempt + 1}/{config.MAX_RETRIES}")

                if self.debug:
                    temp_str = f"{temperature}" if temperature is not None else "default"
                    print(f"[DEBUG] Google call #{call_id}: model={self.model}, max_tokens={max_tokens}, temp={temp_str}")
                    print(f"[DEBUG] Prompt length: {len(prompt)} chars")

                response = self.client.generate_content(
                    prompt,
                    generation_config=generation_config
                )

                response_text = response.text

                if self.debug:
                    print(f"[DEBUG] Response length: {len(response_text)} chars")
                    # Gemini doesn't always provide finish reason in the same way
                    if hasattr(response, 'candidates') and response.candidates:
                        finish_reason = response.candidates[0].finish_reason
                        print(f"[DEBUG] Finish reason: {finish_reason}")

                # Check for truncated response
                if hasattr(response, 'candidates') and response.candidates:
                    finish_reason = str(response.candidates[0].finish_reason)
                    if 'MAX_TOKENS' in finish_reason or 'LENGTH' in finish_reason:
                        warning_msg = (
                            f"[WARNING] Response was truncated due to token limit ({max_tokens} tokens). "
                            f"This may cause JSON parsing errors. "
                            f"Increase max_tokens in the calling code or in config.py."
                        )
                        print(f"\n{warning_msg}\n", file=sys.stderr)
                        if self.debug:
                            print(f"[DEBUG] Response ended with: ...{response_text[-100:]}")

                # Dump response if enabled
                if self.dump_prompts:
                    self._dump_response(call_id, response_text)

                return response_text

            except Exception as e:
                last_error = e
                error_type = type(e).__name__

                # Check for timeout/connection errors
                if 'timeout' in str(e).lower() or isinstance(e, TimeoutError):
                    error_msg = f"Google Vertex AI request timed out"
                    if self.verbose or self.debug:
                        print(f"[TIMEOUT] {error_msg}")
                elif 'connection' in str(e).lower():
                    error_msg = f"Failed to connect to Google Vertex AI"
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
                f"Google Vertex AI request timed out after {config.MAX_RETRIES} attempts. "
                f"Try using a faster model or reducing the prompt size."
            )
        else:
            raise RuntimeError(f"Google Vertex AI call failed after {config.MAX_RETRIES} attempts: {last_error}")

    def _dump_prompt(
        self,
        call_id: int,
        prompt: str,
        max_tokens: int,
        temperature: Optional[float]
    ):
        """Dump prompt to file for debugging."""
        filename = os.path.join(self.dump_dir, f"{call_id:03d}_prompt.txt")

        try:
            with open(filename, 'w') as f:
                f.write(f"=== Google Vertex AI Call #{call_id} ===\n")
                f.write(f"Model: {self.model}\n")
                f.write(f"Project: {self.project_id}\n")
                f.write(f"Location: {self.location}\n")
                f.write(f"Max Tokens: {max_tokens}\n")
                temp_str = f"{temperature}" if temperature is not None else "default"
                f.write(f"Temperature: {temp_str}\n")
                f.write(f"\n{'='*80}\n\n")
                f.write(prompt)
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
                f.write(f"=== Google Vertex AI Response #{call_id} ===\n\n")
                f.write(response)
                f.write("\n")

            if self.debug:
                print(f"[DEBUG] Dumped response to: {filename}")

        except Exception as e:
            print(f"Warning: Failed to dump response: {e}")
