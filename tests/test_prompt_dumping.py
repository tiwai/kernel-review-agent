#!/usr/bin/env python3
"""Test that prompt dumping saves all calls with unique filenames."""

import os
import tempfile
import shutil
from llm_integration.anthropic_client import AnthropicClient
from llm_integration.openai_client import OpenAIClient


def test_anthropic_prompt_dumping():
    """Test that Anthropic client saves multiple prompts without overwriting."""
    with tempfile.TemporaryDirectory() as tmpdir:
        commit_dir = os.path.join(tmpdir, "commit-123")
        os.makedirs(commit_dir)

        # Create a minimal mock client without initializing the API client
        class MockAnthropicClient:
            def __init__(self):
                self.call_counter = 0
                self.dump_prompts = True
                self.dump_dir = tmpdir
                self.debug = False
                self.model = "test-model"

            # Import the methods we want to test
            _dump_prompt = AnthropicClient._dump_prompt
            _dump_response = AnthropicClient._dump_response

        client = MockAnthropicClient()

        # Simulate multiple calls with same stage name
        # This would have overwritten files before the fix
        prompts_dir = os.path.join(commit_dir, "prompts")

        # Manually simulate what would happen with 3 verification calls
        for i in range(3):
            client.call_counter += 1
            call_id = client.call_counter

            client._dump_prompt(
                call_id=call_id,
                system_prompt=f"System prompt {i}",
                messages=[{"role": "user", "content": f"User content {i}"}],
                max_tokens=1000,
                temperature=0.7,
                stage_name="verify",
                commit_output_dir=commit_dir
            )

            client._dump_response(
                call_id=call_id,
                response=f"Response {i}",
                stage_name="verify",
                commit_output_dir=commit_dir
            )

        # Check that all 3 files exist (not overwritten)
        prompt_files = sorted([f for f in os.listdir(prompts_dir) if f.endswith('-prompt.txt')])
        response_files = sorted([f for f in os.listdir(prompts_dir) if f.endswith('-response.txt')])

        print(f"Prompt files: {prompt_files}")
        print(f"Response files: {response_files}")

        assert len(prompt_files) == 3, f"Expected 3 prompt files, got {len(prompt_files)}"
        assert len(response_files) == 3, f"Expected 3 response files, got {len(response_files)}"

        # Check filenames include both stage name and call_id
        assert "verify-001-prompt.txt" in prompt_files
        assert "verify-002-prompt.txt" in prompt_files
        assert "verify-003-prompt.txt" in prompt_files

        print("✓ Anthropic client test passed: All prompts saved with unique filenames")


def test_openai_prompt_dumping():
    """Test that OpenAI client saves multiple prompts without overwriting."""
    with tempfile.TemporaryDirectory() as tmpdir:
        commit_dir = os.path.join(tmpdir, "commit-456")
        os.makedirs(commit_dir)

        # Create a minimal mock client without initializing the API client
        class MockOpenAIClient:
            def __init__(self):
                self.call_counter = 0
                self.dump_prompts = True
                self.dump_dir = tmpdir
                self.debug = False
                self.model = "test-model"
                self.reasoning_effort = None

            # Import the methods we want to test
            _dump_prompt = OpenAIClient._dump_prompt
            _dump_response = OpenAIClient._dump_response

        client = MockOpenAIClient()

        prompts_dir = os.path.join(commit_dir, "prompts")

        # Manually simulate what would happen with 3 verification calls
        for i in range(3):
            client.call_counter += 1
            call_id = client.call_counter

            client._dump_prompt(
                call_id=call_id,
                messages=[
                    {"role": "system", "content": f"System {i}"},
                    {"role": "user", "content": f"User {i}"}
                ],
                max_tokens=1000,
                temperature=0.7,
                stage_name="verify",
                commit_output_dir=commit_dir
            )

            client._dump_response(
                call_id=call_id,
                response=f"Response {i}",
                stage_name="verify",
                commit_output_dir=commit_dir
            )

        # Check that all 3 files exist (not overwritten)
        prompt_files = sorted([f for f in os.listdir(prompts_dir) if f.endswith('-prompt.txt')])
        response_files = sorted([f for f in os.listdir(prompts_dir) if f.endswith('-response.txt')])

        print(f"Prompt files: {prompt_files}")
        print(f"Response files: {response_files}")

        assert len(prompt_files) == 3, f"Expected 3 prompt files, got {len(prompt_files)}"
        assert len(response_files) == 3, f"Expected 3 response files, got {len(response_files)}"

        # Check filenames include both stage name and call_id
        assert "verify-001-prompt.txt" in prompt_files
        assert "verify-002-prompt.txt" in prompt_files
        assert "verify-003-prompt.txt" in prompt_files

        print("✓ OpenAI client test passed: All prompts saved with unique filenames")


if __name__ == "__main__":
    test_anthropic_prompt_dumping()
    test_openai_prompt_dumping()
    print("\n✓ All tests passed!")
