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
    # SUSE integration fields
    suse_commit: Optional[str] = None       # Extracted from suse-commit: tag
    upstream_commit: Optional[str] = None   # Extracted from Git-commit: tag in SUSE repo


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

    def extract_tag(self, message: str, tag_name: str) -> Optional[str]:
        """
        Extract tag value from commit message.

        Looks for patterns like:
            suse-commit: abc123def456...
            Git-commit: def456abc123...

        Args:
            message: Commit message text
            tag_name: Tag name to search for (e.g., 'suse-commit', 'Git-commit')

        Returns:
            Tag value (commit SHA) or None if not found
        """
        # Match tag with optional whitespace: "suse-commit: <sha>" or "suse-commit:<sha>"
        pattern = rf'^{re.escape(tag_name)}:\s*([0-9a-fA-F]+)'

        for line in message.split('\n'):
            match = re.match(pattern, line.strip(), re.IGNORECASE)
            if match:
                return match.group(1)

        return None

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

    def get_commit(self, ref: str) -> Commit:
        """
        Extract commit metadata and diff.

        Args:
            ref: Git reference (SHA, HEAD, etc.)

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
        diff = self._run_git(['show', '--format=', sha])

        # Extract changed files from diff
        files = self._extract_files_from_diff(diff)

        # Extract SUSE tags if present
        suse_commit_sha = self.extract_tag(message, 'suse-commit')

        return Commit(
            sha=sha,
            author=author,
            date=date,
            subject=subject,
            message=message,
            diff=diff,
            files=files,
            suse_commit=suse_commit_sha,
            upstream_commit=None  # Will be populated later if needed
        )

    def _extract_files_from_diff(self, diff: str) -> List[str]:
        """Extract list of changed files from unified diff."""
        files = []
        for line in diff.split('\n'):
            # Look for diff --git a/path b/path lines
            match = re.match(r'^diff --git a/(.+) b/', line)
            if match:
                files.append(match.group(1))
        return files


class MultiRepoExtractor:
    """Handle git operations across multiple repositories."""

    def __init__(self, repo_path: str, verbose: bool = False):
        """
        Initialize multi-repo extractor.

        Args:
            repo_path: Absolute path to git repository
            verbose: Enable verbose output
        """
        self.repo_path = repo_path
        self.verbose = verbose
        self.extractor = CommitExtractor(verbose=verbose)

    def is_available(self) -> bool:
        """Check if repository path exists and is a git repo."""
        import os
        if not self.repo_path or not os.path.exists(self.repo_path):
            return False

        try:
            result = subprocess.run(
                ['git', '-C', self.repo_path, 'rev-parse', '--git-dir'],
                capture_output=True,
                text=True,
                check=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def get_commit(self, commit_sha: str) -> Optional[Commit]:
        """
        Get commit from this repository.

        Args:
            commit_sha: Commit SHA to fetch

        Returns:
            Commit object or None if not found
        """
        if not self.is_available():
            return None

        try:
            # Run git show with -C to specify repository
            result = subprocess.run(
                ['git', '-C', self.repo_path, 'show', '--format=fuller', '--no-patch', commit_sha],
                capture_output=True,
                text=True,
                check=True
            )
            output = result.stdout

            # Get full SHA
            sha_result = subprocess.run(
                ['git', '-C', self.repo_path, 'rev-parse', commit_sha],
                capture_output=True,
                text=True,
                check=True
            )
            sha = sha_result.stdout.strip()

            # Parse using existing logic
            author_match = re.search(r'^Author:\s+(.+)$', output, re.MULTILINE)
            author = author_match.group(1).strip() if author_match else "Unknown"

            date_match = re.search(r'^AuthorDate:\s+(.+)$', output, re.MULTILINE)
            date = date_match.group(1).strip() if date_match else "Unknown"

            subject_match = re.search(r'\n\n\s*(.+)$', output, re.MULTILINE)
            subject = subject_match.group(1).strip() if subject_match else "No subject"

            message_match = re.search(r'\n\n(.*)', output, re.DOTALL)
            message = message_match.group(1).strip() if message_match else ""

            # Get diff
            diff_result = subprocess.run(
                ['git', '-C', self.repo_path, 'show', '--format=', sha],
                capture_output=True,
                text=True,
                check=True
            )
            diff = diff_result.stdout

            # Extract files
            files = self.extractor._extract_files_from_diff(diff)

            # Extract tags (both suse-commit and Git-commit)
            suse_commit = self.extractor.extract_tag(message, 'suse-commit')
            git_commit = self.extractor.extract_tag(message, 'Git-commit')

            return Commit(
                sha=sha,
                author=author,
                date=date,
                subject=subject,
                message=message,
                diff=diff,
                files=files,
                suse_commit=suse_commit,
                upstream_commit=git_commit  # Git-commit tag from SUSE repo
            )

        except subprocess.CalledProcessError:
            return None
