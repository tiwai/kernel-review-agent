"""Extract commits and diffs from git repository."""

import subprocess
import re
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class Commit:
    """Represents a git commit with metadata and diff."""
    sha: str
    author: str
    date: str
    subject: str
    message: str
    diff: str
    files: List[str]


class CommitExtractor:
    """Extract commit information from git repository."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def _run_git(self, args: List[str]) -> str:
        """Run git command and return output."""
        try:
            result = subprocess.run(
                ['git'] + args,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Git command failed: {e.stderr}")

    def is_git_repo(self) -> bool:
        """Check if current directory is a git repository."""
        try:
            self._run_git(['rev-parse', '--git-dir'])
            return True
        except RuntimeError:
            return False

    def expand_range(self, range_spec: str) -> List[str]:
        """
        Convert git range to list of commit SHAs.

        Examples:
            "HEAD~5..HEAD" -> ['sha1', 'sha2', 'sha3', 'sha4', 'sha5']
            "abc123..def456" -> ['commit1', 'commit2', ...]
        """
        if '..' not in range_spec:
            # Single commit
            return [range_spec]

        # Git rev-list returns newest first, we want oldest first
        output = self._run_git(['rev-list', '--reverse', range_spec])
        commits = [line.strip() for line in output.strip().split('\n') if line.strip()]

        if self.verbose:
            print(f"Expanded range {range_spec} to {len(commits)} commits")

        return commits

    def get_commit(self, ref: str, upstream_branch: Optional[str] = None) -> Commit:
        """
        Extract commit metadata and diff.

        Args:
            ref: Git reference (SHA, HEAD, etc.)
            upstream_branch: If provided, compare with upstream branch

        Returns:
            Commit object with metadata and diff
        """
        # Get commit metadata with fuller format
        output = self._run_git(['show', '--format=fuller', '--no-patch', ref])

        # Parse metadata
        sha = self._run_git(['rev-parse', ref]).strip()

        # Extract author line (format: "Author: Name <email>")
        author_match = re.search(r'^Author:\s+(.+)$', output, re.MULTILINE)
        author = author_match.group(1).strip() if author_match else "Unknown"

        # Extract date
        date_match = re.search(r'^AuthorDate:\s+(.+)$', output, re.MULTILINE)
        date = date_match.group(1).strip() if date_match else "Unknown"

        # Extract subject (first line of commit message)
        subject_match = re.search(r'\n\n\s*(.+)$', output, re.MULTILINE)
        subject = subject_match.group(1).strip() if subject_match else "No subject"

        # Extract full commit message (everything after the blank line following headers)
        message_match = re.search(r'\n\n(.*)', output, re.DOTALL)
        message = message_match.group(1).strip() if message_match else ""

        # Get diff
        if upstream_branch:
            # Compare with upstream branch
            diff = self.get_diff_from_upstream(sha, upstream_branch)
        else:
            # Standard commit diff
            diff = self._run_git(['show', '--format=', sha])

        # Extract changed files from diff
        files = self._extract_files_from_diff(diff)

        return Commit(
            sha=sha,
            author=author,
            date=date,
            subject=subject,
            message=message,
            diff=diff,
            files=files
        )

    def get_diff_from_upstream(self, ref: str, upstream_branch: str) -> str:
        """Get diff comparing ref with upstream branch."""
        try:
            # Use three-dot diff to show changes in ref not in upstream
            return self._run_git(['diff', f'{upstream_branch}...{ref}'])
        except RuntimeError as e:
            if self.verbose:
                print(f"Warning: Could not compare with upstream: {e}")
            # Fall back to regular diff
            return self._run_git(['show', '--format=', ref])

    def _extract_files_from_diff(self, diff: str) -> List[str]:
        """Extract list of changed files from unified diff."""
        files = []
        for line in diff.split('\n'):
            # Look for diff --git a/path b/path lines
            match = re.match(r'^diff --git a/(.+) b/', line)
            if match:
                files.append(match.group(1))
        return files
