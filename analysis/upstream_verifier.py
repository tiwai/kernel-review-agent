"""Upstream commit verification for kernel backport review."""

import sys
from typing import List, Dict, Optional
from git_integration import Commit, MultiRepoExtractor, CommitExtractor


class UpstreamVerifier:
    """Verify findings against upstream Linux kernel commits."""

    def __init__(
        self,
        kernel_source_repo: Optional[str] = None,
        upstream_repo: Optional[str] = None,
        llm_client: Optional[object] = None,
        verbose: bool = False,
        debug: bool = False
    ):
        """
        Initialize upstream verifier.

        Args:
            kernel_source_repo: Path to an intermediate patch repository (e.g. SUSE kernel-source)
            upstream_repo: Path to upstream Linux kernel repository
            llm_client: LLM client for semantic verification
            verbose: Enable verbose output
            debug: Enable debug output
        """
        self.verbose = verbose
        self.debug = debug
        self.llm = llm_client

        # Initialize repo extractors if paths provided
        self.kernel_source = None
        self.upstream = None

        if kernel_source_repo:
            self.kernel_source = MultiRepoExtractor(kernel_source_repo, verbose)
            if debug:
                available = self.kernel_source.is_available()
                print(f"Patch repo: {kernel_source_repo} (available: {available})")

        if upstream_repo:
            self.upstream = MultiRepoExtractor(upstream_repo, verbose)
            if debug:
                available = self.upstream.is_available()
                print(f"Upstream Linux repo: {upstream_repo} (available: {available})")

    def is_enabled(self) -> bool:
        """Check if upstream verification is enabled and available."""
        if self.upstream is not None and self.upstream.is_available():
            return True
        if self.kernel_source is not None and self.kernel_source.is_available():
            return True
        return False

    def should_verify(self, commit: Commit, findings: List[Dict]) -> bool:
        """
        Determine if upstream verification should run.

        Args:
            commit: Commit being reviewed
            findings: Findings from Task 2

        Returns:
            True if verification should run
        """
        if not findings or len(findings) == 0:
            return False

        # Check if commit has either distro-commit or upstream reference
        if not commit.distro_commit and not commit.upstream_commit:
            return False

        # If only distro-commit tag, need the patch repository
        if commit.distro_commit and not commit.upstream_commit:
            if not (self.kernel_source and self.kernel_source.is_available()):
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
        1. Extract distro-commit SHA from downstream commit (if present)
        2. Fetch that commit from patch repository
        3. Extract upstream SHA from patch repository commit
        4. Fetch upstream commit (from upstream repo or current repo)
        5. Compare findings against upstream diff

        Args:
            downstream_commit: Downstream commit being reviewed
            findings: Findings from regression analysis

        Returns:
            Verification result dictionary with:
            - distro_commit: Intermediate patch repository commit object (if used)
            - upstream_commit: Upstream Linux commit object
            - findings_in_upstream: List of findings present in upstream
            - findings_only_downstream: List of findings only in downstream
        """
        if self.verbose:
            print(f"\n[upstream] Verifying against upstream...")

        if self.debug:
            print(f"Upstream verification starting for commit {downstream_commit.sha[:12]}")
            print(f"distro-commit tag: {downstream_commit.distro_commit}")
            print(f"upstream commit (direct): {downstream_commit.upstream_commit}")

        result = {
            'distro_commit': None,
            'upstream_commit': None,
            'findings_in_upstream': [],
            'findings_only_downstream': []
        }

        # Determine upstream commit SHA
        upstream_sha = None

        # Path 1: Direct upstream reference in downstream commit
        if downstream_commit.upstream_commit:
            upstream_sha = downstream_commit.upstream_commit
            if self.verbose:
                print(f"[upstream] Using direct upstream reference: {upstream_sha[:12]}")

        # Path 2: distro-commit tag → patch repo → upstream reference
        elif downstream_commit.distro_commit:
            if not self.kernel_source:
                if self.verbose:
                    print("[upstream] patch repository not configured, skipping")
                return result

            distro_commit = self.kernel_source.get_commit(downstream_commit.distro_commit)
            if not distro_commit:
                if self.verbose:
                    print(f"[upstream] Warning: Could not fetch distro-commit {downstream_commit.distro_commit[:12]}")
                return result

            result['distro_commit'] = distro_commit

            if self.debug:
                print(f"Found distro commit: {distro_commit.subject}")
                print(f"Upstream reference from patch repo: {distro_commit.upstream_commit}")

            if not distro_commit.upstream_commit:
                if self.verbose:
                    print("[upstream] No upstream reference found in patch repo commit")
                # All findings are downstream-only
                result['findings_only_downstream'] = findings
                return result

            upstream_sha = distro_commit.upstream_commit

        # No upstream SHA available
        if not upstream_sha:
            result['findings_only_downstream'] = findings
            return result

        # Fetch upstream commit
        upstream_commit = None

        if self.upstream and self.upstream.is_available():
            upstream_commit = self.upstream.get_commit(upstream_sha)
            if self.debug and upstream_commit:
                print(f"Fetched upstream commit from upstream repo")

        # Fallback: try current repository (might be Linux kernel)
        if not upstream_commit:
            try:
                local_git = CommitExtractor(verbose=self.verbose)
                upstream_commit = local_git.get_commit(upstream_sha)
                if self.debug and upstream_commit:
                    print(f"Fetched upstream commit from current repo")
            except Exception:
                pass

        if not upstream_commit:
            if self.verbose:
                print(f"[upstream] Warning: Could not fetch upstream commit {upstream_sha[:12]}")
            # Treat all findings as downstream-only
            result['findings_only_downstream'] = findings
            return result

        result['upstream_commit'] = upstream_commit

        if self.verbose:
            print(f"[upstream] Upstream: {upstream_commit.subject}")

        # Compare findings against upstream
        downstream_files = set(downstream_commit.files)
        upstream_files = set(upstream_commit.files)
        common_files = downstream_files & upstream_files

        if self.debug:
            print(f"Downstream files: {downstream_files}")
            print(f"Upstream files: {upstream_files}")
            print(f"Common files: {common_files}")

        if downstream_files and downstream_files.issubset(upstream_files):
            if self.debug:
                print(f"All downstream files present in upstream - likely same changes")

        for finding in findings:
            if self._finding_exists_in_upstream(finding, upstream_commit, downstream_commit):
                result['findings_in_upstream'].append(finding)
            else:
                result['findings_only_downstream'].append(finding)

        if self.verbose:
            print(f"[upstream] Findings in upstream: {len(result['findings_in_upstream'])}")
            print(f"[upstream] Findings only in downstream: {len(result['findings_only_downstream'])}")

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
        # Strategy 0: First check if the specific evidence from this finding exists in upstream
        evidence = finding.get('evidence', '')
        # Handle both string and list types for evidence (LLM might return either)
        if isinstance(evidence, list):
            evidence = '\n'.join(str(item) for item in evidence)
        if evidence:
            # Extract code snippets from evidence (lines that look like code)
            evidence_code_lines = []
            for line in evidence.split('\n'):
                stripped = line.strip()
                # Look for actual code lines (not comments or descriptions or ellipsis)
                if stripped and len(stripped) > 5 and stripped != '...':
                    # Skip lines that are clearly descriptions
                    if not any(stripped.lower().startswith(word) for word in
                              ['the', 'this', 'shows', 'standard', 'pattern', 'caller', 'diff']):
                        evidence_code_lines.append(stripped)

            # Check if ALL evidence lines appear in upstream diff
            if evidence_code_lines:
                normalized_upstream = ' '.join(upstream_commit.diff.split())
                matched_lines = []
                unmatched_lines = []

                for code_line in evidence_code_lines:
                    normalized_line = ' '.join(code_line.split())

                    if len(normalized_line) > 10 and normalized_line in normalized_upstream:
                        matched_lines.append(code_line)
                        if self.debug:
                            print(f"Evidence found in upstream: {code_line[:60]}")
                    else:
                        unmatched_lines.append(code_line)

                if unmatched_lines:
                    if self.verbose or self.debug:
                        print(f"[upstream] Evidence not found in upstream - downstream-only bug")
                        if self.debug:
                            print(f"Matched lines: {len(matched_lines)}")
                            print(f"Unmatched lines: {len(unmatched_lines)}")
                            for line in unmatched_lines[:2]:
                                print(f"  Missing: {line[:60]}")
                    return False

        # Strategy 0b: Compare diffs for similarity and completeness
        downstream_added = set()
        upstream_added = set()

        for line in downstream_commit.diff.split('\n'):
            if line.startswith('+') and not line.startswith('+++'):
                normalized = line[1:].strip()
                if normalized and len(normalized) > 3:
                    downstream_added.add(normalized)

        for line in upstream_commit.diff.split('\n'):
            if line.startswith('+') and not line.startswith('+++'):
                normalized = line[1:].strip()
                if normalized and len(normalized) > 3:
                    upstream_added.add(normalized)

        if downstream_added and upstream_added:
            common_lines = downstream_added & upstream_added
            missing_in_downstream = upstream_added - downstream_added
            extra_in_downstream = downstream_added - upstream_added

            if self.debug:
                print(f"Diff comparison:")
                print(f"  Common lines: {len(common_lines)}")
                print(f"  Missing in downstream: {len(missing_in_downstream)}")
                print(f"  Extra in downstream: {len(extra_in_downstream)}")
                if missing_in_downstream:
                    print(f"  Missing lines: {list(missing_in_downstream)[:3]}")
                if extra_in_downstream:
                    print(f"  Extra lines: {list(extra_in_downstream)[:3]}")

            total_upstream = len(upstream_added)
            if total_upstream > 0:
                similarity = len(common_lines) / total_upstream

                if similarity < 0.8:
                    if self.debug:
                        print(f"Incomplete backport: only {similarity:.1%} similarity")
                    return False

                critical_keywords = {'goto', 'return', 'break', 'continue', 'unlock', 'free'}
                for missing_line in missing_in_downstream:
                    words = missing_line.lower().split()
                    if any(keyword in words for keyword in critical_keywords):
                        if self.verbose or self.debug:
                            print(f"[upstream] Incomplete backport: missing critical line: {missing_line}")
                        return False

            if len(common_lines) >= 2:
                if self._has_use_after_free_pattern(downstream_commit.diff):
                    if self.verbose or self.debug:
                        print(f"[upstream] Potential use-after-free pattern detected in downstream")
                    return False

                if self.debug:
                    print(f"Substantial overlap: {len(common_lines)} common lines")
                return True

        # Strategy 1: Check if the finding's location matches upstream changes
        location = finding.get('location', '')

        file_from_location = None
        if location:
            parts = location.split(',')
            if parts:
                file_from_location = parts[0].strip()

        if file_from_location and file_from_location in upstream_commit.files:
            if self.debug:
                print(f"Finding location {file_from_location} is in upstream files")
            return True

        # Strategy 2: Check for key patterns in the same files
        finding_type = finding.get('type', '').lower()
        message = finding.get('message', '').lower()

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

        for pattern in key_patterns:
            if pattern in upstream_commit.diff:
                if self.debug:
                    print(f"Found key pattern in upstream: {pattern}")
                return True

        # Strategy 3: Semantic Verification using LLM
        if self.llm:
            if self.debug:
                print(f"Falling back to semantic verification for {finding.get('type')}")

            return self._verify_finding_semantically(finding, upstream_commit, downstream_commit)

        if not evidence and not location:
            if self.verbose:
                print(f"[upstream] No evidence or location for finding, defaulting to upstream")
            return True

        return False

    def _has_use_after_free_pattern(self, diff: str) -> bool:
        """
        Check for dangerous patterns where memory is assigned then immediately freed.

        Pattern: ptr = allocation; ... free(ptr); without control flow in between.
        This catches incomplete backports that are missing goto/return statements.

        Args:
            diff: Diff content to check

        Returns:
            True if dangerous pattern found
        """
        lines = diff.split('\n')

        for i, line in enumerate(lines):
            if not line or line[0] not in ['+', '-', ' ']:
                continue

            if ' = ' in line and not line.startswith('-'):
                stripped = line[1:] if line[0] in ['+', ' '] else line
                stripped = stripped.strip()

                if '=' in stripped:
                    lhs = stripped.split('=')[0].strip()

                    for j in range(i + 1, min(i + 11, len(lines))):
                        next_line = lines[j]
                        if not next_line or next_line[0] not in ['+', '-', ' ']:
                            continue

                        next_stripped = next_line[1:] if next_line[0] in ['+', ' '] else next_line
                        next_stripped = next_stripped.strip()

                        if any(kw in next_stripped for kw in ['goto ', 'return', 'break']):
                            break

                        if 'free(' in next_stripped or 'kfree(' in next_stripped:
                            rhs = stripped.split('=')[1].strip().rstrip(';')
                            if rhs in next_stripped:
                                if self.debug:
                                    print(f"Found use-after-free pattern:")
                                    print(f"  Assignment: {stripped}")
                                    print(f"  Free: {next_stripped}")
                                return True

        return False

    def _verify_finding_semantically(
        self,
        finding: Dict,
        upstream_commit: Commit,
        downstream_commit: Commit
    ) -> bool:
        """Use LLM to semantically compare upstream and downstream diffs."""
        system_prompt = """You are a Linux kernel maintainer verifying if a bug found
