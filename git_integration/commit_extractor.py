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

    def __init__(self, verbose: bool = False, debug: bool = False, kernel_source_extractor: Optional['MultiRepoExtractor'] = None):
        self.verbose = verbose
        self.debug = debug
        self.kernel_source_extractor = kernel_source_extractor

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

    def extract_tag_from_diff(self, diff: str, tag_name: str) -> Optional[str]:
        """
        Extract tag value from diff content.

        In SUSE kernel-source, tags appear in the diff as added lines.
        Looks for patterns like:
            +Git-commit: abc123def456...
            +Patch-mainline: v6.1-rc1

        Args:
            diff: Diff content
            tag_name: Tag name to search for (e.g., 'Git-commit', 'Patch-mainline')

        Returns:
            Tag value (commit SHA or version) or None if not found
        """
        # Match lines starting with "+" followed by tag
        # Pattern: "+Git-commit: <sha>" where + is the diff marker
        pattern = rf'^\+{re.escape(tag_name)}:\s*([0-9a-fA-F]+)'

        for line in diff.split('\n'):
            match = re.match(pattern, line, re.IGNORECASE)
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
        git_commit_sha = self.extract_tag(message, 'Git-commit')

        # Try to enhance commit message from kernel-source patch if applicable
        if self.kernel_source_extractor and suse_commit_sha:
            # Check if message is short (< 10 non-empty lines)
            non_empty_lines = [line for line in message.split('\n') if line.strip()]
            if len(non_empty_lines) < 10:
                if self.debug:
                    print(f"Commit has short message ({len(non_empty_lines)} lines) and suse-commit tag")
                    print(f"Looking up kernel-source commit: {suse_commit_sha[:12]}")

                # Try to extract patch description from kernel-source commit
                patch_info = self.kernel_source_extractor.extract_patch_from_commit(suse_commit_sha)

                if patch_info and patch_info.get('message'):
                    if self.verbose:
                        print(f"  Enhanced commit message from kernel-source patch")

                    # Use patch description instead of downstream commit message
                    if patch_info.get('subject'):
                        subject = patch_info['subject']
                    if patch_info.get('message'):
                        message = patch_info['message']
                    # Use Git-commit from patch if available and not already set
                    if patch_info.get('git_commit') and not git_commit_sha:
                        git_commit_sha = patch_info['git_commit']

        return Commit(
            sha=sha,
            author=author,
            date=date,
            subject=subject,
            message=message,
            diff=diff,
            files=files,
            suse_commit=suse_commit_sha,
            upstream_commit=git_commit_sha  # Direct Git-commit tag if present
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

    def from_patch_file(self, patch_path: str) -> Commit:
        """
        Parse a patch file and create a Commit object.

        Args:
            patch_path: Path to patch file

        Returns:
            Commit object with metadata and diff
        """
        with open(patch_path, 'r') as f:
            patch_content = f.read()

        # Parse patch headers and content
        lines = patch_content.split('\n')

        author = "Unknown"
        date = "Unknown"
        subject = "No subject"
        message_lines = []
        diff_start = 0

        # Parse headers
        in_message = False
        for i, line in enumerate(lines):
            # Extract author (From: or Author:)
            if line.startswith('From:') or line.startswith('Author:'):
                author = line.split(':', 1)[1].strip()
            # Extract date
            elif line.startswith('Date:'):
                date = line.split(':', 1)[1].strip()
            # Subject line
            elif line.startswith('Subject:'):
                subject = line.split(':', 1)[1].strip()
                # Remove [PATCH] prefix if present
                subject = re.sub(r'^\[PATCH[^\]]*\]\s*', '', subject)
                in_message = True
            # Start of diff
            elif line.startswith('diff --git') or line.startswith('---'):
                diff_start = i
                break
            # Message body
            elif in_message and line.strip():
                message_lines.append(line)

        # Extract message and diff
        message = '\n'.join(message_lines).strip()
        diff = '\n'.join(lines[diff_start:]).strip() if diff_start > 0 else patch_content

        # If no headers found, treat entire content as diff
        if not diff and patch_content.strip():
            diff = patch_content.strip()

        # Extract files from diff
        files = self._extract_files_from_diff(diff)

        # Extract Git-commit tag if present in the patch
        git_commit_sha = self.extract_tag(patch_content, 'Git-commit')

        # Create pseudo-commit object for patch
        # Use patch filename as pseudo-SHA
        import os
        pseudo_sha = os.path.basename(patch_path)

        return Commit(
            sha=pseudo_sha,
            author=author,
            date=date,
            subject=subject,
            message=message,
            diff=diff,
            files=files,
            suse_commit=None,  # No suse-commit for patches
            upstream_commit=git_commit_sha
        )


class MultiRepoExtractor:
    """Handle git operations across multiple repositories."""

    def __init__(self, repo_path: str, verbose: bool = False, debug: bool = False):
        """
        Initialize multi-repo extractor.

        Args:
            repo_path: Absolute path to git repository
            verbose: Enable verbose output
            debug: Enable debug output
        """
        self.repo_path = repo_path
        self.verbose = verbose
        self.debug = debug
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

            # Extract tags
            # suse-commit appears in commit message
            suse_commit = self.extractor.extract_tag(message, 'suse-commit')

            # Git-commit appears in the diff (as "+Git-commit: <sha>" in patch files)
            git_commit = self.extractor.extract_tag_from_diff(diff, 'Git-commit')

            return Commit(
                sha=sha,
                author=author,
                date=date,
                subject=subject,
                message=message,
                diff=diff,
                files=files,
                suse_commit=suse_commit,
                upstream_commit=git_commit  # Git-commit tag from SUSE repo diff
            )

        except subprocess.CalledProcessError:
            return None

    def extract_patch_from_commit(self, commit_sha: str) -> Optional[dict]:
        """
        Extract patch file content from a kernel-source commit.

        Looks for newly created patch files in patches.suse/ or patches.kabi/
        and extracts their content including headers and description.

        Args:
            commit_sha: Commit SHA in kernel-source repo

        Returns:
            Dict with 'subject', 'message', 'author', 'git_commit' or None if no patch found
        """
        if not self.is_available():
            return None

        try:
            # Get the commit diff
            diff_result = subprocess.run(
                ['git', '-C', self.repo_path, 'show', '--format=', commit_sha],
                capture_output=True,
                text=True,
                check=True
            )
            diff = diff_result.stdout

            # Look for new patch files in patches.suse/ or patches.kabi/
            patch_file_path = None
            for line in diff.split('\n'):
                # Match: +++ b/patches.suse/filename.patch or +++ b/patches.kabi/filename.patch
                match = re.match(r'^\+\+\+ b/(patches\.(?:suse|kabi)/[^\s]+\.patch)', line)
                if match:
                    patch_file_path = match.group(1)
                    if self.debug:
                        print(f"Found patch file in kernel-source commit: {patch_file_path}")
                    break

            if not patch_file_path:
                return None

            # Extract the patch content from the diff
            # The content appears as added lines (starting with '+')
            patch_lines = []
            in_patch_content = False

            for line in diff.split('\n'):
                # Start collecting after the "+++ b/patches.suse/..." line
                if line.startswith('+++ b/' + patch_file_path):
                    in_patch_content = True
                    continue

                # Stop at next file
                if in_patch_content and line.startswith('diff --git'):
                    break

                # Collect added lines (remove the leading '+')
                if in_patch_content and line.startswith('+'):
                    patch_lines.append(line[1:])  # Remove '+' prefix

            if not patch_lines:
                return None

            patch_content = '\n'.join(patch_lines)

            # Parse patch headers
            author = None
            subject = None
            git_commit = None
            message_lines = []
            in_description = False

            for line in patch_content.split('\n'):
                # Extract From: author
                if line.startswith('From:'):
                    author = line.split(':', 1)[1].strip()
                # Extract Subject:
                elif line.startswith('Subject:'):
                    subject = line.split(':', 1)[1].strip()
                    in_description = True
                # Extract Git-commit:
                elif line.startswith('Git-commit:'):
                    git_commit = line.split(':', 1)[1].strip()
                # Stop at start of actual patch diff
                elif line.startswith('---') or line.startswith('diff --git'):
                    break
                # Collect description lines (between Subject and ---)
                elif in_description and line.strip() and not line.startswith(('References:', 'Patch-mainline:', 'Git-repo:', 'Date:')):
                    message_lines.append(line)

            # Build full message including subject
            if subject:
                full_message = subject
                if message_lines:
                    full_message += '\n\n' + '\n'.join(message_lines)
            else:
                full_message = '\n'.join(message_lines) if message_lines else None

            if self.debug and (subject or full_message):
                print(f"Extracted patch description from {patch_file_path}")
                print(f"  Subject: {subject}")
                if git_commit:
                    print(f"  Git-commit: {git_commit}")

            return {
                'subject': subject,
                'message': full_message,
                'author': author,
                'git_commit': git_commit
            }

        except subprocess.CalledProcessError:
            return None
