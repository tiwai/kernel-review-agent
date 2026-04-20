"""Abstract base class for LLM clients."""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import config


class LLMClient(ABC):
    """Abstract base class for LLM API clients."""

    def __init__(
        self,
        model: str = config.DEFAULT_MODEL,
        verbose: bool = False,
        debug: bool = False,
        dump_prompts: bool = False,
        dump_dir: str = config.DEBUG_DUMP_DIR
    ):
        """
        Initialize LLM client.

        Args:
            model: Model name to use
            verbose: Enable verbose output
            debug: Enable debug output
            dump_prompts: Dump prompts and responses to files
            dump_dir: Directory for prompt/response dumps
        """
        self.model = model
        self.verbose = verbose
        self.debug = debug
        self.dump_prompts = dump_prompts
        self.dump_dir = dump_dir
        self.call_counter = 0

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    def _get_provider_name(self) -> str:
        """Get the name of this LLM provider."""
        return self.__class__.__name__.replace('Client', '')
