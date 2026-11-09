"""Helpers for reading C source code out of git trees."""

import re
from typing import List, Optional, Tuple


def git_ref_for_commit(sha: str) -> str:
    """
    Get a valid git reference for a commit.

    In patch mode, commit.sha is a filename (e.g., "test.patch"), not a git ref.
    Detect this and return "HEAD" instead.
    """
    # Git SHAs are hex strings (0-9, a-f). If commit.sha contains other chars
    # (like dots, slashes, or non-hex chars), it's likely a patch filename.
    if sha and re.match(r'^[0-9a-fA-F]+$', sha):
        return sha
    return "HEAD"


def _is_definition_start(lines: List[str], idx: int) -> bool:
    """Check whether the signature starting at lines[idx] opens a body ('{') before any ';'."""
    for line in lines[idx:idx + 20]:
        code = line.split('//', 1)[0]
        brace = code.find('{')
        semi = code.find(';')
        if brace >= 0 and (semi < 0 or brace < semi):
            return True
        if semi >= 0:
            return False
    return False


def extract_function(content: str, func_name: str) -> Optional[Tuple[int, str]]:
    """
    Extract a complete function definition from C source.

    Prefers real definitions (signature at column 0 followed by a body) over
    prototypes and call sites; falls back to the first textual match.

    Args:
        content: Full file content
        func_name: Function name

    Returns:
        (1-based start line, definition text), or None if not found
    """
    lines = content.split('\n')
    name_re = re.compile(rf'\b{re.escape(func_name)}\s*\(')

    start = None
    fallback = None
    for i, line in enumerate(lines):
        if not name_re.search(line):
            continue
        if fallback is None:
            fallback = i
        if line[:1].isspace() or line.rstrip().endswith(';'):
            continue
        if _is_definition_start(lines, i):
            start = i
            break

    if start is None:
        start = fallback
    if start is None:
        return None

    # Include the return type when it sits on the preceding line
    # (e.g. "static int\nfoo(...)")
    if start > 0 and lines[start].lstrip().startswith(func_name):
        prev = lines[start - 1]
        if prev.strip() and not prev[:1].isspace() and \
                not prev.rstrip().endswith((';', '}', '{', '*/')) and \
                not prev.startswith('#'):
            start -= 1

    func_def = []
    brace_count = 0
    seen_brace = False
    for line in lines[start:]:
        func_def.append(line)
        brace_count += line.count('{') - line.count('}')
        if '{' in line:
            seen_brace = True
        # Function complete when braces balance
        if seen_brace and brace_count <= 0:
            break

    return start + 1, '\n'.join(func_def)
