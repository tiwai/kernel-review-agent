"""OpenAI-compatible API client for LLM communication."""

import time
from typing import List, Dict, Optional
from openai import OpenAI

import config


class OpenAIClient:
    """Client for communicating with OpenAI-compatible LLM API."""

    def __init__(
        self,
        host: str = config.DEFAULT_HOST,
        port: int = config.DEFAULT_PORT,
        api_key: str = config.DEFAULT_API_KEY,
        model: str = config.DEFAULT_MODEL,
        verbose: bool = False
    ):
        """
        Initialize OpenAI client.

        Args:
            host: API server host
            port: API server port
            api_key: API key (use "dummy" for local servers)
            model: Model name to use
            verbose: Enable verbose output
        """
        self.base_url = f"http://{host}:{port}/v1"
        self.api_key = api_key
        self.model = model
        self.verbose = verbose

        try:
            self.client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize OpenAI client: {e}")

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
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        return self._call_with_retry(messages, max_tokens, temperature)

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
        return self._call_with_retry(messages, max_tokens, temperature)

    def _call_with_retry(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float
    ) -> str:
        """Call LLM API with exponential backoff retry."""
        last_error = None

        for attempt in range(config.MAX_RETRIES):
            try:
                if self.verbose and attempt > 0:
                    print(f"Retry attempt {attempt + 1}/{config.MAX_RETRIES}")

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=False
                )

                return response.choices[0].message.content

            except Exception as e:
                last_error = e
                if attempt < config.MAX_RETRIES - 1:
                    delay = config.RETRY_DELAY * (config.RETRY_BACKOFF ** attempt)
                    if self.verbose:
                        print(f"Error: {e}. Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                else:
                    if self.verbose:
                        print(f"All retry attempts failed")

        raise RuntimeError(f"LLM API call failed after {config.MAX_RETRIES} attempts: {last_error}")

    def stream_response(
        self,
        system_prompt: str,
        user_content: str,
        max_tokens: int = config.DEFAULT_MAX_TOKENS,
        temperature: float = config.DEFAULT_TEMPERATURE
    ):
        """
        Stream LLM response for better UX (yields chunks).

        Args:
            system_prompt: System prompt
            user_content: User content
            max_tokens: Maximum tokens
            temperature: Sampling temperature

        Yields:
            Response chunks as they arrive
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True
            )

            for chunk in response:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            raise RuntimeError(f"Streaming failed: {e}")
