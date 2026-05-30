"""Unit tests for ResilientLLMClient and error detection."""

import unittest
from unittest.mock import Mock, patch, call
from llm_integration.resilient_client import ResilientLLMClient
from llm_integration.error_detector import is_fatal_host_error
from llm_integration.base_client import LLMClient


class MockLLMClient(LLMClient):
    """Mock LLM client for testing."""

    def __init__(self, model='test-model', **kwargs):
        super().__init__(model=model, **kwargs)
        self.call_count = 0
        self.responses = []
        self.errors = []

    def analyze_code(self, system_prompt, user_content, max_tokens=1000, temperature=None):
        """Mock analyze_code that can be configured to fail or succeed."""
        self.call_count += 1

        # If errors configured, raise them in sequence
        if self.errors and len(self.errors) >= self.call_count:
            error = self.errors[self.call_count - 1]
            if error:
                raise error

        # Otherwise return success
        if self.responses and len(self.responses) >= self.call_count:
            return self.responses[self.call_count - 1]

        return "OK"

    def analyze_with_context(self, messages, max_tokens=1000, temperature=None):
        """Mock analyze_with_context."""
        return self.analyze_code("system", "user", max_tokens, temperature)


class TestErrorDetection(unittest.TestCase):
    """Test error detection logic."""

    def test_proxy_error_detected(self):
        """Test that proxy errors are detected as fatal."""
        error = RuntimeError("proxy error: Could not establish connection")
        self.assertTrue(is_fatal_host_error(error))

    def test_connection_error_detected(self):
        """Test that connection errors are detected as fatal."""
        error = RuntimeError("could not establish connection")
        self.assertTrue(is_fatal_host_error(error))

    def test_internal_server_error_detected(self):
        """Test that InternalServerError is detected as fatal."""
        error = RuntimeError("InternalServerError: Error code: 500")
        self.assertTrue(is_fatal_host_error(error))

    def test_502_error_detected(self):
        """Test that HTTP 502 errors are detected as fatal."""
        error = RuntimeError("Error code: 502 - Bad Gateway")
        self.assertTrue(is_fatal_host_error(error))

    def test_503_error_detected(self):
        """Test that HTTP 503 errors are detected as fatal."""
        error = RuntimeError("Error code: 503 - Service Unavailable")
        self.assertTrue(is_fatal_host_error(error))

    def test_504_error_detected(self):
        """Test that HTTP 504 errors are detected as fatal."""
        error = RuntimeError("Error code: 504 - Gateway Timeout")
        self.assertTrue(is_fatal_host_error(error))

    def test_connection_refused_detected(self):
        """Test that connection refused is detected as fatal."""
        error = RuntimeError("Connection refused")
        self.assertTrue(is_fatal_host_error(error))

    def test_timeout_not_fatal(self):
        """Test that timeout errors are NOT detected as fatal."""
        error = RuntimeError("Request timed out after 300s")
        self.assertFalse(is_fatal_host_error(error))

    def test_generic_error_not_fatal(self):
        """Test that generic errors are NOT detected as fatal."""
        error = RuntimeError("Something went wrong")
        self.assertFalse(is_fatal_host_error(error))

    def test_value_error_not_fatal(self):
        """Test that non-RuntimeError exceptions are NOT detected as fatal."""
        error = ValueError("Invalid input")
        self.assertFalse(is_fatal_host_error(error))