in a kernel backport is also present in the original upstream commit.

Backports often have slight context shifts (line numbers, variable renaming, or
different surrounding code), but the underlying logic defect might be the same.

Your goal is to determine if the logic defect described in the finding exists
in the upstream diff."""

        # Normalize evidence to handle both string and list types
        evidence = finding.get('evidence', '')
        if isinstance(evidence, list):
            evidence = '\n'.join(str(item) for item in evidence)

        user_prompt = f"""FINDING DESCRIPTION:
Type: {finding.get('type')}
Message: {finding.get('message')}
Evidence: {evidence}

DOWNSTREAM DIFF:
{downstream_commit.diff[:2000]}

UPSTREAM DIFF:
{upstream_commit.diff[:2000]}

Task: Does the underlying logic defect described in the finding also exist in the UPSTREAM diff?
Even if the code is slightly different, is the BUG the same?

Answer ONLY: YES or NO."""

        try:
            response = self.llm.analyze_code(system_prompt, user_prompt, max_tokens=1000)
            return 'yes' in response.lower()
        except Exception as e:
            if self.debug:
                print(f"Semantic upstream verification failed: {e}")
            return True  # Default to True (upstream) to avoid over-reporting downstream-only bugs


# Backward-compatible alias
SuseUpstreamVerifier = UpstreamVerifier
