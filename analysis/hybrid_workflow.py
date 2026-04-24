"""Hybrid workflow: Pre-loaded context + tool calling for deep-dive."""

import re
from typing import List, Dict, Optional

from .workflow import ReviewWorkflow, ReviewResult
from .backport_verifier import BackportVerifier, BackportComparison
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
        upstream_repo=None,
        **kwargs
    ):
        """
        Initialize hybrid workflow.

        Args:
            llm_client: ToolEnabledClient instance
            enable_tools: Enable tool calling for deep-dive checks
            upstream_repo: MultiRepoExtractor for upstream Linux kernel (for backport verification)
            *args, **kwargs: Passed to ReviewWorkflow
        """
        super().__init__(llm_client, *args, **kwargs)
        self.enable_tools = enable_tools
        self.backport_verifier = BackportVerifier(
            upstream_repo=upstream_repo,
            verbose=kwargs.get('verbose', False),
            debug=kwargs.get('debug', False)
        )

        if not isinstance(llm_client, ToolEnabledClient):
            raise TypeError("HybridReviewWorkflow requires ToolEnabledClient")

    def execute_review(self, commit: Commit) -> ReviewResult:
        """
        Execute review with hybrid approach.

        0. Check backport quality (compare with upstream if available)
        1. Run standard workflow (pre-loaded context)
        2. If findings detected, use tool calling for deep-dive verification
        """
        # Phase 0: Backport verification
        backport_comparison = None
        backport_info_for_llm = None

        if commit.upstream_commit:
            if self.verbose:
                print(f"\n=== Phase 0: Backport Verification ===")
                print(f"  Upstream commit: {commit.upstream_commit[:12]}")

            backport_comparison = self.backport_verifier.verify_backport(commit)

            if backport_comparison and backport_comparison.has_upstream:
                if self.verbose:
                    print(f"  {backport_comparison.summary}")

                # Prepare backport info for LLM if differences found
                if backport_comparison.differences_found:
                    backport_info_for_llm = self._format_backport_info_for_llm(backport_comparison)

                    if backport_comparison.needs_deep_review and self.verbose:
                        print(f"  → Deep review required - backport differences detected")

        # Phase 1: Run standard workflow (with backport info if available)
        if self.verbose:
            phase_num = "1" if commit.upstream_commit else ""
            print(f"\n=== Phase {phase_num}: Standard Review (Pre-loaded Context) ===")

        # Temporarily store backport info for use in the review
        original_commit_message = commit.message
        if backport_info_for_llm:
            # Append backport analysis to commit message for LLM context
            commit.message = commit.message + "\n\n" + backport_info_for_llm

        result = super().execute_review(commit)

        # Restore original commit message
        commit.message = original_commit_message

        # Add backport comparison to result metadata
        if backport_comparison and backport_comparison.has_upstream:
            result.backport_comparison = backport_comparison

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

        # Check for locking issues (deadlocks, missing locks)
        lock_findings = self._verify_lock_issues(commit, findings)
        verified.extend(lock_findings)

        # Check for use-after-free issues (verify reference counting)
        uaf_findings = self._verify_uaf_issues(commit, findings)
        verified.extend(uaf_findings)

        # Add other findings (not timer, lock, or UAF-related)
        excluded_types = ['timer-api-conversion', 'timer-callback-signature',
                          'deadlock', 'double-lock', 'missing-lock', 'lock-order',
                          'use-after-free', 'uaf', 'double-free']
        for finding in findings:
            ftype = finding.get('type', '')
            if (ftype not in excluded_types and
                'lock' not in ftype.lower() and
                'use-after-free' not in finding.get('message', '').lower() and
                'uaf' not in ftype.lower()):
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

    def _verify_lock_issues(self, commit: Commit, findings: List[Dict]) -> List[Dict]:
        """
        Use tool calling to verify locking issues (deadlocks, missing locks).

        Common false positive: Missing an unlock (up_write/mutex_unlock) that
        happens between lock acquire and the supposed deadlock point.
        """
        # Find lock-related findings
        lock_related = [
            f for f in findings
            if any(word in f.get('type', '').lower() for word in ['lock', 'deadlock']) or
               any(word in f.get('message', '').lower() for word in ['deadlock', 'double-lock', 'recursive lock'])
        ]

        if not lock_related:
            return []

        if self.verbose:
            print(f"  Verifying {len(lock_related)} lock-related finding(s) with tools...")

        verified = []

        for finding in lock_related:
            # Extract function name from finding
            func_match = re.search(r'(?:in function|function) [`\']?(\w+)[`\']?', finding.get('message', ''))
            if not func_match:
                # Try to extract from evidence
                func_match = re.search(r'(\w+)\s*\(', finding.get('evidence', ''))

            if not func_match:
                # Can't verify without function name - keep original finding
                verified.append(finding)
                continue

            func_name = func_match.group(1)

            if self.verbose:
                print(f"    Checking locking in: {func_name}")

            system_prompt = """You are verifying a potential locking issue in Linux kernel code.

CRITICAL REQUIREMENTS:
1. You MUST trace lock state through ALL code paths
2. You MUST show lock acquisitions (down_write/mutex_lock/spin_lock)
3. You MUST show lock releases (up_write/mutex_unlock/spin_unlock)
4. You MUST verify the lock is ACTUALLY HELD at the problematic point

DO NOT report a deadlock unless you can prove the lock is held at both acquisition points."""

            user_prompt = f"""A potential locking issue was reported:

ISSUE: {finding.get('message', '')}

DIFF:
{commit.diff[:2000]}

Task: Verify if this is a real bug or false positive.

1. Use git_show to read the COMPLETE function `{func_name}`
2. Find ALL lock operations:
   - Acquisitions: down_write, down_read, mutex_lock, spin_lock
   - Releases: up_write, up_read, mutex_unlock, spin_unlock
3. Trace lock state through the code path to the problematic point
4. Show a lock trace like:
   Line X: down_write(&lock)    [LOCKED]
   Line Y: if (condition)        [LOCKED]
   Line Z:   up_write(&lock)     [UNLOCKED] ← Release
   Line A:   function()          [UNLOCKED]
   Line B:   goto label          [UNLOCKED]
   Line C: label: down_write()   [LOCKED] ← Reacquire OK

Answer: REAL_BUG or FALSE_POSITIVE (with lock trace)

Be concise but include the lock trace."""

            try:
                response = self.llm.analyze_with_tools(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_iterations=6,
                    max_tokens=3000
                )

                # Check response
                response_lower = response.lower()

                if 'real_bug' in response_lower and 'false' not in response_lower:
                    # Bug confirmed - keep finding
                    verified.append(finding)
                    if self.verbose:
                        print(f"      → BUG CONFIRMED: {func_name}")
                elif 'false_positive' in response_lower or 'false positive' in response_lower:
                    # False positive - discard
                    if self.verbose:
                        print(f"      → False positive: {func_name} - lock is released")
                elif 'unlock' in response_lower or 'up_write' in response_lower or 'released' in response_lower:
                    # Response mentions unlock - likely false positive
                    if self.verbose:
                        print(f"      → False positive: {func_name} - lock release detected")
                else:
                    # Uncertain - keep finding but mark as unverified
                    if self.verbose:
                        print(f"      → Could not verify: {func_name}")
                    verified.append(finding)

            except Exception as e:
                if self.debug:
                    print(f"[DEBUG] Lock verification failed for {func_name}: {e}")
                # On error, keep original finding
                verified.append(finding)

        return verified

    def _verify_uaf_issues(self, commit: Commit, findings: List[Dict]) -> List[Dict]:
        """
        Use tool calling to verify use-after-free issues.

        Common false positive: Not checking the initial value of reference counters.
        Many objects start with refcount > 1, so first decrement doesn't free.
        """
        # Find UAF-related findings
        uaf_related = [
            f for f in findings
            if 'use-after-free' in f.get('type', '').lower() or
               'uaf' in f.get('type', '').lower() or
               'use-after-free' in f.get('message', '').lower() or
               ('free' in f.get('message', '').lower() and 'race' in f.get('message', '').lower())
        ]

        if not uaf_related:
            return []

        if self.verbose:
            print(f"  Verifying {len(uaf_related)} use-after-free finding(s) with tools...")

        verified = []

        for finding in uaf_related:
            # Extract relevant variable/struct name
            # Look for patterns like "wq", "obj", "ptr", etc.
            var_match = re.search(r'\b([a-z_]+)(?:->|\.|\.)', finding.get('evidence', ''))
            if not var_match:
                var_match = re.search(r'(?:free|kfree|put_)\(([a-z_][a-z0-9_]*)\)', finding.get('evidence', ''))

            if not var_match:
                # Can't extract variable - keep finding
                verified.append(finding)
                continue

            var_name = var_match.group(1)

            # Look for reference counter patterns
            ref_patterns = ['wait_ctr', 'refcnt', 'ref_count', 'kref', 'count', 'users']
            ref_counter = None
            for pattern in ref_patterns:
                if pattern in commit.diff or pattern in finding.get('evidence', ''):
                    ref_counter = pattern
                    break

            if not ref_counter:
                # No obvious reference counter - keep finding
                verified.append(finding)
                continue

            if self.verbose:
                print(f"    Checking UAF: {var_name} (refcount: {ref_counter})")

            system_prompt = """You are verifying a potential use-after-free issue in Linux kernel code.

CRITICAL: Many objects use reference counting starting at 2 or higher.

Before reporting UAF, you MUST:
1. Find the INITIAL value of the reference counter
2. Find ALL increment operations
3. Find ALL decrement/free operations
4. Trace the reference count to verify it can actually reach 0 before the access

DO NOT assume refcount starts at 1 or 0 - verify the initialization!"""

            user_prompt = f"""A potential use-after-free was reported:

ISSUE: {finding.get('message', '')}

EVIDENCE: {finding.get('evidence', '')}

DIFF:
{commit.diff[:2000]}

Task: Verify if this is a real UAF or false positive.

1. Use git_show to read the file containing `{var_name}`
2. Find the initialization of reference counter `{ref_counter}`
   - What is the INITIAL value? (often 2, not 1!)
3. Find ALL places that increment `{ref_counter}`
4. Trace reference count through the code path:
   - Initial: {ref_counter} = ?
   - After increments: {ref_counter} = ?
   - After first decrement: {ref_counter} = ?
   - Can it actually reach 0 at the free point?

Answer: REAL_UAF or FALSE_POSITIVE (with reference count trace)

Include the reference count trace showing initial value and all changes.
Be concise but show the trace."""

            try:
                response = self.llm.analyze_with_tools(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_iterations=8,
                    max_tokens=3000
                )

                response_lower = response.lower()

                # Look for reference count analysis
                if 'false_positive' in response_lower or 'false positive' in response_lower:
                    if self.verbose:
                        print(f"      → False positive: {var_name} - refcount prevents UAF")
                elif ('initial' in response_lower and
                      any(str(n) in response for n in [' = 2', '= 3', 'starts at 2', 'starts at 3'])):
                    # Response mentions initial value > 1 - likely false positive
                    if self.verbose:
                        print(f"      → False positive: {var_name} - refcount starts > 1")
                elif 'real_uaf' in response_lower and 'false' not in response_lower:
                    verified.append(finding)
                    if self.verbose:
                        print(f"      → BUG CONFIRMED: {var_name}")
                else:
                    # Uncertain - keep finding
                    if self.verbose:
                        print(f"      → Could not verify: {var_name}")
                    verified.append(finding)

            except Exception as e:
                if self.debug:
                    print(f"[DEBUG] UAF verification failed for {var_name}: {e}")
                verified.append(finding)

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

    def _format_backport_info_for_llm(self, comparison: BackportComparison) -> str:
        """
        Format backport comparison for LLM context.

        Returns a clear description of the backport differences that the LLM
        should pay attention to during review.
        """
        parts = []

        parts.append("=== BACKPORT ANALYSIS ===")
        parts.append(f"Upstream commit: {comparison.upstream_commit[:12]}")
        parts.append("")

        parts.append("**IMPORTANT**: This is a backport from upstream.")
        parts.append("The downstream patch differs from upstream - verify the backport is correct!")
        parts.append("")

        if comparison.file_path_changes:
            parts.append("File Path Differences:")
            for upstream_path, downstream_path in comparison.file_path_changes:
                parts.append(f"  - Upstream:   {upstream_path}")
                parts.append(f"    Downstream: {downstream_path}")
            parts.append("")

        if comparison.line_number_shifts:
            parts.append("Line Number Shifts:")
            for shift in comparison.line_number_shifts[:5]:  # Limit to top 5
                parts.append(
                    f"  - {shift['file']}: "
                    f"upstream line {shift['upstream_line']} → "
                    f"downstream line {shift['downstream_line']} "
                    f"(shift: {shift['shift']} lines {shift['direction']})"
                )
            if len(comparison.line_number_shifts) > 5:
                parts.append(f"  ... and {len(comparison.line_number_shifts) - 5} more shifts")
            parts.append("")

        if comparison.context_mismatches:
            parts.append("Context Mismatches (surrounding code differs):")
            for mismatch in comparison.context_mismatches[:3]:  # Limit to top 3
                parts.append(
                    f"  - {mismatch['file']}: "
                    f"line {mismatch['downstream_line']} "
                    f"(match score: {mismatch['match_score']:.1%})"
                )
            if len(comparison.context_mismatches) > 3:
                parts.append(f"  ... and {len(comparison.context_mismatches) - 3} more mismatches")
            parts.append("")

        if comparison.missing_hunks:
            parts.append("Missing Hunks (in upstream but not downstream):")
            for hunk in comparison.missing_hunks[:5]:
                parts.append(f"  - {hunk}")
            if len(comparison.missing_hunks) > 5:
                parts.append(f"  ... and {len(comparison.missing_hunks) - 5} more")
            parts.append("")

        if comparison.extra_hunks:
            parts.append("Extra Hunks (in downstream but not upstream):")
            for hunk in comparison.extra_hunks[:5]:
                parts.append(f"  - {hunk}")
            if len(comparison.extra_hunks) > 5:
                parts.append(f"  ... and {len(comparison.extra_hunks) - 5} more")
            parts.append("")

        if comparison.needs_deep_review:
            parts.append("**ACTION REQUIRED**: Deep verification needed!")
            parts.append("Verify that:")
            parts.append("  1. Patch applied to functionally equivalent code location")
            parts.append("  2. All critical parts of upstream patch are present")
            parts.append("  3. Logic/semantics match upstream intent")
            parts.append("  4. No missing error handling or cleanup code")
            parts.append("")

        parts.append("=== END BACKPORT ANALYSIS ===")

        return "\n".join(parts)