class TestResilientClient(unittest.TestCase):
    """Test ResilientLLMClient behavior."""

    def test_normal_operation_no_reset(self):
        """Test that normal operations pass through without overhead."""
        mock_client = MockLLMClient()
        mock_client.responses = ["Response 1"]

        resilient = ResilientLLMClient(
            wrapped_client=mock_client,
            enable_reset=True,
            provider='openai'
        )

        result = resilient.analyze_code("system", "user")

        self.assertEqual(result, "Response 1")
        self.assertEqual(mock_client.call_count, 1)

    def test_fatal_error_triggers_reset(self):
        """Test that fatal errors trigger reset and retry."""
        mock_client = MockLLMClient()
        # First call fails with proxy error, second succeeds
        mock_client.errors = [
            RuntimeError("proxy error: Could not establish connection"),
            None
        ]
        mock_client.responses = [None, "Success after reset"]

        with patch('llm_integration.client_factory.create_llm_client') as mock_factory:
            # Mock the temp client used for reset
            temp_client = MockLLMClient(model='gpt-3.5-turbo')
            temp_client.responses = ["OK"]
            mock_factory.return_value = temp_client

            resilient = ResilientLLMClient(
                wrapped_client=mock_client,
                enable_reset=True,
                provider='openai'
            )

            result = resilient.analyze_code("system", "user")

            # Should have succeeded after reset
            self.assertEqual(result, "Success after reset")
            # Original client called twice (fail, then succeed)
            self.assertEqual(mock_client.call_count, 2)
            # Temp client created for reset
            mock_factory.assert_called_once()

    def test_non_fatal_error_bypasses_reset(self):
        """Test that non-fatal errors don't trigger reset."""
        mock_client = MockLLMClient()
        mock_client.errors = [RuntimeError("Request timed out")]

        resilient = ResilientLLMClient(
            wrapped_client=mock_client,
            enable_reset=True,
            provider='openai'
        )

        with self.assertRaises(RuntimeError) as ctx:
            resilient.analyze_code("system", "user")

        # Error should propagate immediately
        self.assertIn("timed out", str(ctx.exception))
        # Only one call attempt
        self.assertEqual(mock_client.call_count, 1)

    def test_reset_disabled(self):
        """Test that reset is disabled when enable_reset=False."""
        mock_client = MockLLMClient()
        mock_client.errors = [RuntimeError("proxy error")]

        resilient = ResilientLLMClient(
            wrapped_client=mock_client,
            enable_reset=False,
            provider='openai'
        )

        with self.assertRaises(RuntimeError) as ctx:
            resilient.analyze_code("system", "user")

        # Error should propagate immediately
        self.assertIn("proxy error", str(ctx.exception))
        # Only one call attempt
        self.assertEqual(mock_client.call_count, 1)

    def test_max_attempts_exhausted(self):
        """Test that errors are raised after max reset attempts."""
        mock_client = MockLLMClient()
        # All calls fail with proxy error
        mock_client.errors = [
            RuntimeError("proxy error"),
            RuntimeError("proxy error"),
            RuntimeError("proxy error")
        ]

        with patch('llm_integration.client_factory.create_llm_client') as mock_factory:
            temp_client = MockLLMClient(model='gpt-3.5-turbo')
            temp_client.responses = ["OK"]
            mock_factory.return_value = temp_client

            resilient = ResilientLLMClient(
                wrapped_client=mock_client,
                enable_reset=True,
                max_reset_attempts=2,
                provider='openai'
            )

            with self.assertRaises(RuntimeError) as ctx:
                resilient.analyze_code("system", "user")

            # Error should be raised after 2 attempts
            self.assertIn("proxy error", str(ctx.exception))
            # Original client called twice (initial + 1 retry after reset)
            self.assertEqual(mock_client.call_count, 2)
            # Temp client created once for the one reset before giving up
            self.assertEqual(mock_factory.call_count, 1)

    def test_fallback_model_selection_openai(self):
        """Test correct default fallback model for OpenAI."""
        mock_client = MockLLMClient()

        resilient = ResilientLLMClient(
            wrapped_client=mock_client,
            enable_reset=True,
            provider='openai'
        )

        self.assertEqual(resilient.fallback_model, 'gpt-3.5-turbo')

    def test_fallback_model_selection_anthropic(self):
        """Test correct default fallback model for Anthropic."""
        mock_client = MockLLMClient()

        resilient = ResilientLLMClient(
            wrapped_client=mock_client,
            enable_reset=True,
            provider='anthropic'
        )

        self.assertEqual(resilient.fallback_model, 'claude-3-haiku-20240307')

    def test_fallback_model_selection_google(self):
        """Test correct default fallback model for Google."""
        mock_client = MockLLMClient()

        resilient = ResilientLLMClient(
            wrapped_client=mock_client,
            enable_reset=True,
            provider='google'
        )

        self.assertEqual(resilient.fallback_model, 'gemini-1.5-flash')

    def test_fallback_model_selection_ollama(self):
        """Test correct default fallback model for Ollama."""
        mock_client = MockLLMClient()

        resilient = ResilientLLMClient(
            wrapped_client=mock_client,
            enable_reset=True,
            provider='ollama'
        )

        self.assertEqual(resilient.fallback_model, 'llama2')

    def test_custom_fallback_model(self):
        """Test that custom fallback model is used when specified."""
        mock_client = MockLLMClient()

        resilient = ResilientLLMClient(
            wrapped_client=mock_client,
            enable_reset=True,
            fallback_model='custom-model',
            provider='openai'
        )

        self.assertEqual(resilient.fallback_model, 'custom-model')

    def test_token_usage_sync(self):
        """Test that token usage is synced from wrapped client."""
        mock_client = MockLLMClient()
        mock_client.responses = ["Response"]
        mock_client.total_prompt_tokens = 100
        mock_client.total_completion_tokens = 50
        mock_client.total_tokens = 150

        resilient = ResilientLLMClient(
            wrapped_client=mock_client,
            enable_reset=True,
            provider='openai'
        )

        result = resilient.analyze_code("system", "user")

        usage = resilient.get_token_usage()
        self.assertEqual(usage['prompt_tokens'], 100)
        self.assertEqual(usage['completion_tokens'], 50)
        self.assertEqual(usage['total_tokens'], 150)

    def test_analyze_with_context(self):
        """Test that analyze_with_context is also wrapped."""
        mock_client = MockLLMClient()
        mock_client.responses = ["Context response"]

        resilient = ResilientLLMClient(
            wrapped_client=mock_client,
            enable_reset=True,
            provider='openai'
        )

        result = resilient.analyze_with_context(
            [{"role": "system", "content": "test"}]
        )

        self.assertEqual(result, "Context response")
        self.assertEqual(mock_client.call_count, 1)


if __name__ == '__main__':
    unittest.main()
