"""Backport verification - compare downstream patches against upstream sources."""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from git_integration import Commit


@dataclass
class DiffHunk:
    """Represents a single diff hunk."""
    file_path: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    context_before: List[str]  # Lines before the change
    removed_lines: List[str]
    added_lines: List[str]
    context_after: List[str]   # Lines after the change


@dataclass
class BackportComparison:
    """Comparison between downstream and upstream patches."""
    has_upstream: bool
    upstream_commit: Optional[str]
    differences_found: bool
    needs_deep_review: bool

    # Specific differences
    file_path_changes: List[Tuple[str, str]]  # (upstream_path, downstream_path)
    line_number_shifts: List[Dict]  # Changes in line numbers
    context_mismatches: List[Dict]  # Context doesn't match
    missing_hunks: List[str]  # Hunks in upstream but not downstream
    extra_hunks: List[str]   # Hunks in downstream but not upstream

    summary: str  # Human-readable summary


class BackportVerifier:
    """Verify backport quality by comparing downstream vs upstream patches."""

    def __init__(self, upstream_repo=None, verbose: bool = False, debug: bool = False):
        """
        Initialize backport verifier.

        Args:
            upstream_repo: MultiRepoExtractor for upstream Linux kernel
            verbose: Enable verbose output
            debug: Enable debug output
        """
        self.upstream_repo = upstream_repo
        self.verbose = verbose
        self.debug = debug

    def compare_patches(self, downstream: Commit, upstream: Commit) -> BackportComparison:
        """
        Compare downstream and upstream patches.

        Args:
            downstream: Downstream commit
            upstream: Upstream commit

        Returns:
            BackportComparison with analysis
        """
        # Parse both diffs into hunks
        downstream_hunks = self._parse_diff_hunks(downstream.diff)
        upstream_hunks = self._parse_diff_hunks(upstream.diff)

        if self.debug:
            print(f"Downstream: {len(downstream_hunks)} hunks")
            print(f"Upstream: {len(upstream_hunks)} hunks")

        # Detect file path changes
        file_path_changes = self._detect_file_path_changes(downstream_hunks, upstream_hunks)

        # Detect line number shifts
        line_number_shifts = self._detect_line_shifts(downstream_hunks, upstream_hunks)

        # Detect context mismatches
        context_mismatches = self._detect_context_mismatches(downstream_hunks, upstream_hunks)

        # Detect missing/extra hunks
        missing_hunks = self._detect_missing_hunks(upstream_hunks, downstream_hunks)
        extra_hunks = self._detect_missing_hunks(downstream_hunks, upstream_hunks)

        # Determine if differences were found
        differences_found = bool(
            file_path_changes or
            line_number_shifts or
            context_mismatches or
            missing_hunks or
            extra_hunks
        )

        # Determine if deep review is needed
        # Deep review needed if:
        # - Context mismatches (patch applied to wrong location)
        # - Missing/extra hunks (incomplete backport)
        # - File path changes (different files modified)
        needs_deep_review = bool(
            context_mismatches or
            missing_hunks or
            extra_hunks or
            file_path_changes
        )

        # Generate summary
        summary = self._generate_summary(
            file_path_changes, line_number_shifts, context_mismatches,
            missing_hunks, extra_hunks, needs_deep_review
        )

        return BackportComparison(
            has_upstream=True,
            upstream_commit=upstream.sha,
            differences_found=differences_found,
            needs_deep_review=needs_deep_review,
            file_path_changes=file_path_changes,
            line_number_shifts=line_number_shifts,
            context_mismatches=context_mismatches,
            missing_hunks=missing_hunks,
            extra_hunks=extra_hunks,
            summary=summary
        )

    def _parse_diff_hunks(self, diff: str) -> List[DiffHunk]:
        """Parse unified diff into hunks."""
        hunks = []
        current_file = None
        current_hunk = None
        context_before = []
        removed = []
        added = []
        context_after = []
        in_change = False

        for line in diff.split('\n'):
            # File header: diff --git a/path b/path
            if line.startswith('diff --git'):
                match = re.match(r'^diff --git a/(.+) b/(.+)', line)
                if match:
                    current_file = match.group(2)  # Use 'b' path (after)

            # Hunk header: @@ -old_start,old_count +new_start,new_count @@
            elif line.startswith('@@'):
                # Save previous hunk if exists
                if current_hunk:
                    current_hunk.context_after = context_after[:]
                    hunks.append(current_hunk)
                    context_before = []
                    removed = []
                    added = []
                    context_after = []

                match = re.match(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
                if match and current_file:
                    old_start = int(match.group(1))
                    old_count = int(match.group(2)) if match.group(2) else 1
                    new_start = int(match.group(3))
                    new_count = int(match.group(4)) if match.group(4) else 1

                    current_hunk = DiffHunk(
                        file_path=current_file,
                        old_start=old_start,
                        old_count=old_count,
                        new_start=new_start,
                        new_count=new_count,
                        context_before=[],
                        removed_lines=[],
                        added_lines=[],
                        context_after=[]
                    )
                    in_change = False

            # Context, removed, or added lines
            elif current_hunk and (line.startswith(' ') or line.startswith('-') or line.startswith('+')):
                if line.startswith('-'):
                    in_change = True
                    removed.append(line[1:])  # Remove '-' prefix
                    current_hunk.removed_lines = removed[:]
                elif line.startswith('+'):
                    in_change = True
                    added.append(line[1:])  # Remove '+' prefix
                    current_hunk.added_lines = added[:]
                elif line.startswith(' '):
                    # Context line
                    if not in_change:
                        # Before the change
                        context_before.append(line[1:])
                        current_hunk.context_before = context_before[:]
                    else:
                        # After the change
                        context_after.append(line[1:])

        # Save last hunk
        if current_hunk:
            current_hunk.context_after = context_after[:]
            hunks.append(current_hunk)

        return hunks

    def _detect_file_path_changes(self, downstream_hunks: List[DiffHunk],
                                   upstream_hunks: List[DiffHunk]) -> List[Tuple[str, str]]:
        """Detect file path changes between upstream and downstream."""
        downstream_files = {h.file_path for h in downstream_hunks}
        upstream_files = {h.file_path for h in upstream_hunks}

        # Files that are different
        changes = []

        # Check for renames or different paths
        if downstream_files != upstream_files:
            only_downstream = downstream_files - upstream_files
            only_upstream = upstream_files - downstream_files

            # Try to match similar paths
            for up_file in only_upstream:
                for down_file in only_downstream:
                    # Same basename but different path
                    if up_file.split('/')[-1] == down_file.split('/')[-1]:
                        changes.append((up_file, down_file))

        return changes

    def _detect_line_shifts(self, downstream_hunks: List[DiffHunk],
                           upstream_hunks: List[DiffHunk]) -> List[Dict]:
        """Detect line number shifts (patch applied at different line numbers)."""
        shifts = []

        # Group hunks by file
        downstream_by_file = {}
        upstream_by_file = {}

        for h in downstream_hunks:
            downstream_by_file.setdefault(h.file_path, []).append(h)

        for h in upstream_hunks:
            upstream_by_file.setdefault(h.file_path, []).append(h)

        # Compare hunks in same file
        common_files = set(downstream_by_file.keys()) & set(upstream_by_file.keys())

        for file_path in common_files:
            down_hunks = downstream_by_file[file_path]
            up_hunks = upstream_by_file[file_path]

            # For each upstream hunk, find matching downstream hunk
            for up_h in up_hunks:
                # Find best match based on content similarity
                best_match = self._find_matching_hunk(up_h, down_hunks)

                if best_match:
                    # Check if line numbers differ significantly
                    line_diff = abs(best_match.new_start - up_h.new_start)

                    if line_diff > 5:  # More than 5 lines shifted
                        shifts.append({
                            'file': file_path,
                            'upstream_line': up_h.new_start,
                            'downstream_line': best_match.new_start,
                            'shift': line_diff,
                            'direction': 'down' if best_match.new_start > up_h.new_start else 'up'
                        })

        return shifts

    def _detect_context_mismatches(self, downstream_hunks: List[DiffHunk],
                                   upstream_hunks: List[DiffHunk]) -> List[Dict]:
        """Detect context mismatches (patch applied to different code)."""
        mismatches = []

        # Group by file
        downstream_by_file = {}
        upstream_by_file = {}

        for h in downstream_hunks:
            downstream_by_file.setdefault(h.file_path, []).append(h)

        for h in upstream_hunks:
            upstream_by_file.setdefault(h.file_path, []).append(h)

        common_files = set(downstream_by_file.keys()) & set(upstream_by_file.keys())

        for file_path in common_files:
            down_hunks = downstream_by_file[file_path]
            up_hunks = upstream_by_file[file_path]

            for up_h in up_hunks:
                best_match = self._find_matching_hunk(up_h, down_hunks)

                if best_match:
                    # Compare context lines
                    context_match = self._compare_context(up_h, best_match)

                    if context_match < 0.7:  # Less than 70% context match
                        mismatches.append({
                            'file': file_path,
                            'upstream_line': up_h.new_start,
                            'downstream_line': best_match.new_start,
                            'match_score': context_match,
                            'upstream_context': up_h.context_before + up_h.context_after,
                            'downstream_context': best_match.context_before + best_match.context_after
                        })

        return mismatches

    def _detect_missing_hunks(self, reference_hunks: List[DiffHunk],
                             comparison_hunks: List[DiffHunk]) -> List[str]:
        """Detect hunks in reference that are missing in comparison."""
        missing = []

        # Group by file
        comparison_by_file = {}
        for h in comparison_hunks:
            comparison_by_file.setdefault(h.file_path, []).append(h)

        for ref_h in reference_hunks:
            comparison_hunks_in_file = comparison_by_file.get(ref_h.file_path, [])

            # Try to find matching hunk
            match = self._find_matching_hunk(ref_h, comparison_hunks_in_file)

            if not match:
                # No match found - hunk is missing
                missing.append(f"{ref_h.file_path}:{ref_h.new_start}")

        return missing

    def _find_matching_hunk(self, target: DiffHunk, candidates: List[DiffHunk]) -> Optional[DiffHunk]:
        """Find the best matching hunk from candidates."""
        best_match = None
        best_score = 0.0

        for candidate in candidates:
            # Compare added/removed lines
            score = self._compare_hunk_content(target, candidate)

            if score > best_score and score > 0.5:  # At least 50% match
                best_score = score
                best_match = candidate

        return best_match

    def _compare_hunk_content(self, h1: DiffHunk, h2: DiffHunk) -> float:
        """Compare content similarity between two hunks."""
        # Compare added lines
        added_match = self._line_similarity(h1.added_lines, h2.added_lines)

        # Compare removed lines
        removed_match = self._line_similarity(h1.removed_lines, h2.removed_lines)

        # Average score
        return (added_match + removed_match) / 2.0

    def _compare_context(self, h1: DiffHunk, h2: DiffHunk) -> float:
        """Compare context similarity between two hunks."""
        context1 = h1.context_before + h1.context_after
        context2 = h2.context_before + h2.context_after

        return self._line_similarity(context1, context2)

    def _line_similarity(self, lines1: List[str], lines2: List[str]) -> float:
        """Calculate similarity between two lists of lines."""
        if not lines1 and not lines2:
            return 1.0
        if not lines1 or not lines2:
            return 0.0

        # Simple character-based similarity
        text1 = '\n'.join(lines1)
        text2 = '\n'.join(lines2)

        # Count matching characters
        matches = sum(1 for c1, c2 in zip(text1, text2) if c1 == c2)
        total = max(len(text1), len(text2))

        return matches / total if total > 0 else 0.0

    def _generate_summary(self, file_path_changes, line_number_shifts,
                         context_mismatches, missing_hunks, extra_hunks,
                         needs_deep_review) -> str:
        """Generate human-readable summary."""
        parts = []

        if not (file_path_changes or line_number_shifts or context_mismatches or
                missing_hunks or extra_hunks):
            return "Downstream patch matches upstream exactly (clean backport)"

        if file_path_changes:
            parts.append(f"{len(file_path_changes)} file path difference(s)")

        if line_number_shifts:
            parts.append(f"{len(line_number_shifts)} line number shift(s)")

        if context_mismatches:
            parts.append(f"{len(context_mismatches)} context mismatch(es)")

        if missing_hunks:
            parts.append(f"{len(missing_hunks)} missing hunk(s)")

        if extra_hunks:
            parts.append(f"{len(extra_hunks)} extra hunk(s)")

        summary = "Backport differences detected: " + ", ".join(parts)

        if needs_deep_review:
            summary += " → NEEDS DEEP REVIEW"

        return summary

    def verify_backport(self, downstream: Commit) -> Optional[BackportComparison]:
        """
        Verify backport quality for a downstream commit.

        Args:
            downstream: Downstream commit to verify

        Returns:
            BackportComparison if upstream commit found, None otherwise
        """
        # Check if commit has upstream reference
        if not downstream.upstream_commit:
            return BackportComparison(
                has_upstream=False,
                upstream_commit=None,
                differences_found=False,
                needs_deep_review=False,
                file_path_changes=[],
                line_number_shifts=[],
                context_mismatches=[],
                missing_hunks=[],
                extra_hunks=[],
                summary="No upstream commit reference found"
            )

        # Fetch upstream commit
        if not self.upstream_repo or not self.upstream_repo.is_available():
            if self.verbose:
                print(f"  Warning: Upstream repository not available, cannot verify backport")
            return None

        upstream = self.upstream_repo.get_commit(downstream.upstream_commit)
        if not upstream:
            if self.verbose:
                print(f"  Warning: Upstream commit {downstream.upstream_commit[:12]} not found")
            return None

        if self.verbose:
            print(f"  Comparing with upstream: {upstream.sha[:12]}")

        # Compare patches
        return self.compare_patches(downstream, upstream)
