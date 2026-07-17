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
    distro_commit: Optional[str] = None     # Extracted from distro-specific tag (e.g. suse-commit:)
    upstream_commit: Optional[str] = None   # Extracted from upstream reference tag


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
            raise RuntimeError(f"Git command failed: {e.stderr.strip()}")

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

    def extract_upstream_sha(self, text: str) -> Optional[str]:
        """
        Extract upstream Linux commit SHA from commit message or patch content.

        Tries multiple patterns in priority order:
          1. Git-commit: <sha>                    (explicit tag, distro-style)
          2. (cherry picked from commit <sha>)    (git cherry-pick message)
          3. cherry picked from commit <sha>      (without parens variant)
          4. [ Upstream commit <sha> ]            (stable kernel standard)
          5. commit <sha> upstream                (stable kernel alternate)

        Args:
            text: Commit message or patch content to search

        Returns:
            Upstream commit SHA or None if not found
        """
        # Priority 1: explicit Git-commit: tag
        sha = self.extract_tag(text, 'Git-commit')
        if sha:
            return sha

        # Priority 2 & 3: cherry-pick message (with or without parens)
        for pattern in [
            r'\(cherry picked from commit ([0-9a-fA-F]{12,40})\)',
            r'cherry picked from commit ([0-9a-fA-F]{12,40})',
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return m.group(1)

        # Priority 4: stable kernel standard header
        m = re.search(r'\[ Upstream commit ([0-9a-fA-F]{12,40}) \]', text, re.IGNORECASE)
        if m:
            return m.group(1)

        # Priority 5: stable kernel alternate form
        m = re.search(r'\bcommit ([0-9a-fA-F]{12,40}) upstream\b', text, re.IGNORECASE)
        if m:
            return m.group(1)

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

    def _is_oversized_commit(self, sha: str) -> tuple:
        """
        Check if a commit is too large for direct review using --shortstat.

        Returns:
            Tuple of (is_oversized, file_count, line_count)
        """
        try:
            stat = self._run_git(['show', '--shortstat', '--format=', sha])
            files_match = re.search(r'(\d+) files? changed', stat)
            ins_match = re.search(r'(\d+) insertions?', stat)
            del_match = re.search(r'(\d+) deletions?', stat)

            file_count = int(files_match.group(1)) if files_match else 0
            ins_count = int(ins_match.group(1)) if ins_match else 0
            del_count = int(del_match.group(1)) if del_match else 0
            line_count = ins_count + del_count

            is_oversized = file_count > 1000 or line_count > 10000
            return is_oversized, file_count, line_count
        except Exception:
            return False, 0, 0

    def get_commit(self, ref: str) -> Commit:
        """
        Extract commit metadata and diff.

        Args:
            ref: Git reference (SHA, HEAD, etc.)

        Returns:
            Commit object with metadata and diff
        """
        # Get commit metadata with fuller format
        try:
            output = self._run_git(['show', '--format=fuller', '--no-patch', ref])
        except RuntimeError as e:
            if 'unknown revision' in str(e) or 'not in the working tree' in str(e):
                raise RuntimeError(f"Commit '{ref}' not found in repository")
            raise

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

        # Extract distro and upstream tags early — needed before deciding how to get the diff
        distro_commit_sha = self.extract_tag(message, 'suse-commit')
        git_commit_sha = self.extract_upstream_sha(message)

        # Check if commit is too large to review directly, and fall back to
        # the patch repo commit when a distro-commit tag is available.
        diff = None
        if self.kernel_source_extractor and distro_commit_sha:
            is_oversized, file_count, line_count = self._is_oversized_commit(sha)
            if is_oversized:
                if self.verbose:
                    print(f"  Commit {sha[:12]} is too large to review directly "
                          f"({file_count} files, {line_count} lines). "
                          f"Using patch repo commit {distro_commit_sha[:12]}.")

                patch_info = self.kernel_source_extractor.extract_patch_from_commit(distro_commit_sha)
                if patch_info and patch_info.get('patch_content'):
                    diff = patch_info['patch_content']
                    files = self._extract_files_from_diff(diff)
                    if patch_info.get('subject'):
                        subject = patch_info['subject']
                    if patch_info.get('message'):
                        message = patch_info['message']
                    if patch_info.get('git_commit') and not git_commit_sha:
                        git_commit_sha = patch_info['git_commit']
                else:
                    if self.verbose:
                        print(f"  No patch content found in kernel-source commit; skipping diff.")
                    diff = ""
                    files = []

        if diff is None:
            # Get diff normally
            diff = self._run_git(['show', '--format=', sha])
            files = self._extract_files_from_diff(diff)

            # Try to enhance commit message from kernel-source patch if applicable
            if self.kernel_source_extractor and distro_commit_sha:
                non_empty_lines = [line for line in message.split('\n') if line.strip()]
                if len(non_empty_lines) < 10:
                    if self.debug:
                        print(f"Commit has short message ({len(non_empty_lines)} lines) and distro-commit tag")
                        print(f"Looking up patch repo commit: {distro_commit_sha[:12]}")

                    patch_info = self.kernel_source_extractor.extract_patch_from_commit(distro_commit_sha)

                    if patch_info and patch_info.get('message'):
                        if self.verbose:
                            print(f"  Enhanced commit message from kernel-source patch")

                        if patch_info.get('subject'):
                            subject = patch_info['subject']
                        if patch_info.get('message'):
                            message = patch_info['message']
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
            distro_commit=distro_commit_sha,
            upstream_commit=git_commit_sha
        )

    def _extract_files_from_diff(self, diff: str) -> List[str]:
        """Extract list of changed files from unified diff or patch format."""
        files = []
        for line in diff.split('\n'):
            # Standard git diff header: diff --git a/path b/path
            match = re.match(r'^diff --git a/(.+) b/', line)
            if match:
                files.append(match.group(1))

        if not files:
            # Fallback for patch-file format (no diff --git headers):
            # extract from "--- a/path" lines, skipping /dev/null (new files)
            seen = set()
            for line in diff.split('\n'):
                match = re.match(r'^--- a/(.+)', line)
                if match:
                    path = match.group(1)
                    if path not in seen:
                        seen.add(path)
                        files.append(path)

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

        # Extract upstream commit SHA if present in the patch
        git_commit_sha = self.extract_upstream_sha(patch_content)

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
            distro_commit=None,
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
            # distro-specific commit tag appears in commit message
            distro_commit = self.extractor.extract_tag(message, 'suse-commit')

            # Upstream SHA appears in the diff (as "+Git-commit: <sha>" in patch files)
            # or in the commit message itself
            git_commit = self.extractor.extract_tag_from_diff(diff, 'Git-commit')
            if not git_commit:
                git_commit = self.extractor.extract_upstream_sha(message)

            return Commit(
                sha=sha,
                author=author,
                date=date,
                subject=subject,
                message=message,
                diff=diff,
                files=files,
                distro_commit=distro_commit,
                upstream_commit=git_commit
            )

        except subprocess.CalledProcessError:
            return None

    def extract_patch_from_commit(self, commit_sha: str) -> Optional[dict]:
        """
        Extract patch file content from a patch repository commit.

        Looks for newly created patch files in any patches.*/ subdirectory
        and extracts their content including headers, description, and diff.

        Args:
            commit_sha: Commit SHA in kernel-source repo

        Returns:
            Dict with 'subject', 'message', 'author', 'git_commit', 'patch_content'
            or None if no patch found.  'patch_content' is the full concatenated
            content of all patch files added by the commit, suitable for use as a
            diff when the downstream commit is too large to review directly.
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

            # Collect content of every patch file added by this commit.
            # A new file appears as "+++ b/patches.suse/..." followed by lines
            # prefixed with '+' (since every line of a new file is "added").
            # Stripping the leading '+' recovers the original patch file content.
            all_patch_contents = []
            current_patch_path = None
            current_patch_lines = []

            for line in diff.split('\n'):
                # Detect the start of a new patch file section
                match = re.match(r'^\+\+\+ b/(patches\.[^/]+/[^\s]+\.patch)', line)
                if match:
                    # Save the previous patch if any
                    if current_patch_path and current_patch_lines:
                        all_patch_contents.append('\n'.join(current_patch_lines))
                    current_patch_path = match.group(1)
                    current_patch_lines = []
                    if self.debug:
                        print(f"Found patch file in patch repo commit: {current_patch_path}")
                    continue

                if current_patch_path:
                    # Stop collecting when the next file diff starts
                    if line.startswith('diff --git'):
                        all_patch_contents.append('\n'.join(current_patch_lines))
                        current_patch_path = None
                        current_patch_lines = []
                        continue
                    # Collect added lines, stripping the diff '+' prefix
                    if line.startswith('+'):
                        current_patch_lines.append(line[1:])

            # Save the last patch
            if current_patch_path and current_patch_lines:
                all_patch_contents.append('\n'.join(current_patch_lines))

            if not all_patch_contents:
                return None

            # Concatenate all patch contents; parse headers from the first one
            patch_content = '\n'.join(all_patch_contents)
            first_patch = all_patch_contents[0]

            # Parse patch headers
            author = None
            subject = None
            git_commit = None
            message_lines = []
            in_description = False

            for line in first_patch.split('\n'):
                if line.startswith('From:'):
                    author = line.split(':', 1)[1].strip()
                elif line.startswith('Subject:'):
                    subject = line.split(':', 1)[1].strip()
                    in_description = True
                elif line.startswith('Git-commit:'):
                    git_commit = line.split(':', 1)[1].strip()
                elif line.startswith('---') or line.startswith('diff --git'):
                    break
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
                print(f"Extracted patch description from {current_patch_path or 'patch repo commit'}")
                print(f"  Subject: {subject}")
                if git_commit:
                    print(f"  Git-commit: {git_commit}")

            return {
                'subject': subject,
                'message': full_message,
                'author': author,
                'git_commit': git_commit,
                'patch_content': patch_content,
            }

        except subprocess.CalledProcessError:
            return None
