"""OpenAI client with tool calling support."""

import json
import re
import subprocess
from typing import List, Dict, Optional, Tuple
from openai import OpenAI

from .openai_client import OpenAIClient
from git_integration import extract_function
import config


# Default / maximum number of lines returned by a single git_show call
SHOW_DEFAULT_LINES = 250
SHOW_MAX_LINES = 400
# Maximum lines returned by a single get_function call
FUNCTION_MAX_LINES = 500
# Maximum output size of a single git_grep call
GREP_MAX_CHARS = 6000
GREP_MAX_CONTEXT = 10
# Consecutive tool calls without new information before nudging the model to conclude
MAX_UNPRODUCTIVE_CALLS = 3
# Duplicate calls tolerated before tools are withdrawn and a final answer is forced
MAX_DUPLICATE_CALLS = 5

TOOL_USAGE_GUIDE = """

TOOL USAGE RULES:
- All tools read the source tree AT THE COMMIT UNDER REVIEW (i.e. after the change) unless
  you pass another 'commit'. Use get_function(version="before") to see the code before the change.
- To read a function, call get_function: it returns the whole body with line numbers in one call.
- git_show returns at most 400 lines per call. Use start_line/end_line to read a specific region.
- git_grep output is size-limited. Narrow it with file_pattern or a more specific pattern;
  increasing context_lines will not show more.
- Issue several independent tool calls in a single turn when possible.
- Never repeat a call with the same arguments: the result will not change.
- Code already included in the prompt does not need to be fetched again.
- Stop calling tools as soon as you have enough evidence, and write your answer."""

FINAL_ANSWER_PROMPT = (
    "The tool-call budget is exhausted; no more tools are available. "
    "Based on the information you have gathered so far, give your final answer now, "
    "in exactly the output format requested at the beginning. Do not call any tools; "
    "reply with plain text only."
)

TRUNCATED_ANSWER_PROMPT = (
    "Your previous response was cut off by the output length limit. "
    "Do not repeat the analysis; give only your final answer now, briefly, "
    "in exactly the output format requested at the beginning. Do not call any tools; "
    "reply with plain text only."
)

LOOP_STOP_PROMPT = (
    "You keep repeating tool calls that return no new information, so tools are no longer "
    "available. Based on the information you have gathered so far, give your final answer "
    "now, in exactly the output format requested at the beginning. Do not call any "
    "tools; reply with plain text only."
)

