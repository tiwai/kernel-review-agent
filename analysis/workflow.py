"""Main review workflow orchestration (5-task protocol)."""

import json
import re
from typing import List, Dict, Optional
from dataclasses import dataclass

from git_integration import Commit
from llm_integration import OpenAIClient
from prompt_management import PromptLoader, SubsystemMatcher


@dataclass
class ReviewResult:
    """Review result containing findings and metadata."""
    findings: List[Dict]
    summary: str
    subsystems_loaded: List[str]


class ReviewWorkflow:
    """Orchestrate 5-task review protocol."""

    def __init__(
        self,
        llm_client: OpenAIClient,
        prompt_loader: PromptLoader,
        subsystem_matcher: SubsystemMatcher,
        verbose: bool = False
    ):
        """
        Initialize review workflow.

        Args:
            llm_client: LLM client for API calls
            prompt_loader: Prompt loader
            subsystem_matcher: Subsystem matcher
            verbose: Enable verbose output
        """
        self.llm = llm_client
        self.prompts = prompt_loader
        self.matcher = subsystem_matcher
        self.verbose = verbose

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
        context = self._gather_context(commit)

        # Match subsystems
        subsystems = self.matcher.match_diff(commit.files, commit.diff)
        if self.verbose and subsystems:
            print(f"      Matched subsystems: {', '.join(subsystems)}")

        # Task 1: Categorize changes (LLM-driven)
        if self.verbose:
            print("\n[2/5] Categorizing changes...")
        categories = self._categorize_changes(commit, context)
        if self.verbose:
            print(f"      Found {len(categories)} change categories")

        # Task 2: Analyze for regressions (LLM-driven)
        if self.verbose:
            print("\n[3/5] Analyzing for regressions...")
        findings = self._analyze_regressions(commit, categories, context, subsystems)
        if self.verbose:
            print(f"      Found {len(findings)} potential issues")

        # Task 3: Verify findings (eliminate false positives)
        if self.verbose:
            print("\n[4/5] Verifying findings...")
        verified = self._verify_findings(findings, context, commit)
        if self.verbose:
            print(f"      {len(verified)} issues after verification")

        # Task 4: Generate summary
        if self.verbose:
            print("\n[5/5] Generating summary...")
        summary = self._generate_summary(commit, verified)

        if self.verbose:
            print(f"\nReview complete: {len(verified)} issue(s) found\n")

        return ReviewResult(
            findings=verified,
            summary=summary,
            subsystems_loaded=subsystems
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

        response = self.llm.analyze_code(system_prompt, user_prompt, max_tokens=4000)

        # Parse JSON response
        try:
            # Extract JSON from response (may have markdown code blocks)
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                categories = json.loads(json_match.group(0))
                return categories if isinstance(categories, list) else []
        except json.JSONDecodeError:
            if self.verbose:
                print("Warning: Failed to parse categorization JSON")

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

        response = self.llm.analyze_code(system_prompt, user_prompt, max_tokens=8000)

        # Parse JSON response
        try:
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                findings = json.loads(json_match.group(0))
                return findings if isinstance(findings, list) else []
        except json.JSONDecodeError:
            if self.verbose:
                print("Warning: Failed to parse analysis JSON")

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

        response = self.llm.analyze_code(system_prompt, user_prompt, max_tokens=8000)

        # Parse JSON response
        try:
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                verified = json.loads(json_match.group(0))
                return verified if isinstance(verified, list) else []
        except json.JSONDecodeError:
            if self.verbose:
                print("Warning: Failed to parse verification JSON, keeping original findings")
            # If parsing fails, keep original findings rather than discarding
            return findings

        return []

    def _generate_summary(self, commit: Commit, findings: List[Dict]) -> str:
        """
        Generate 1-2 sentence summary of review.

        Args:
            commit: Commit object
            findings: Verified findings

        Returns:
            Summary string
        """
        if not findings:
            return "This commit appears correct with no regressions found."

        count = len(findings)
        types = set(f.get('type', 'issue') for f in findings)

        if count == 1:
            issue_type = findings[0].get('type', 'issue')
            return f"This commit has a potential {issue_type} that should be reviewed."
        else:
            types_str = ", ".join(sorted(types))
            return f"This commit has {count} potential issues ({types_str}) that should be reviewed."
