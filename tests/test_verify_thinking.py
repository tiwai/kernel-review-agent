#!/usr/bin/env python3
"""Tests for the verification-phase thinking overrides."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_integration.openai_client import OpenAIClient
from llm_integration.tool_enabled_client import ToolEnabledClient
from llm_integration.resilient_client import ResilientLLMClient


def make_client(cls=OpenAIClient, **kwargs):
    with mock.patch('llm_integration.openai_client.OpenAI'):
        return cls(**kwargs)


def payload(client):
    api_kwargs = {}
    client._apply_thinking(api_kwargs)
    return api_kwargs


class TestThinkingScope(unittest.TestCase):
    def test_no_override_configured(self):
        client = make_client(reasoning_effort="high")
        with client.thinking_scope(True):
            self.assertEqual(payload(client), {"reasoning_effort": "high"})

    def test_scope_applies_and_restores(self):
        client = make_client(
            reasoning_effort="high",
            verify_reasoning_effort="low",
            verify_chat_template_kwargs=True)
        self.assertEqual(payload(client), {"reasoning_effort": "high"})
        with client.thinking_scope(True):
            self.assertEqual(payload(client), {
                "reasoning_effort": "low",
                "extra_body": {"chat_template_kwargs": {"reasoning_effort": "low"}}})
        self.assertEqual(payload(client), {"reasoning_effort": "high"})

    def test_effort_only_without_toggle(self):
        client = make_client(verify_reasoning_effort="xhigh")
        with client.thinking_scope(True):
            self.assertEqual(payload(client), {"reasoning_effort": "xhigh"})

    def test_none_with_toggle_disables_thinking(self):
        client = make_client(reasoning_effort="high", verify_reasoning_effort="none",
                             verify_chat_template_kwargs=True)
        with client.thinking_scope(True):
            self.assertEqual(payload(client), {
                "reasoning_effort": "high",
                "extra_body": {"chat_template_kwargs": {"enable_thinking": False}}})

    def test_toggle_without_effort_is_noop(self):
        client = make_client(verify_chat_template_kwargs=True)
        with client.thinking_scope(True):
            self.assertEqual(payload(client), {})

    def test_scope_disabled(self):
        client = make_client(verify_reasoning_effort="low")
        with client.thinking_scope(False):
            self.assertEqual(payload(client), {})

    def test_scope_restored_on_exception(self):
        client = make_client(verify_reasoning_effort="low")
        with self.assertRaises(ValueError):
            with client.thinking_scope(True):
                raise ValueError
        self.assertEqual(payload(client), {})

    def test_tool_client_create(self):
        client = make_client(ToolEnabledClient, verify_reasoning_effort="none", verify_chat_template_kwargs=True)
        client.client.chat.completions.create.return_value = "resp"
        with client.thinking_scope(True):
            client._create([], 10, None)
        kwargs = client.client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["extra_body"], {"chat_template_kwargs": {"enable_thinking": False}})
        client._create([], 10, None)
        self.assertNotIn("extra_body", client.client.chat.completions.create.call_args.kwargs)

    def test_resilient_delegates(self):
        inner = make_client(verify_reasoning_effort="low")
        wrapper = ResilientLLMClient(inner, enable_reset=False)
        with wrapper.thinking_scope(True):
            self.assertEqual(payload(inner), {"reasoning_effort": "low"})
        self.assertEqual(payload(inner), {})


if __name__ == '__main__':
    unittest.main()
