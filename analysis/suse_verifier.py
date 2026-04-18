"""SUSE kernel upstream commit verification."""

import sys
from typing import List, Dict, Optional
from git_integration import Commit, MultiRepoExtractor, CommitExtractor


class SuseUpstreamVerifier:
    """Verify findings against upstream Linux kernel commits."""

    def __init__(
        self,
        kernel_source_repo: Optional[str] = None,
        upstream_repo: Optional[str] = None,
        verbose: bool = False,
        debug: bool = False
    ):
        """
        Initialize SUSE upstream verifier.

        Args:
            kernel_source_repo: Path to SUSE kernel-source repository
            upstream_repo: Path to upstream Linux kernel repository
            verbose: Enable verbose output
            debug: Enable debug output
        """
        self.verbose = verbose
        self.debug = debug

        # Initialize repo extractors if paths provided
        self.kernel_source = None
        self.upstream = None

        if kernel_source_repo:
            self.kernel_source = MultiRepoExtractor(kernel_source_repo, verbose)
            if debug:
                available = self.kernel_source.is_available()
                print(f"[DEBUG] SUSE kernel-source repo: {kernel_source_repo} (available: {available})")

        if upstream_repo:
            self.upstream = MultiRepoExtractor(upstream_repo, verbose)
            if debug:
                available = self.upstream.is_available()
                print(f"[DEBUG] Upstream Linux repo: {upstream_repo} (available: {available})")

    def is_enabled(self) -> bool:
        """Check if SUSE verification is enabled and available."""
        return self.kernel_source is not None and self.kernel_source.is_available()

    def should_verify(self, commit: Commit, findings: List[Dict]) -> bool:
        """
        Determine if upstream verification should run.

        Args:
            commit: Commit being reviewed
            findings: Findings from Task 2

        Returns:
            True if verification should run
        """
        # Only verify if:
        # 1. Commit has suse-commit OR Git-commit tag
        # 2. There are findings to verify
        # Note: SUSE repos don't need to be configured if Git-commit is present directly

        if not findings or len(findings) == 0:
            return False

        # Check if commit has either suse-commit or Git-commit tag
        if not commit.suse_commit and not commit.upstream_commit:
            return False

        # If only suse-commit tag, need SUSE kernel-source repo
        if commit.suse_commit and not commit.upstream_commit:
            if not self.is_enabled():
                return False

        return True

    def verify_against_upstream(
        self,
        downstream_commit: Commit,
        findings: List[Dict]
    ) -> Dict:
        """
        Verify findings against upstream commit.

        Workflow:
        1. Extract suse-commit SHA from downstream commit
        2. Fetch that commit from kernel-source repo
        3. Extract Git-commit SHA from kernel-source commit
        4. Fetch upstream commit (from upstream repo or current repo)
        5. Compare findings against upstream diff

        Args:
            downstream_commit: SUSE downstream commit being reviewed
            findings: Findings from regression analysis

        Returns:
            Verification result dictionary with:
            - suse_commit: SUSE kernel-source commit object
            - upstream_commit: Upstream Linux commit object
            - findings_in_upstream: List of findings present in upstream
            - findings_only_downstream: List of findings only in downstream
        """
        if self.verbose:
            print(f"\n[SUSE] Verifying against upstream...")

        if self.debug:
            print(f"[DEBUG] SUSE verification starting for commit {downstream_commit.sha[:12]}")
            print(f"[DEBUG] suse-commit tag: {downstream_commit.suse_commit}")
            print(f"[DEBUG] Git-commit tag (direct): {downstream_commit.upstream_commit}")

        result = {
            'suse_commit': None,
            'upstream_commit': None,
            'findings_in_upstream': [],
            'findings_only_downstream': []
        }

        # Determine upstream commit SHA
        upstream_sha = None

        # Path 1: Direct Git-commit tag in downstream commit
        if downstream_commit.upstream_commit:
            upstream_sha = downstream_commit.upstream_commit
            if self.verbose:
                print(f"[SUSE] Using direct Git-commit tag: {upstream_sha[:12]}")

        # Path 2: suse-commit tag → SUSE kernel-source → Git-commit tag
        elif downstream_commit.suse_commit:
            if not self.kernel_source:
                if self.verbose:
                    print("[SUSE] kernel-source repository not configured, skipping")
                return result

            suse_commit = self.kernel_source.get_commit(downstream_commit.suse_commit)
            if not suse_commit:
                if self.verbose:
                    print(f"[SUSE] Warning: Could not fetch suse-commit {downstream_commit.suse_commit[:12]}")
                return result

            result['suse_commit'] = suse_commit

            if self.debug:
                print(f"[DEBUG] Found SUSE commit: {suse_commit.subject}")
                print(f"[DEBUG] Git-commit tag from SUSE: {suse_commit.upstream_commit}")

            if not suse_commit.upstream_commit:
                if self.verbose:
                    print("[SUSE] No Git-commit tag found in SUSE commit")
                # All findings are downstream-only
                result['findings_only_downstream'] = findings
                return result

            upstream_sha = suse_commit.upstream_commit

        # No upstream SHA available
        if not upstream_sha:
            result['findings_only_downstream'] = findings
            return result

        # Fetch upstream commit
        upstream_commit = None

        if self.upstream and self.upstream.is_available():
            upstream_commit = self.upstream.get_commit(upstream_sha)
            if self.debug and upstream_commit:
                print(f"[DEBUG] Fetched upstream commit from upstream repo")

        # Fallback: try current repository (might be Linux kernel)
        if not upstream_commit:
            try:
                local_git = CommitExtractor(verbose=self.verbose)
                upstream_commit = local_git.get_commit(upstream_sha)
                if self.debug and upstream_commit:
                    print(f"[DEBUG] Fetched upstream commit from current repo")
            except Exception:
                pass

        if not upstream_commit:
            if self.verbose:
                print(f"[SUSE] Warning: Could not fetch upstream commit {upstream_sha[:12]}")
            # Treat all findings as downstream-only
            result['findings_only_downstream'] = findings
            return result

        result['upstream_commit'] = upstream_commit

        if self.verbose:
            print(f"[SUSE] Upstream: {upstream_commit.subject}")

        # Step 5: Compare findings against upstream
        # Simple heuristic: check if finding locations exist in upstream diff
        for finding in findings:
            if self._finding_exists_in_upstream(finding, upstream_commit):
                result['findings_in_upstream'].append(finding)
            else:
                result['findings_only_downstream'].append(finding)

        if self.verbose:
            print(f"[SUSE] Findings in upstream: {len(result['findings_in_upstream'])}")
            print(f"[SUSE] Findings only in downstream: {len(result['findings_only_downstream'])}")

        return result

    def _finding_exists_in_upstream(
        self,
        finding: Dict,
        upstream_commit: Commit
    ) -> bool:
        """
        Heuristic to determine if finding exists in upstream.

        Checks if the code patterns mentioned in the finding's evidence
        appear in the upstream diff.

        Args:
            finding: Finding dictionary
            upstream_commit: Upstream commit

        Returns:
            True if finding likely exists in upstream
        """
        evidence = finding.get('evidence', '')
        if not evidence:
            # No evidence to check, assume downstream-only
            return False

        # Simple substring check: does evidence code appear in upstream diff?
        # More sophisticated: could use fuzzy matching or AST comparison

        # Extract code snippets from evidence (lines that look like code)
        code_lines = [
            line.strip()
            for line in evidence.split('\n')
            if line.strip() and not line.strip().startswith('//')
        ]

        # Check if any code lines appear in upstream diff
        for code_line in code_lines:
            if len(code_line) > 10 and code_line in upstream_commit.diff:
                return True

        return False
