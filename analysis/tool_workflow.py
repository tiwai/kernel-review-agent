"""Full tool-calling workflow without pre-loaded context."""

import re
import json
from typing import List, Dict
from dataclasses import dataclass

from git_integration import Commit
from llm_integration import ToolEnabledClient
from prompt_management import PromptLoader, SubsystemMatcher
import config


@dataclass
class ToolReviewResult:
    """Review result from tool-calling workflow."""
    findings: List[Dict]
    summary: str
    subsystems_loaded: List[str]
    tool_calls_made: int


class ToolCallReviewWorkflow:
    """
    Full tool-calling workflow.

    LLM uses git tools to gather all context on-demand.
    No pre-loading of code context.
    """

    def __init__(
        self,
        llm_client: ToolEnabledClient,
        prompt_loader: PromptLoader,
        subsystem_matcher: SubsystemMatcher,
        verbose: bool = False,
        debug: bool = False
    ):
        """
        Initialize tool-call workflow.

        Args:
            llm_client: ToolEnabledClient instance
            prompt_loader: Prompt loader
            subsystem_matcher: Subsystem matcher
            verbose: Verbose output
            debug: Debug output
        """
        if not isinstance(llm_client, ToolEnabledClient):
            raise TypeError("ToolCallReviewWorkflow requires ToolEnabledClient")

        self.llm = llm_client
        self.prompts = prompt_loader
        self.matcher = subsystem_matcher
        self.verbose = verbose
        self.debug = debug

    def execute_review(self, commit: Commit) -> ToolReviewResult:
        """
        Execute review using tool calling exclusively.

        Returns:
            ToolReviewResult with findings
        """
        if self.verbose:
            print(f"\nReviewing commit {commit.sha[:12]} (tool-calling mode)...")
            print(f"Subject: {commit.subject}\n")

        # Match subsystems
        subsystems = self.matcher.match_diff(commit.files, commit.diff)
        if self.verbose and subsystems:
            print(f"Matched subsystems: {', '.join(subsystems)}")

        # Load subsystem prompts
        subsystem_context = ""
        for subsys in subsystems:
            subsys_prompt = self.prompts.get_subsystem_prompt(subsys)
            if subsys_prompt:
                subsystem_context += f"\n## {subsys.upper()} Subsystem Rules\n\n{subsys_prompt}\n"

        # Execute structured review tasks
        all_findings = []

        # Task 1: Timer API checks
        if self.verbose:
            print("\n[1/3] Checking timer API conversions...")

        timer_findings = self._check_timer_apis(commit, subsystem_context)
        if timer_findings:
            all_findings.extend(timer_findings)
            if self.verbose:
                print(f"      Found {len(timer_findings)} timer issue(s)")

        # Task 2: Error handling checks
        if self.verbose:
            print("\n[2/3] Checking error handling...")

        error_findings = self._check_error_handling(commit, subsystem_context)
        if error_findings:
            all_findings.extend(error_findings)
            if self.verbose:
                print(f"      Found {len(error_findings)} error handling issue(s)")

        # Task 3: Memory safety checks
        if self.verbose:
            print("\n[3/3] Checking memory safety...")

        memory_findings = self._check_memory_safety(commit, subsystem_context)
        if memory_findings:
            all_findings.extend(memory_findings)
            if self.verbose:
                print(f"      Found {len(memory_findings)} memory safety issue(s)")

        # Generate summary
        summary = self._generate_summary(commit, all_findings)

        return ToolReviewResult(
            findings=all_findings,
            summary=summary,
            subsystems_loaded=subsystems,
            tool_calls_made=0  # TODO: track this
        )

    def _check_timer_apis(self, commit: Commit, subsystem_context: str) -> List[Dict]:
        """Check timer API conversions using tool calling."""
        # Check if diff contains timer changes
        timer_patterns = ['timer_setup', 'setup_timer', 'hrtimer_setup']
        if not any(p in commit.diff for p in timer_patterns):
            return []

        # Extract callback names
        callbacks = []
        for line in commit.diff.split('\n'):
            match = re.search(r'(?:timer_setup|setup_timer)\s*\([^,]+,\s*(\w+)', line)
            if match and match.group(1) not in ['NULL', '0']:
                callbacks.append(match.group(1))

        if not callbacks:
            return []

        findings = []

        for callback in set(callbacks):
            system_prompt = f"""You are a Linux kernel code reviewer checking timer API usage.

{subsystem_context}

CRITICAL: Timer APIs have incompatible signatures:
- timer_setup() requires: void callback(struct timer_list *t)
- setup_timer() (old) requires: void callback(unsigned long data)

Use git tools to verify callback signatures."""

            user_prompt = f"""Analyze this timer API change:

COMMIT MESSAGE:
{commit.message[:500]}

DIFF:
{commit.diff[:2000]}

Task: Verify callback `{callback}` signature matches the timer API being used.

1. Use git_grep to find `{callback}` function definition
2. Check its signature (parameter type)
3. Check which API is used (timer_setup or setup_timer)
4. Report if there's a mismatch

Respond: BUG or OK"""

            try:
                response = self.llm.analyze_with_tools(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_iterations=5,
                    max_tokens=2000
                )

                if 'bug' in response.lower() or 'mismatch' in response.lower():
                    findings.append({
                        'category': 'TIMER-API',
                        'type': 'timer-callback-signature',
                        'severity': 'high',
                        'message': f"Timer callback {callback} signature mismatch",
                        'evidence': response
                    })

            except Exception as e:
                if self.debug:
                    print(f"[DEBUG] Timer check failed for {callback}: {e}")

        return findings

    def _check_error_handling(self, commit: Commit, subsystem_context: str) -> List[Dict]:
        """Check error handling using tool calling."""
        # Extract changed functions
        functions = self._extract_functions_from_diff(commit.diff)

        if not functions:
            return []

        findings = []

        # Check first 2 functions (to keep it fast)
        for func_info in functions[:2]:
            func_name = func_info['name']
            file_path = func_info['file']

            system_prompt = f"""You are checking error handling in Linux kernel code.

{subsystem_context}

Common issues:
- Missing NULL checks after kmalloc/kzalloc
- Missing ERR_PTR checks (use IS_ERR/PTR_ERR)
- Resource leaks on error paths
- Wrong error codes returned"""

            user_prompt = f"""Check error handling in function `{func_name}`:

DIFF:
{commit.diff[:2000]}

1. Use git_show to read {file_path} at HEAD
2. Find function `{func_name}`
3. Check for missing error checks or resource leaks

Respond with JSON array: [{{"type":"...", "message":"...", "severity":"..."}}] or []"""

            try:
                response = self.llm.analyze_with_tools(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_iterations=6,
                    max_tokens=3000
                )

                # Try to parse JSON
                json_match = re.search(r'\[.*\]', response, re.DOTALL)
                if json_match:
                    issues = json.loads(json_match.group(0))
                    if issues:
                        findings.extend(issues)

            except Exception as e:
                if self.debug:
                    print(f"[DEBUG] Error check failed for {func_name}: {e}")

        return findings

    def _check_memory_safety(self, commit: Commit, subsystem_context: str) -> List[Dict]:
        """Check memory safety using tool calling."""
        # Look for memory-related changes
        memory_keywords = ['kfree', 'kmalloc', 'kzalloc', 'free', 'alloc', 'delete', 'put_']

        has_memory_changes = any(kw in commit.diff for kw in memory_keywords)

        if not has_memory_changes:
            return []

        findings = []

        system_prompt = f"""You are checking memory safety in Linux kernel code.

{subsystem_context}

Look for:
- Use-after-free (using object after free/put)
- Double-free (freeing twice)
- Memory leaks (allocated but not freed on all paths)"""

        user_prompt = f"""Check memory safety:

DIFF:
{commit.diff}

Use git tools to read functions if needed. Report any memory safety issues.

Respond with JSON array or [].
"""

        try:
            response = self.llm.analyze_with_tools(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_iterations=6,
                max_tokens=3000
            )

            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                issues = json.loads(json_match.group(0))
                if issues:
                    findings.extend(issues)

        except Exception as e:
            if self.debug:
                print(f"[DEBUG] Memory check failed: {e}")

        return findings

    def _extract_functions_from_diff(self, diff: str) -> List[Dict]:
        """Extract changed functions from diff hunk headers."""
        functions = []
        current_file = None

        for line in diff.split('\n'):
            if line.startswith('diff --git'):
                match = re.search(r'b/(.+)$', line)
                if match:
                    current_file = match.group(1)
            elif line.startswith('@@') and current_file:
                match = re.search(r'@@.*?@@\s*(.+)', line)
                if match:
                    func_match = re.search(r'\b(\w+)\s*\(', match.group(1))
                    if func_match:
                        func_name = func_match.group(1)
                        if func_name not in ['if', 'while', 'for', 'switch', 'return']:
                            functions.append({'name': func_name, 'file': current_file})

        # Remove duplicates
        seen = set()
        unique = []
        for f in functions:
            key = (f['name'], f['file'])
            if key not in seen:
                seen.add(key)
                unique.append(f)

        return unique

    def _generate_summary(self, commit: Commit, findings: List[Dict]) -> str:
        """Generate summary of findings."""
        if not findings:
            return "No issues found."

        high = sum(1 for f in findings if f.get('severity') == 'high')
        medium = sum(1 for f in findings if f.get('severity') == 'medium')
        low = sum(1 for f in findings if f.get('severity') == 'low')

        parts = []
        if high > 0:
            parts.append(f"{high} high")
        if medium > 0:
            parts.append(f"{medium} medium")
        if low > 0:
            parts.append(f"{low} low")

        severity_str = ", ".join(parts) if parts else f"{len(findings)}"

        return f"Found {len(findings)} potential issue(s): {severity_str} severity"
