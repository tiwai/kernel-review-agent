"""Hybrid workflow: Pre-loaded context + tool calling for deep-dive."""

import re
from typing import List, Dict, Optional

from .workflow import ReviewWorkflow, ReviewResult
from git_integration import Commit
from llm_integration import ToolEnabledClient
import config


class HybridReviewWorkflow(ReviewWorkflow):
    """
    Hybrid approach: Pre-loaded context + tool calling.

    Uses the standard workflow with pre-loaded context for baseline analysis,
    then adds tool calling for specific deep-dive verification tasks.
    """

    def __init__(
        self,
        llm_client: ToolEnabledClient,
        *args,
        enable_tools: bool = True,
        **kwargs
    ):
        """
        Initialize hybrid workflow.

        Args:
            llm_client: ToolEnabledClient instance
            enable_tools: Enable tool calling for deep-dive checks
            *args, **kwargs: Passed to ReviewWorkflow
        """
        super().__init__(llm_client, *args, **kwargs)
        self.enable_tools = enable_tools

        if not isinstance(llm_client, ToolEnabledClient):
            raise TypeError("HybridReviewWorkflow requires ToolEnabledClient")

    def execute_review(self, commit: Commit) -> ReviewResult:
        """
        Execute review with hybrid approach.

        1. Run standard workflow (pre-loaded context)
        2. If findings detected, use tool calling for deep-dive verification
        """
        # Run standard workflow first
        if self.verbose:
            print("\n=== Phase 1: Standard Review (Pre-loaded Context) ===")

        result = super().execute_review(commit)

        # If tool calling disabled or no findings, return as-is
        if not self.enable_tools or not result.findings:
            return result

        # Phase 2: Tool-based deep-dive verification
        if self.verbose:
            print(f"\n=== Phase 2: Deep-dive Verification ({len(result.findings)} findings) ===")

        verified_findings = self._verify_findings_with_tools(commit, result.findings)

        # Update result with verified findings
        result.findings = verified_findings

        return result

    def _verify_findings_with_tools(self, commit: Commit, findings: List[Dict]) -> List[Dict]:
        """
        Use tool calling to verify and enhance findings.

        Args:
            commit: Commit being reviewed
            findings: Initial findings from standard workflow

        Returns:
            Verified/enhanced findings
        """
        verified = []

        # Check for timer API issues specifically
        timer_findings = self._verify_timer_api_issues(commit, findings)
        verified.extend(timer_findings)

        # Add other findings (not timer-related)
        for finding in findings:
            if finding.get('type') not in ['timer-api-conversion', 'timer-callback-signature']:
                verified.append(finding)

        return verified

    def _verify_timer_api_issues(self, commit: Commit, findings: List[Dict]) -> List[Dict]:
        """
        Use tool calling to verify timer API signature mismatches.

        This is more reliable than static analysis because it actually reads
        the callback function definition.
        """
        timer_related = [
            f for f in findings
            if f.get('type') in ['timer-api-conversion', 'timer-callback-signature']
            or 'timer' in f.get('message', '').lower()
        ]

        if not timer_related:
            return []

        if self.verbose:
            print(f"  Verifying {len(timer_related)} timer-related finding(s) with tools...")

        verified = []

        # Extract timer callbacks from diff
        callbacks = self._extract_timer_callbacks(commit.diff)

        if not callbacks:
            # No callbacks found, keep original findings
            return timer_related

        # Verify each callback signature
        for callback_name in set(callbacks):
            if self.verbose:
                print(f"    Checking callback: {callback_name}")

            system_prompt = """You are verifying timer API callback signatures in Linux kernel code.

Timer APIs have INCOMPATIBLE callback signatures:
- timer_setup() requires: void callback(struct timer_list *t)
- setup_timer() requires: void callback(unsigned long data)

You have git tools to read code. Use them to verify the callback signature."""

            user_prompt = f"""This diff changes timer setup:

{commit.diff[:2000]}

Task: Verify if callback function `{callback_name}` has the correct signature.

Steps:
1. Use git_grep to find the definition of `{callback_name}`
2. Check its parameter type
3. Check which timer API is being used (look for timer_setup or setup_timer in the diff)
4. Answer: Does the signature match the API? (YES = correct, NO = bug)

Be concise."""

            try:
                response = self.llm.analyze_with_tools(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_iterations=5,
                    max_tokens=2000
                )

                # Check if verification confirms a bug
                response_lower = response.lower()
                if any(word in response_lower for word in ['no', 'bug', 'mismatch', 'incorrect', 'wrong']):
                    # Bug confirmed
                    verified.append({
                        'category': 'TIMER-API',
                        'type': 'timer-callback-signature',
                        'severity': 'high',
                        'message': f"Timer callback {callback_name} signature mismatch (verified with code inspection)",
                        'evidence': response[:300],
                        'tool_verified': True
                    })

                    if self.verbose:
                        print(f"      → BUG CONFIRMED: {callback_name}")
                elif 'yes' in response_lower or 'correct' in response_lower:
                    if self.verbose:
                        print(f"      → False positive: {callback_name} signature is correct")
                else:
                    # Uncertain - keep original finding
                    for f in timer_related:
                        if callback_name in f.get('evidence', '') or callback_name in f.get('message', ''):
                            verified.append(f)
                            break

            except Exception as e:
                if self.debug:
                    print(f"[DEBUG] Tool verification failed for {callback_name}: {e}")
                # On error, keep original findings
                for f in timer_related:
                    if callback_name in f.get('evidence', '') or callback_name in f.get('message', ''):
                        verified.append(f)
                        break

        return verified

    def _extract_timer_callbacks(self, diff: str) -> List[str]:
        """Extract timer callback function names from diff."""
        callbacks = []
        timer_patterns = [
            (r'timer_setup\s*\(\s*[^,]+,\s*(\w+)', 'timer_setup'),
            (r'setup_timer\s*\(\s*[^,]+,\s*(\w+)', 'setup_timer'),
            (r'hrtimer_setup\s*\(\s*[^,]+,\s*(\w+)', 'hrtimer_setup'),
        ]

        for line in diff.split('\n'):
            if line.startswith('+') or line.startswith(' '):
                for pattern, _ in timer_patterns:
                    match = re.search(pattern, line)
                    if match:
                        callback = match.group(1)
                        if callback not in ['NULL', '0']:
                            callbacks.append(callback)

        return callbacks
