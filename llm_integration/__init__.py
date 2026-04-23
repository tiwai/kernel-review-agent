"""LLM integration module for kernel review agent."""

from .base_client import LLMClient
from .openai_client import OpenAIClient
from .tool_enabled_client import ToolEnabledClient
from .client_factory import create_llm_client, get_provider_from_args

# Optional imports - only available if dependencies are installed
try:
    from .anthropic_client import AnthropicClient
except ImportError:
    AnthropicClient = None

try:
    from .anthropic_vertex_client import AnthropicVertexClient
except ImportError:
    AnthropicVertexClient = None

try:
    from .google_client import GoogleClient
except ImportError:
    GoogleClient = None

try:
    from .ollama_client import OllamaClient
except ImportError:
    OllamaClient = None

__all__ = [
    'LLMClient',
    'OpenAIClient',
    'ToolEnabledClient',
    'AnthropicClient',
    'AnthropicVertexClient',
    'GoogleClient',
    'OllamaClient',
    'create_llm_client',
    'get_provider_from_args',
]
