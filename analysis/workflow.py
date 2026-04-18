"""Main review workflow orchestration (5-task protocol)."""

import json
import re
import sys
from typing import List, Dict, Optional
from dataclasses import dataclass

from git_integration import Commit
from llm_integration import OpenAIClient
from prompt_management import PromptLoader, SubsystemMatcher
import config


@dataclass
class ReviewResult:
    """Review result containing findings and metadata."""
    findings: List[Dict]
    summary: str
    subsystems_loaded: List[str]
    suse_verification: Optional[Dict] = None  # SUSE upstream verification result


class ReviewWorkflow:
    """Orchestrate 5-task review protocol."""

    def __init__(
        self,
        llm_client: OpenAIClient,
        prompt_loader: PromptLoader,
        subsystem_matcher: SubsystemMatcher,
        verbose: bool = False,
        debug: bool = False,
        skip_verification: bool = False,
        suse_verifier: Optional['SuseUpstreamVerifier'] = None
    ):
        """
        Initialize review workflow.

        Args:
            llm_client: LLM client for API calls
            prompt_loader: Prompt loader
            subsystem_matcher: Subsystem matcher
            verbose: Enable verbose output
            debug: Enable debug output
            skip_verification: Skip false-positive verification step
            suse_verifier: SUSE upstream verifier (optional)
        """
        self.llm = llm_client
        self.prompts = prompt_loader
        self.matcher = subsystem_matcher
        self.verbose = verbose
        self.debug = debug
        self.skip_verification = skip_verification
        self.suse_verifier = suse_verifier

    def execute_review(self, commit: Commit) -> ReviewResult:
        """
        Execute full 5-task review protocol.

        Args:
            commit: Commit to review

        Returns:
            ReviewResult with findings and metadata
        """
        if self.verbose:
            print(f"\nReviewing commit {commit.sha[:12]}...")
            print(f"Subject: {commit.subject}\n")

        # Task 0: Context management (automated)
        if self.verbose:
            print("[1/5] Gathering context...")
        if self.debug:
            print(f"[DEBUG] Task 0: Context management")
            print(f"[DEBUG] Commit SHA: {commit.sha}")
            print(f"[DEBUG] Files changed: {len(commit.files)}")
            print(f"[DEBUG] Diff size: {len(commit.diff)} chars")

        context = self._gather_context(commit)

        if self.debug:
            print(f"[DEBUG] Context gathered:")
            print(f"[DEBUG]   - Changed functions: {context.get('changed_functions', [])}")
            print(f"[DEBUG]   - Files: {context.get('files', [])}")

        # Match subsystems
        subsystems = self.matcher.match_diff(commit.files, commit.diff)
        if self.verbose and subsystems:
            print(f"      Matched subsystems: {', '.join(subsystems)}")
        if self.debug:
            print(f"[DEBUG] Subsystems matched: {subsystems}")

        # Task 1: Categorize changes (LLM-driven)
        if self.verbose:
            print("\n[2/5] Categorizing changes...")
        if self.debug:
            print(f"[DEBUG] Task 1: Categorizing changes")
            print(f"[DEBUG] Calling LLM for categorization...")

        categories = self._categorize_changes(commit, context)

        if self.verbose:
            print(f"      Found {len(categories)} change categories")
        if self.debug:
            print(f"[DEBUG] Categories:")
            for cat in categories:
                print(f"[DEBUG]   - {cat.get('id')}: {cat.get('type')} - {cat.get('description', '')[:60]}")

        # Task 2: Analyze for regressions (LLM-driven)
        if self.verbose:
            print("\n[3/5] Analyzing for regressions...")
        if self.debug:
            print(f"[DEBUG] Task 2: Analyzing for regressions")
            print(f"[DEBUG] Loading subsystem guides: {subsystems}")
            print(f"[DEBUG] Calling LLM for regression analysis...")

        findings = self._analyze_regressions(commit, categories, context, subsystems)

        if self.verbose:
            print(f"      Found {len(findings)} potential issues")
        if self.debug:
            print(f"[DEBUG] Findings:")
            for i, finding in enumerate(findings):
                print(f"[DEBUG]   {i+1}. {finding.get('type')}: {finding.get('message', '')[:60]}...")

        # Task 2.5: SUSE upstream verification (conditional)
        suse_verification_result = None
        if self.suse_verifier and self.suse_verifier.should_verify(commit, findings):
            if self.verbose:
                print("\n[3.5/5] Verifying against upstream...")
            if self.debug:
                print(f"[DEBUG] Task 2.5: SUSE upstream verification")

            suse_verification_result = self.suse_verifier.verify_against_upstream(
                commit, findings
            )

            # Annotate findings with upstream status
            findings_in_upstream = set(
                id(f) for f in suse_verification_result.get('findings_in_upstream', [])
            )

            for finding in findings:
                if id(finding) in findings_in_upstream:
                    finding['upstream_status'] = 'present_in_upstream'
                else:
                    finding['upstream_status'] = 'downstream_only'

            if self.debug:
                print(f"[DEBUG] SUSE verification complete")
                print(f"[DEBUG]   Findings in upstream: {len(suse_verification_result.get('findings_in_upstream', []))}")
                print(f"[DEBUG]   Downstream-only: {len(suse_verification_result.get('findings_only_downstream', []))}")

        # Task 3: Verify findings (eliminate false positives)
        if self.skip_verification:
            if self.verbose:
                print("\n[4/5] Skipping verification (--skip-verification enabled)...")
            if self.debug:
                print(f"[DEBUG] Task 3: SKIPPED (verification disabled)")
            verified = findings
        else:
            if self.verbose:
                print("\n[4/5] Verifying findings...")
            if self.debug:
                print(f"[DEBUG] Task 3: Verifying findings")
                print(f"[DEBUG] Applying false-positive checks to {len(findings)} findings...")

            verified = self._verify_findings(findings, context, commit)

            if self.verbose:
                print(f"      {len(verified)} issues after verification")
            if self.debug:
                discarded = len(findings) - len(verified)
                print(f"[DEBUG] Verification complete: {len(verified)} verified, {discarded} discarded as false positives")

        # Task 4: Generate summary
        if self.verbose:
            print("\n[5/5] Generating summary...")
        if self.debug:
            print(f"[DEBUG] Task 4: Generating summary")

        summary = self._generate_summary(commit, verified, suse_verification_result)

        if self.debug:
            print(f"[DEBUG] Summary: {summary}")

        if self.verbose:
            print(f"\nReview complete: {len(verified)} issue(s) found\n")

        return ReviewResult(
            findings=verified,
            summary=summary,
            subsystems_loaded=subsystems,
            suse_verification=suse_verification_result
        )

    def _gather_context(self, commit: Commit) -> Dict:
        """
        Task 0: Automated context gathering.

        Returns:
            Context dictionary with changed functions, files, etc.
        """
        context = {
            "files": commit.files,
            "changed_functions": self._extract_changed_functions(commit.diff),
            "diff_stats": {
                "files_changed": len(commit.files),
                "has_c_files": any(f.endswith('.c') for f in commit.files),
                "has_h_files": any(f.endswith('.h') for f in commit.files)
            }
        }
        return context

    def _extract_changed_functions(self, diff: str) -> List[str]:
        """Extract function names from diff hunks."""
        functions = set()

        # Look for function context in hunk headers: @@ ... @@ function_name
        for line in diff.split('\n'):
            if line.startswith('@@'):
                # Extract function name after the second @@
                match = re.search(r'@@.*@@\s*(\w+)', line)
                if match:
                    functions.add(match.group(1))

        return list(functions)

    def _categorize_changes(self, commit: Commit, context: Dict) -> List[Dict]:
        """
        Task 1: Categorize changes using LLM.

        Returns:
            List of change categories
        """
        # Build prompt for categorization
        system_prompt = self.prompts.load_review_core()

        user_prompt = f"""Analyze this commit and categorize the changes.

For each distinct change, create a category with:
- id: CHANGE-1, CHANGE-2, etc.
- type: control-flow, resource-management, locking, initialization, cleanup, or other
- description: Brief description of what changed
- location: File and function name

Commit: {commit.subject}

Diff:
{commit.diff}

Return ONLY a JSON array of changes, no other text:
[{{"id": "CHANGE-1", "type": "...", "description": "...", "location": "..."}}]
"""

        response = self.llm.analyze_code(system_prompt, user_prompt, max_tokens=config.CATEGORIZE_MAX_TOKENS)

        # Parse JSON response
        try:
            # Extract JSON from response (may have markdown code blocks)
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                categories = json.loads(json_match.group(0))
                return categories if isinstance(categories, list) else []
            else:
                if self.verbose or self.debug:
                    print("[WARNING] No JSON array found in categorization response", file=sys.stderr)
                    print(f"[WARNING] Response preview: {response[:200]}...", file=sys.stderr)
        except json.JSONDecodeError as e:
            if self.verbose or self.debug:
                print(f"[ERROR] Failed to parse categorization JSON: {e}", file=sys.stderr)
                print(f"[ERROR] Response may be truncated. Last 100 chars: ...{response[-100:]}", file=sys.stderr)
                print(f"[ERROR] Increase CATEGORIZE_MAX_TOKENS in config.py (current: {config.CATEGORIZE_MAX_TOKENS})", file=sys.stderr)

        return []

    def _analyze_regressions(
        self,
        commit: Commit,
        categories: List[Dict],
        context: Dict,
        subsystems: List[str]
    ) -> List[Dict]:
        """
        Task 2: Analyze for regressions using LLM.

        Returns:
            List of potential findings
        """
        # Build comprehensive system prompt with subsystem guides
        system_prompt = self.prompts.build_system_prompt(
            include_technical_patterns=True,
            include_false_positive_guide=False,
            subsystem_guides=subsystems
        )

        # Build user prompt with categorized changes
        categories_text = json.dumps(categories, indent=2)

        user_prompt = f"""Analyze this commit for potential regressions.

Commit: {commit.subject}

Categories of changes:
{categories_text}

Full diff:
{commit.diff}

For each potential issue found, return a JSON object with:
- category: Which CHANGE-X this relates to
- type: Type of issue (use-after-free, memory-leak, null-deref, race-condition, etc.)
- message: Question or description of the issue (conversational, no ALL CAPS)
- evidence: Code snippets or call traces supporting the finding
- severity: low, medium, or high

Return ONLY a JSON array of findings:
[{{"category": "CHANGE-1", "type": "...", "message": "...", "evidence": "...", "severity": "..."}}]

If no issues found, return: []
"""

        response = self.llm.analyze_code(system_prompt, user_prompt, max_tokens=config.ANALYZE_MAX_TOKENS)

        # Parse JSON response
        try:
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                findings = json.loads(json_match.group(0))
                return findings if isinstance(findings, list) else []
            else:
                if self.verbose or self.debug:
                    print("[WARNING] No JSON array found in regression analysis response", file=sys.stderr)
                    print(f"[WARNING] Response preview: {response[:200]}...", file=sys.stderr)
        except json.JSONDecodeError as e:
            if self.verbose or self.debug:
                print(f"[ERROR] Failed to parse regression analysis JSON: {e}", file=sys.stderr)
                print(f"[ERROR] Response may be truncated. Last 100 chars: ...{response[-100:]}", file=sys.stderr)
                print(f"[ERROR] Increase ANALYZE_MAX_TOKENS in config.py (current: {config.ANALYZE_MAX_TOKENS})", file=sys.stderr)
                if self.dump_prompts:
                    print(f"[ERROR] Check dump files in {self.llm.dump_dir}/ for full response", file=sys.stderr)

        return []

    def _verify_findings(
        self,
        findings: List[Dict],
        context: Dict,
        commit: Commit
    ) -> List[Dict]:
        """
        Task 3: Verify findings using false-positive guide.

        Returns:
            Verified findings (false positives removed)
        """
        if not findings:
            return []

        # Load false positive prevention guide
        system_prompt = self.prompts.build_system_prompt(
            include_technical_patterns=True,
            include_false_positive_guide=True,
            subsystem_guides=[]
        )

        findings_text = json.dumps(findings, indent=2)

        user_prompt = f"""Verify these findings against the false-positive prevention guide.

For each finding, check:
1. Is there concrete evidence this can happen?
2. Is this defensive programming vs. a real bug?
3. Are all assumptions verified with code?

Commit diff:
{commit.diff}

Findings to verify:
{findings_text}

Return ONLY verified findings as JSON array (discard false positives):
[{{"category": "...", "type": "...", "message": "...", "evidence": "...", "severity": "..."}}]
"""

        response = self.llm.analyze_code(system_prompt, user_prompt, max_tokens=config.VERIFY_MAX_TOKENS)

        # Parse JSON response
        try:
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                verified = json.loads(json_match.group(0))
                return verified if isinstance(verified, list) else []
            else:
                if self.verbose or self.debug:
                    print("[WARNING] No JSON array found in verification response", file=sys.stderr)
                    print(f"[WARNING] Response preview: {response[:200]}...", file=sys.stderr)
                    print("[WARNING] Keeping original findings", file=sys.stderr)
                return findings
        except json.JSONDecodeError as e:
            if self.verbose or self.debug:
                print(f"[ERROR] Failed to parse verification JSON: {e}", file=sys.stderr)
                print(f"[ERROR] Response may be truncated. Last 100 chars: ...{response[-100:]}", file=sys.stderr)
                print(f"[ERROR] Increase VERIFY_MAX_TOKENS in config.py (current: {config.VERIFY_MAX_TOKENS})", file=sys.stderr)
                print("[WARNING] Keeping original findings to avoid losing data", file=sys.stderr)
            # If parsing fails, keep original findings rather than discarding
            return findings

        return []

    def _generate_summary(
        self,
        commit: Commit,
        findings: List[Dict],
        suse_verification: Optional[Dict] = None
    ) -> str:
        """
        Generate 1-2 sentence summary of review.

        Args:
            commit: Commit object
            findings: Verified findings
            suse_verification: SUSE upstream verification result (optional)

        Returns:
            Summary string
        """
        if not findings:
            base = "This commit appears correct with no regressions found."
            if suse_verification and suse_verification.get('upstream_commit'):
                upstream = suse_verification['upstream_commit']
                base += f" Verified against upstream: {upstream.subject}"
            return base

        count = len(findings)
        types = set(f.get('type', 'issue') for f in findings)

        # Check for upstream/downstream split
        if suse_verification:
            in_upstream = len(suse_verification.get('findings_in_upstream', []))
            downstream_only = len(suse_verification.get('findings_only_downstream', []))

            if downstream_only > 0:
                return (f"This commit has {count} potential issues, "
                       f"{downstream_only} unique to SUSE downstream that should be reviewed.")
            elif in_upstream > 0:
                return (f"This commit has {count} potential issues also present in upstream. "
                       f"Consider reporting to upstream maintainers.")

        # Default summary (existing logic)
        if count == 1:
            issue_type = findings[0].get('type', 'issue')
            return f"This commit has a potential {issue_type} that should be reviewed."
        else:
            types_str = ", ".join(sorted(types))
            return f"This commit has {count} potential issues ({types_str}) that should be reviewed."
