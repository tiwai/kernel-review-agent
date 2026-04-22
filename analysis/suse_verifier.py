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
        # Check if finding locations exist in upstream diff

        # First, do a sanity check: are the diffs similar?
        downstream_files = set(downstream_commit.files)
        upstream_files = set(upstream_commit.files)
        common_files = downstream_files & upstream_files

        if self.debug:
            print(f"[DEBUG] Downstream files: {downstream_files}")
            print(f"[DEBUG] Upstream files: {upstream_files}")
            print(f"[DEBUG] Common files: {common_files}")

        # If all downstream files are in upstream, likely all findings are in upstream
        if downstream_files and downstream_files.issubset(upstream_files):
            if self.debug:
                print(f"[DEBUG] All downstream files present in upstream - likely same changes")

        for finding in findings:
            if self._finding_exists_in_upstream(finding, upstream_commit, downstream_commit):
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
        upstream_commit: Commit,
        downstream_commit: Commit
    ) -> bool:
        """
        Determine if finding exists in upstream by comparing actual code changes.

        Uses multiple strategies:
        1. Check if finding's file location is modified in upstream
        2. Check if key code patterns from finding appear in upstream diff
        3. Look for similar changes in the same functions
        4. Compare downstream and upstream diffs for similarity

        Args:
            finding: Finding dictionary
            upstream_commit: Upstream commit
            downstream_commit: Downstream commit

        Returns:
            True if finding likely exists in upstream
        """
        # Strategy 0: Quick check - if diffs are very similar, it's the same change
        # Extract added lines from both diffs (lines starting with +)
        downstream_added = set()
        upstream_added = set()

        for line in downstream_commit.diff.split('\n'):
            if line.startswith('+') and not line.startswith('+++'):
                # Normalize: remove leading + and whitespace
                normalized = line[1:].strip()
                if normalized and len(normalized) > 3:
                    downstream_added.add(normalized)

        for line in upstream_commit.diff.split('\n'):
            if line.startswith('+') and not line.startswith('+++'):
                normalized = line[1:].strip()
                if normalized and len(normalized) > 3:
                    upstream_added.add(normalized)

        # If there's significant overlap in added lines, it's the same change
        if downstream_added and upstream_added:
            common_lines = downstream_added & upstream_added
            if len(common_lines) >= 2:  # At least 2 identical added lines
                if self.debug:
                    print(f"[DEBUG] Found {len(common_lines)} common added lines between downstream and upstream")
                return True

        # Strategy 1: Check if the finding's location matches upstream changes
        location = finding.get('location', '')
        category = finding.get('category', '')

        # Extract file from location (format: "file.c, function_name" or just "file.c")
        file_from_location = None
        if location:
            # Location format examples:
            # "net/ipv6/exthdrs.c, ipv6_srh_rcv"
            # "net/ipv6/seg6_hmac.c"
            parts = location.split(',')
            if parts:
                file_from_location = parts[0].strip()

        # Check if the file is modified in upstream
        if file_from_location and file_from_location in upstream_commit.files:
            if self.debug:
                print(f"[DEBUG] Finding location {file_from_location} is in upstream files")
            # File is modified in upstream, likely the same change
            return True

        # Strategy 2: Check evidence text
        evidence = finding.get('evidence', '')
        if evidence:
            # Extract code snippets from evidence (lines that look like code)
            code_lines = []
            for line in evidence.split('\n'):
                stripped = line.strip()
                # Look for actual code lines (not comments or descriptions)
                if stripped and len(stripped) > 5:
                    # Skip lines that are clearly descriptions
                    if not any(stripped.lower().startswith(word) for word in
                              ['the', 'this', 'shows', 'standard', 'pattern', 'caller', 'diff']):
                        code_lines.append(stripped)

            # Check if any code lines appear in upstream diff (with some flexibility)
            for code_line in code_lines:
                # Remove extra whitespace for better matching
                normalized_line = ' '.join(code_line.split())
                normalized_diff = ' '.join(upstream_commit.diff.split())

                if len(normalized_line) > 10 and normalized_line in normalized_diff:
                    if self.debug:
                        print(f"[DEBUG] Found matching code in upstream: {code_line[:50]}")
                    return True

        # Strategy 3: Check for similar changes in the same files
        # Extract changed lines from finding type/message
        finding_type = finding.get('type', '').lower()
        message = finding.get('message', '').lower()

        # Look for key indicators that suggest the same issue
        # e.g., "kfree_skb", "return false", "null check"
        key_patterns = []
        if 'kfree_skb' in message or 'kfree_skb' in evidence:
            key_patterns.append('kfree_skb')
        if 'return false' in message or 'return false' in evidence:
            key_patterns.append('return false')
        if 'return -1' in message or 'return -1' in evidence:
            key_patterns.append('return -1')
        if 'null check' in message or '!idev' in evidence:
            key_patterns.append('!idev')
            key_patterns.append('if (!idev')

        # Check if these patterns appear in upstream
        for pattern in key_patterns:
            if pattern in upstream_commit.diff:
                if self.debug:
                    print(f"[DEBUG] Found key pattern in upstream: {pattern}")
                return True

        # If we have no evidence and no location match, default to upstream
        # (better to over-report as upstream than miss upstream issues)
        if not evidence and not location:
            if self.verbose:
                print(f"[SUSE] No evidence or location for finding, defaulting to upstream")
            return True

        # No matches found
        return False
