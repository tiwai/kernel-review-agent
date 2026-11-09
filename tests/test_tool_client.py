"""Unit tests for ToolEnabledClient tools and tool-calling loop."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from llm_integration.tool_enabled_client import (
    ToolEnabledClient, FINAL_ANSWER_PROMPT, LOOP_STOP_PROMPT
)
from git_integration import extract_function, git_ref_for_commit


OLD_SRC = """#include <linux/foo.h>

static int helper(int x)
{
\treturn x + 1;
}

int main_func(void)
{
\treturn helper(1);
}
"""

NEW_SRC = """#include <linux/foo.h>

static int helper(int x)
{
\treturn x + 1;
}

static void
new_cleanup(int y)
{
\tif (y) {
\t\thelper(y);
\t}
}

int main_func(void)
{
\tnew_cleanup(0);
\treturn helper(1);
}
""" + "".join(f"/* filler {i} */\n" for i in range(600))


def git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), check=True,
                          capture_output=True, text=True).stdout.strip()


def make_client(git_dir):
    client = ToolEnabledClient.__new__(ToolEnabledClient)
    client.git_dir = git_dir
    client.tools = client._define_tools()
    client.model = "test"
    client.reasoning_effort = None
    client.verbose = False
    client.debug = False
    return client


class TestSourceUtils(unittest.TestCase):

    def test_git_ref_for_commit(self):
        self.assertEqual(git_ref_for_commit("abc123"), "abc123")
        self.assertEqual(git_ref_for_commit("fix.patch"), "HEAD")

    def test_extract_function_skips_calls_and_prototypes(self):
        src = "int foo(int a);\n\nvoid bar(void)\n{\n\tfoo(1);\n}\n\nint\nfoo(int a)\n{\n\treturn a;\n}\n"
        start, text = extract_function(src, "foo")
        self.assertEqual(start, 8)
        self.assertTrue(text.startswith("int\nfoo(int a)"))
        self.assertTrue(text.endswith("}"))


class TestTools(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.repo = tempfile.mkdtemp()
        git(cls.repo, "init", "-q")
        git(cls.repo, "config", "user.email", "t@example.com")
        git(cls.repo, "config", "user.name", "Test")
        path = os.path.join(cls.repo, "drv.c")
        with open(path, "w") as f:
            f.write(OLD_SRC)
        git(cls.repo, "add", ".")
        git(cls.repo, "commit", "-q", "-m", "old")
        with open(path, "w") as f:
            f.write(NEW_SRC)
        git(cls.repo, "commit", "-q", "-am", "new")
        cls.new_sha = git(cls.repo, "rev-parse", "HEAD")
        # Move the working tree away, as on a reviewer's machine
        git(cls.repo, "checkout", "-q", "HEAD^")
        cls.client = make_client(cls.repo)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.repo)

    def run_tool(self, tool, **args):
        return self.client.execute_tool(tool, json.dumps(args), self.new_sha)

    def test_grep_uses_commit_tree(self):
        out = self.run_tool("git_grep", pattern="new_cleanup")
        self.assertIn("drv.c:9:new_cleanup(int y)", out)
        self.assertNotIn(self.new_sha, out)

    def test_grep_no_match(self):
        out = self.run_tool("git_grep", pattern="does_not_exist")
        self.assertTrue(out.startswith("No matches found"))

    def test_grep_truncation_and_context_cap(self):
        out = self.run_tool("git_grep", pattern="filler", context_lines=500)
        self.assertIn("context_lines capped", out)
        self.assertIn("output truncated", out)

    def test_show_range(self):
        out = self.run_tool("git_show", path="drv.c", start_line=8, end_line=9)
        self.assertIn("8\tstatic void", out)
        self.assertIn("9\tnew_cleanup(int y)", out)
        self.assertIn("start_line=10", out)

    def test_show_default_window(self):
        out = self.run_tool("git_show", path="drv.c")
        self.assertIn("lines 1-250 of", out)
        self.assertIn("start_line=251", out)

    def test_get_function_after_and_before(self):
        out = self.run_tool("get_function", name="new_cleanup")
        self.assertIn("in drv.c", out)
        self.assertIn("8\tstatic void", out)
        self.assertIn("14\t}", out)
        before = self.run_tool("get_function", name="new_cleanup", version="before")
        self.assertIn("not found", before)
        self.assertIn("added by this commit", before)
        main_before = self.run_tool("get_function", name="main_func", path="drv.c",
                                    version="before")
        self.assertNotIn("new_cleanup", main_before)


def tool_call(call_id, name, args):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def response(content=None, tool_calls=None, finish_reason="stop"):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish_reason)])


class TestToolLoop(unittest.TestCase):

    def setUp(self):
        self.client = make_client(".")
        self.client._run_tool = Mock(return_value="some result")
        self.client.client = Mock()

    def test_duplicate_calls_not_rerun(self):
        call = {"pattern": "foo", "context_lines": 40}
        same = {"pattern": "foo", "context_lines": 80}   # both capped to the same value
        self.client.client.chat.completions.create.side_effect = [
            response(tool_calls=[tool_call("1", "git_grep", call)]),
            response(tool_calls=[tool_call("2", "git_grep", same)]),
            response(content="VALID_FINDINGS: [1]"),
        ]
        out = self.client.analyze_with_tools("sys", "user", max_iterations=10, commit_ref="abc")
        self.assertEqual(out, "VALID_FINDINGS: [1]")
        self.assertEqual(self.client._run_tool.call_count, 1)
        messages = self.client.client.chat.completions.create.call_args.kwargs["messages"]
        second = [m for m in messages if m.get("tool_call_id") == "2"][0]
        self.assertTrue(second["content"].startswith("[Duplicate of tool call #1"))

    def test_final_answer_on_exhaustion(self):
        create = self.client.client.chat.completions.create
        create.side_effect = [
            response(tool_calls=[tool_call("1", "git_grep", {"pattern": "a"})]),
            response(tool_calls=[tool_call("2", "git_grep", {"pattern": "b"})]),
            response(content="VALID_FINDINGS: []"),
        ]
        out = self.client.analyze_with_tools("sys", "user", max_iterations=2)
        self.assertEqual(out, "VALID_FINDINGS: []")
        final_kwargs = create.call_args.kwargs
        self.assertEqual(final_kwargs["tool_choice"], "none")
        self.assertEqual(final_kwargs["messages"][-1]["content"], FINAL_ANSWER_PROMPT)

    def test_repeated_duplicates_force_final_answer(self):
        create = self.client.client.chat.completions.create
        same = [response(tool_calls=[tool_call(str(i), "git_grep", {"pattern": "x"})])
                for i in range(20)]
        create.side_effect = same[:6] + [response(content="VALID_FINDINGS: [1]")]
        out = self.client.analyze_with_tools("sys", "user", max_iterations=150)
        self.assertEqual(out, "VALID_FINDINGS: [1]")
        self.assertEqual(self.client._run_tool.call_count, 1)
        self.assertEqual(create.call_args.kwargs["tool_choice"], "none")
        self.assertEqual(create.call_args.kwargs["messages"][-1]["content"], LOOP_STOP_PROMPT)

    def test_final_answer_falls_back_without_tools(self):
        create = self.client.client.chat.completions.create
        create.side_effect = [
            response(tool_calls=[tool_call("1", "git_grep", {"pattern": "a"})]),
            RuntimeError("500 peg-native format"),
            response(content="VALID_FINDINGS: []"),
        ]
        out = self.client.analyze_with_tools("sys", "user", max_iterations=1)
        self.assertEqual(out, "VALID_FINDINGS: []")
        self.assertNotIn("tools", create.call_args.kwargs)

    def test_final_answer_flattened_conversation(self):
        create = self.client.client.chat.completions.create
        create.side_effect = [
            response(tool_calls=[tool_call("1", "git_grep", {"pattern": "a"})]),
            RuntimeError("500 peg-native format"),
            RuntimeError("500 peg-native format"),
            response(content="VALID_FINDINGS: [1]"),
        ]
        out = self.client.analyze_with_tools("sys", "user", max_iterations=1)
        self.assertEqual(out, "VALID_FINDINGS: [1]")
        messages = create.call_args.kwargs["messages"]
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertIn('git_grep({"pattern": "a"})', messages[1]["content"])
        self.assertIn("some result", messages[1]["content"])

    def test_truncated_answer_retried(self):
        create = self.client.client.chat.completions.create
        create.side_effect = [
            response(content="", finish_reason="length"),
            response(content="VALID_FINDINGS: [2]"),
        ]
        out = self.client.analyze_with_tools("sys", "user", max_iterations=5)
        self.assertEqual(out, "VALID_FINDINGS: [2]")
        self.assertEqual(create.call_args.kwargs["tool_choice"], "none")


if __name__ == '__main__':
    unittest.main()
