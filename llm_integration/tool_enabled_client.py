"""OpenAI client with tool calling support."""

import json
import subprocess
from typing import List, Dict, Optional, Callable
from openai import OpenAI

from .openai_client import OpenAIClient
import config


class ToolEnabledClient(OpenAIClient):
    """OpenAI client with tool calling capability."""

    def __init__(self, git_dir: str = '.', **kwargs):
        """
        Initialize tool-enabled client.

        Args:
            git_dir: Git repository directory for tool execution
            **kwargs: Passed to OpenAIClient
        """
        super().__init__(**kwargs)
        self.git_dir = git_dir
        self.tools = self._define_tools()

    def _define_tools(self) -> List[Dict]:
        """Define available tools for LLM."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "git_show",
                    "description": "Read a file from a specific git commit",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "commit": {
                                "type": "string",
                                "description": "Git commit reference (e.g., 'HEAD', 'abc123')"
                            },
                            "path": {
                                "type": "string",
                                "description": "File path relative to git root"
                            }
                        },
                        "required": ["commit", "path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "git_grep",
                    "description": "Search for a pattern in the git repository",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "Pattern to search for"
                            },
                            "file_pattern": {
                                "type": "string",
                                "description": "Optional file pattern (e.g., '*.c')"
                            },
                            "context_lines": {
                                "type": "integer",
                                "description": "Context lines around matches (default: 0)"
                            }
                        },
                        "required": ["pattern"]
                    }
                }
            }
        ]

    def execute_tool(self, tool_name: str, arguments: str) -> str:
        """Execute a git tool and return result."""
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON arguments: {e}"

        if tool_name == "git_show":
            return self._git_show(args.get("commit"), args.get("path"))
        elif tool_name == "git_grep":
            return self._git_grep(
                args.get("pattern"),
                args.get("file_pattern"),
                args.get("context_lines", 0)
            )
        else:
            return f"Error: Unknown tool '{tool_name}'"

    def _git_show(self, commit: str, path: str) -> str:
        """Execute git show."""
        if not commit or not path:
            return "Error: Both commit and path are required"

        try:
            result = subprocess.run(
                ["git", "-C", self.git_dir, "show", f"{commit}:{path}"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                content = result.stdout
                if len(content) > 8000:
                    return content[:8000] + f"\n... (truncated from {len(content)} chars)"
                return content
            else:
                return f"Error: {result.stderr.strip()}"
        except subprocess.TimeoutExpired:
            return "Error: git show timed out"
        except Exception as e:
            return f"Error: {e}"

    def _git_grep(self, pattern: str, file_pattern: Optional[str], context_lines: int) -> str:
        """Execute git grep."""
        if not pattern:
            return "Error: Pattern is required"

        try:
            cmd = ["git", "-C", self.git_dir, "grep", "-n"]

            if context_lines > 0:
                cmd.extend(["-C", str(context_lines)])

            cmd.append(pattern)

            if file_pattern:
                cmd.extend(["--", file_pattern])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                lines = result.stdout.split('\n')
                if len(lines) > 30:
                    return '\n'.join(lines[:30]) + f"\n... ({len(lines)-30} more matches)"
                return result.stdout
            elif result.returncode == 1:
                return "No matches found"
            else:
                return f"Error: {result.stderr.strip()}"
        except subprocess.TimeoutExpired:
            return "Error: git grep timed out"
        except Exception as e:
            return f"Error: {e}"

    def analyze_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        max_iterations: int = 10,
        max_tokens: int = config.DEFAULT_MAX_TOKENS,
        temperature: Optional[float] = None
    ) -> str:
        """
        Analyze with tool calling enabled.

        Args:
            system_prompt: System instructions
            user_prompt: User query/task
            max_iterations: Maximum tool calling iterations
            max_tokens: Maximum tokens per response
            temperature: Sampling temperature

        Returns:
            Final LLM response after all tool calls
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        for iteration in range(max_iterations):
            if self.debug:
                print(f"[DEBUG] Tool-calling iteration {iteration + 1}/{max_iterations}")

            # Build API kwargs
            api_kwargs = {
                "model": self.model,
                "messages": messages,
                "tools": self.tools,
                "max_tokens": max_tokens,
                "stream": False
            }
            if temperature is not None:
                api_kwargs["temperature"] = temperature

            # Call LLM
            response = self.client.chat.completions.create(**api_kwargs)

            message = response.choices[0].message
            finish_reason = response.choices[0].finish_reason

            # Add assistant message to history
            assistant_msg = {"role": "assistant", "content": message.content or ""}

            if message.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    } for tc in message.tool_calls
                ]

            messages.append(assistant_msg)

            # Process tool calls
            if message.tool_calls:
                if self.debug:
                    print(f"[DEBUG] LLM called {len(message.tool_calls)} tool(s)")

                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = tool_call.function.arguments

                    if self.debug:
                        print(f"[DEBUG]   Tool: {tool_name}({tool_args[:100]}...)")

                    # Execute tool
                    result = self.execute_tool(tool_name, tool_args)

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })

                    if self.debug:
                        print(f"[DEBUG]   Result: {len(result)} chars")

                # Continue loop to process tool results
                continue

            # No more tool calls - done
            if self.debug:
                print(f"[DEBUG] Tool calling finished (reason: {finish_reason})")

            return message.content or ""

        # Max iterations reached
        if self.verbose:
            print(f"[WARNING] Tool calling reached max iterations ({max_iterations})")

        return messages[-1].get("content", "(incomplete)")