CONCLUDE_NUDGE = (
    "[NOTE: Your last tool calls returned no new information. Stop investigating and "
    "give your final answer now in the requested format, based on what you already know.]"
)


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
        commit_param = {
            "type": "string",
            "description": "Git commit reference. Defaults to the commit under review; "
                           "omit it unless you really need another revision."
        }
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_function",
                    "description": "Return the complete definition of a C function (with line numbers). "
                                   "Preferred way to read code.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Function name"
                            },
                            "path": {
                                "type": "string",
                                "description": "File path relative to git root. If omitted, the "
                                               "definition is searched for in the whole tree."
                            },
                            "version": {
                                "type": "string",
                                "enum": ["after", "before"],
                                "description": "'after' (default): code after the commit under review; "
                                               "'before': code before it (parent commit)"
                            },
                            "commit": commit_param
                        },
                        "required": ["name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "git_show",
                    "description": f"Read lines of a file with line numbers (at most {SHOW_MAX_LINES} "
                                   f"lines per call; default: first {SHOW_DEFAULT_LINES} lines)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path relative to git root"
                            },
                            "start_line": {
                                "type": "integer",
                                "description": "First line to show (1-based, default: 1)"
                            },
                            "end_line": {
                                "type": "integer",
                                "description": "Last line to show (inclusive)"
                            },
                            "commit": commit_param
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "git_grep",
                    "description": "Search for a pattern (basic regex) in the source tree; "
                                   "returns file:line:text matches",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "Pattern to search for"
                            },
                            "file_pattern": {
                                "type": "string",
                                "description": "Optional path or glob to limit the search "
                                               "(e.g., 'drivers/dma/at_hdmac.c', '*.h')"
                            },
                            "context_lines": {
                                "type": "integer",
                                "description": f"Context lines around matches (default: 0, max: {GREP_MAX_CONTEXT})"
                            },
                            "commit": commit_param
                        },
                        "required": ["pattern"]
                    }
                }
            }
        ]

    @staticmethod
    def _to_int(value) -> Optional[int]:
        """Convert a tool argument to int (models sometimes pass strings)."""
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _prepare_call(self, tool_name: str, arguments: str,
                      commit_ref: str) -> Tuple[Optional[Dict], Optional[str]]:
        """
        Parse and normalize tool arguments.

        Normalized arguments have all defaults filled in, so that calls which
        would produce identical output also compare equal.

        Returns:
            (normalized args, None) or (None, error message)
        """
        try:
            args = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError as e:
            return None, f"Error: Invalid JSON arguments: {e}"
        if not isinstance(args, dict):
            return None, "Error: Arguments must be a JSON object"

        commit = args.get("commit") or commit_ref

        if tool_name == "git_show":
            path = args.get("path")
            if not path:
                return None, "Error: path is required"
            start = max(self._to_int(args.get("start_line")) or 1, 1)
            end = self._to_int(args.get("end_line"))
            if end is None or end < start:
                end = start + SHOW_DEFAULT_LINES - 1
            end = min(end, start + SHOW_MAX_LINES - 1)
            return {"commit": commit, "path": path, "start_line": start, "end_line": end}, None

        if tool_name == "git_grep":
            pattern = args.get("pattern")
            if not pattern:
                return None, "Error: pattern is required"
            context = self._to_int(args.get("context_lines")) or 0
            return {
                "commit": commit,
                "pattern": pattern,
                "file_pattern": args.get("file_pattern") or None,
                "context_lines": min(max(context, 0), GREP_MAX_CONTEXT),
                "context_capped": context > GREP_MAX_CONTEXT,
            }, None

        if tool_name == "get_function":
            name = args.get("name")
            if not name:
                return None, "Error: name is required"
            name = name.strip().rstrip('()').strip()
            version = args.get("version") or "after"
            if version not in ("after", "before"):
                version = "after"
            return {
                "commit": commit,
                "name": name,
                "path": args.get("path") or None,
                "version": version,
            }, None

        return None, f"Error: Unknown tool '{tool_name}'"

    @staticmethod
    def _call_key(tool_name: str, args: Dict) -> str:
        """Key identifying calls with identical output."""
        key_args = {k: v for k, v in args.items() if k != "context_capped"}
        return tool_name + json.dumps(key_args, sort_keys=True)

    def _run_tool(self, tool_name: str, args: Dict) -> str:
        """Run a tool with normalized arguments."""
        if tool_name == "git_show":
            return self._git_show(args["commit"], args["path"],
                                  args["start_line"], args["end_line"])
        if tool_name == "git_grep":
            return self._git_grep(args["pattern"], args["file_pattern"],
                                  args["context_lines"], args["commit"],
                                  args["context_capped"])
        if tool_name == "get_function":
            return self._get_function(args["name"], args["path"],
                                      args["commit"], args["version"])
        return f"Error: Unknown tool '{tool_name}'"

    def execute_tool(self, tool_name: str, arguments: str, commit_ref: str = "HEAD") -> str:
        """Execute a git tool and return result."""
        args, error = self._prepare_call(tool_name, arguments, commit_ref)
        if error:
            return error
        return self._run_tool(tool_name, args)

    def _read_file(self, commit: str, path: str) -> Tuple[Optional[str], Optional[str]]:
        """Read a file at a commit. Returns (content, None) or (None, error)."""
        try:
            result = subprocess.run(
                ["git", "-C", self.git_dir, "show", f"{commit}:{path}"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=30
            )
        except subprocess.TimeoutExpired:
            return None, "Error: git show timed out"
        except Exception as e:
            return None, f"Error: {e}"
        if result.returncode != 0:
            return None, f"Error: {result.stderr.strip()}"
        return result.stdout, None

    @staticmethod
    def _number_lines(lines: List[str], first: int) -> str:
        return '\n'.join(f"{first + i}\t{line}" for i, line in enumerate(lines))

    def _git_show(self, commit: str, path: str, start: int, end: int) -> str:
        """Show a range of lines of a file at a commit."""
        content, error = self._read_file(commit, path)
        if error:
            return error

        lines = content.split('\n')
        if lines and lines[-1] == '':
            lines.pop()
        total = len(lines)
        if start > total:
            return f"Error: {path} has only {total} lines"
        end = min(end, total)

        out = f"{path} @ {commit[:12]} (lines {start}-{end} of {total}):\n"
        out += self._number_lines(lines[start - 1:end], start)
        if end < total:
            out += (f"\n[showing lines {start}-{end} of {total}; call git_show with "
                    f"start_line={end + 1} to read further, or use get_function to read "
                    f"a specific function]")
        return out

    def _git_grep(self, pattern: str, file_pattern: Optional[str], context_lines: int,
                  commit: str, context_capped: bool = False) -> str:
        """Execute git grep on the tree of the given commit."""
        try:
            cmd = ["git", "-C", self.git_dir, "grep", "-n", "-I"]

            if context_lines > 0:
                cmd.extend(["-C", str(context_lines)])

            cmd.extend(["-e", pattern, commit])

            if file_pattern:
                cmd.extend(["--", file_pattern])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=60
            )

            if result.returncode == 1:
                where = f" in {file_pattern}" if file_pattern else ""
                return f"No matches found for '{pattern}'{where} at {commit[:12]}"
            if result.returncode != 0:
                return f"Error: {result.stderr.strip()}"

            # Strip the "<commit>:" prefix git adds when grepping a tree
            prefix = f"{commit}:"
            lines = [l[len(prefix):] if l.startswith(prefix) else l
                     for l in result.stdout.rstrip('\n').split('\n')]

            out_lines = []
            size = 0
            for line in lines:
                if size + len(line) + 1 > GREP_MAX_CHARS:
                    break
                out_lines.append(line)
                size += len(line) + 1

            out = '\n'.join(out_lines)
            if context_capped:
                out = f"[context_lines capped at {GREP_MAX_CONTEXT}]\n" + out
            if len(out_lines) < len(lines):
                out += (f"\n[output truncated: showing {len(out_lines)} of {len(lines)} lines. "
                        f"Narrow the search with file_pattern or a more specific pattern, or "
                        f"read the code with get_function / git_show start_line. Increasing "
                        f"context_lines will not show more.]")
            return out
        except subprocess.TimeoutExpired:
            return "Error: git grep timed out; narrow the search with file_pattern"
        except Exception as e:
            return f"Error: {e}"

    def _find_function_files(self, name: str, commit: str) -> List[str]:
        """Find files likely containing the definition of a function."""
        try:
            result = subprocess.run(
                ["git", "-C", self.git_dir, "grep", "-n", "-I", "-E",
                 rf"^([A-Za-z_].*[^A-Za-z0-9_])?{re.escape(name)}[[:space:]]*\(", commit,
                 "--", "*.c", "*.h"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=60
            )
        except (subprocess.TimeoutExpired, OSError):
            return []

        prefix = f"{commit}:"
        files = []
        for line in result.stdout.split('\n'):
            if line.startswith(prefix):
                line = line[len(prefix):]
            parts = line.split(':', 2)
            if len(parts) < 3 or parts[2].rstrip().endswith(';'):
                continue
            if parts[0] not in files:
                files.append(parts[0])
        # Prefer .c files over headers
        return sorted(files, key=lambda f: not f.endswith('.c'))

    def _get_function(self, name: str, path: Optional[str], commit: str, version: str) -> str:
        """Return the full definition of a function at a commit."""
        ref = f"{commit}^" if version == "before" else commit
        ref_desc = f"{commit[:12]}^ (before the change)" if version == "before" else commit[:12]

        hint = " (it may have been added by this commit)" if version == "before" else ""
        candidates = [path] if path else self._find_function_files(name, ref)
        if not candidates:
            return (f"Function {name}() not found at {ref_desc}{hint}. "
                    f"Do not retry with the same name; try git_grep with a different pattern.")

        for file_path in candidates[:5]:
            content, error = self._read_file(ref, file_path)
            if error:
                if path:
                    return error
                continue
            found = extract_function(content, name)
            if not found:
                continue

            start, text = found
            lines = text.split('\n')
            truncated = len(lines) > FUNCTION_MAX_LINES
            lines = lines[:FUNCTION_MAX_LINES]
            end = start + len(lines) - 1
            out = f"{name}() in {file_path} @ {ref_desc} (lines {start}-{end}):\n"
            out += self._number_lines(lines, start)
            if truncated:
                out += (f"\n[function truncated at {FUNCTION_MAX_LINES} lines; use git_show "
                        f"with start_line={end + 1} for the rest]")
            others = [f for f in candidates if f != file_path]
            if not path and others:
                out += f"\n[other files with a possible definition: {', '.join(others[:5])}]"
            return out

        where = f"in {path}" if path else f"in {', '.join(candidates[:5])}"
        return f"Function {name}() not found {where} at {ref_desc}{hint}."

    @staticmethod
    def _is_unproductive(result: str) -> bool:
        """Whether a tool result carries no new information."""
        return result.startswith(("Error:", "No matches found", "[Duplicate")) or \
            " not found " in result.split('\n', 1)[0]

    def _create(self, messages: List[Dict], max_tokens: int, temperature: Optional[float],
                use_tools: bool = True, tool_choice: Optional[str] = None):
        """Issue one chat completion request."""
        api_kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": False
        }
        if use_tools:
            api_kwargs["tools"] = self.tools
            if tool_choice:
                api_kwargs["tool_choice"] = tool_choice
        if temperature is not None:
            api_kwargs["temperature"] = temperature
        if self.reasoning_effort is not None:
            api_kwargs["reasoning_effort"] = self.reasoning_effort
        return self.client.chat.completions.create(**api_kwargs)

    def analyze_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        max_iterations: int = 10,
        max_tokens: int = config.DEFAULT_MAX_TOKENS,
        temperature: Optional[float] = None,
        commit_ref: Optional[str] = None
    ) -> str:
        """
        Analyze with tool calling enabled.

        Args:
            system_prompt: System instructions
            user_prompt: User query/task
            max_iterations: Maximum tool calling iterations
            max_tokens: Maximum tokens per response
            temperature: Sampling temperature
            commit_ref: Commit under review; tools read this tree by default

        Returns:
            Final LLM response after all tool calls
        """
        commit_ref = commit_ref or "HEAD"
        messages = [
            {"role": "system", "content": system_prompt + TOOL_USAGE_GUIDE},
            {"role": "user", "content": user_prompt}
        ]

        seen_calls = {}     # call key -> call number
        num_calls = 0
        num_duplicates = 0
        unproductive = 0
        nudged = False
        last_content = ""

        for iteration in range(max_iterations):
            if self.debug:
                print(f"Tool-calling iteration {iteration + 1}/{max_iterations}")

            response = self._create(messages, max_tokens, temperature)

            message = response.choices[0].message
            finish_reason = response.choices[0].finish_reason
            if message.content:
                last_content = message.content

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

            # No more tool calls - done
            if not message.tool_calls:
                if self.debug:
                    print(f"Tool calling finished (reason: {finish_reason}); "
                          f"{num_calls} call(s), {num_duplicates} duplicate(s)")
                if finish_reason == "length":
                    # Answer was cut off (e.g. reasoning used up max_tokens); ask once
                    # more for a concise answer instead of losing the investigation
                    if self.verbose:
                        print("[WARNING] Final answer truncated by max_tokens; requesting concise answer")
                    return self._final_answer(messages, TRUNCATED_ANSWER_PROMPT, max_tokens,
                                              temperature, message.content or "")
                return message.content or ""

            # Process tool calls
            if self.debug:
                print(f"LLM called {len(message.tool_calls)} tool(s)")

            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = tool_call.function.arguments or ""
                num_calls += 1

                args, error = self._prepare_call(tool_name, tool_args, commit_ref)
                duplicate = False
                if error:
                    result = error
                else:
                    key = self._call_key(tool_name, args)
                    if key in seen_calls:
                        duplicate = True
                        num_duplicates += 1
                        result = (f"[Duplicate of tool call #{seen_calls[key]}: the arguments are "
                                  f"identical, so the result is unchanged and already shown above. "
                                  f"Use that result or give your final answer.]")
                    else:
                        seen_calls[key] = num_calls
                        result = self._run_tool(tool_name, args)

                if self.debug:
                    dup = " (duplicate)" if duplicate else ""
                    print(f"  Tool: {tool_name}({tool_args[:100]}...){dup}")

                if self._is_unproductive(result):
                    unproductive += 1
                else:
                    unproductive = 0

                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })

                if self.debug:
                    print(f"  Result: {len(result)} chars")

            # Append hints to the last tool result rather than adding a user
            # message, as some chat templates reject user turns after tool turns
            notes = []
            remaining = max_iterations - iteration - 1
            if 0 < remaining <= max(2, max_iterations // 5):
                notes.append(f"[{remaining} tool-call round(s) remaining; wrap up your investigation.]")
            if unproductive >= MAX_UNPRODUCTIVE_CALLS or num_duplicates >= MAX_DUPLICATE_CALLS:
                if nudged or num_duplicates >= MAX_DUPLICATE_CALLS:
                    # The model is looping; more rounds would add nothing
                    if self.verbose:
                        print(f"[WARNING] Model is repeating tool calls ({num_calls} call(s), "
                              f"{num_duplicates} duplicate(s)); requesting final answer")
                    return self._final_answer(messages, LOOP_STOP_PROMPT, max_tokens,
                                              temperature, last_content or "(incomplete)")
                notes.append(CONCLUDE_NUDGE)
                nudged = True
                unproductive = 0
            if notes:
                messages[-1]["content"] += "\n\n" + "\n".join(notes)

        # Max iterations reached: ask for a final answer without tools, so the
        # information gathered so far is not lost
        if self.verbose:
            print(f"[WARNING] Tool calling reached max iterations ({max_iterations}); "
                  f"{num_calls} call(s), {num_duplicates} duplicate(s). Requesting final answer")

        return self._final_answer(messages, FINAL_ANSWER_PROMPT, max_tokens,
                                  temperature, last_content or "(incomplete)")

    def _final_answer(self, messages: List[Dict], prompt: str, max_tokens: int,
                      temperature: Optional[float], fallback: str) -> str:
        """Request a final answer without tool calls; return fallback on failure."""
        messages.append({"role": "user", "content": prompt})
        # Keep the tool definitions but forbid calling them first: some servers
        # (llama.cpp) fail to parse the reply when tools vanish from a
        # conversation that used them.  Fall back to omitting tools entirely.
        # As a last resort, flatten the tool exchange into plain text so that
        # the model has no tool-call structure left to imitate.
        attempts = [
            (messages, {"tool_choice": "none"}),
            (messages, {"use_tools": False}),
            (self._flatten_messages(messages), {"use_tools": False}),
        ]
        for msgs, kwargs in attempts:
            try:
                response = self._create(msgs, max_tokens, temperature, **kwargs)
                content = response.choices[0].message.content
                if content:
                    return content
            except Exception as e:
                if self.debug:
                    print(f"Final answer request failed: {e}")
        return fallback

    @staticmethod
    def _flatten_messages(messages: List[Dict]) -> List[Dict]:
        """Convert a tool-calling conversation into a plain system + user prompt."""
        system = messages[0]["content"].replace(TOOL_USAGE_GUIDE, "")
        task = messages[1]["content"]
        calls = {}
        parts = []
        for msg in messages[2:-1]:
            if msg["role"] == "assistant":
                if msg.get("content"):
                    parts.append(f"[Your notes]\n{msg['content']}")
                for tc in msg.get("tool_calls", []):
                    calls[tc["id"]] = f"{tc['function']['name']}({tc['function']['arguments']})"
            elif msg["role"] == "tool":
                call = calls.get(msg.get("tool_call_id"), "tool call")
                parts.append(f"[{call}]\n{msg['content']}")
        user = (f"{task}\n\n=== RESULTS OF YOUR CODE INVESTIGATION SO FAR ===\n\n"
                + "\n\n".join(parts)
                + f"\n\n=== END OF INVESTIGATION ===\n\n{messages[-1]['content']}")
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]
