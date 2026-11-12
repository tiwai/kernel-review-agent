"""Refresh the later-fix status of already reported findings.

Meant to run regularly (e.g. from cron) over an output directory of earlier
reviews.  For each review with still-open findings it asks the FixChecker
about the commits that landed since the previous refresh only, and updates
fix-status / future-fix in review-inline.json, review-inline.txt and
review-metadata.json in place.  Nothing else of the review is touched.

The branch tips seen by the last refresh are kept in review-fix-check.json
next to the review; a review whose branch tips did not move is skipped
without any git history walk or LLM call.
"""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Dict, List, Optional

from output.fix_info import FIX_STATUS_KEY, FUTURE_FIX_KEY, summarize_future_fixes
from output.inline_parser import load_inline_review
from .fix_checker import FixChecker

STATE_FILE = 'review-fix-check.json'
REFRESH_MAX_ITERATIONS = 3   # tool iterations per LLM call; candidates are pre-selected

_RANK = {'not-fixed': 0, 'fixed-upstream': 1, 'fixed': 2}
_FIX_SUFFIX_RE = re.compile(r'(?:^| — |, )fix-status: .*$')
_FINDING_HEADER_RE = re.compile(r'^\[Finding (\d+)(?: — (.*))?\]$')


def _rank(status) -> int:
    return _RANK.get(status or 'not-fixed', 0)


def _state(finding: Dict):
    """(status, future-fix) with a missing status read as not-fixed"""
    return (finding.get(FIX_STATUS_KEY) or 'not-fixed', finding.get(FUTURE_FIX_KEY))


def _atomic_write(path: str, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.tmp-')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _write_json(path: str, data: Dict) -> None:
    _atomic_write(path, json.dumps(data, indent=2))


def _load_json(path: str) -> Optional[Dict]:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def patch_inline_text(text: str, findings: List[Dict]) -> str:
    """Update the fix-status / future-fix part of the '[Finding N — ...]' headers."""
    out = []
    for line in text.split('\n'):
        m = _FINDING_HEADER_RE.match(line)
        idx = int(m.group(1)) - 1 if m else -1
        if m and m.group(2) and 0 <= idx < len(findings):
            f = findings[idx]
            fields = _FIX_SUFFIX_RE.sub('', m.group(2))
            if f.get(FIX_STATUS_KEY) and f[FIX_STATUS_KEY] != 'not-fixed':
                fields += f", {FIX_STATUS_KEY}: {f[FIX_STATUS_KEY]}"
                if f.get(FUTURE_FIX_KEY):
                    fields += f", {FUTURE_FIX_KEY}: {f[FUTURE_FIX_KEY]}"
            line = f"[Finding {m.group(1)} — {fields}]"
        out.append(line)
    return '\n'.join(out)


def _merge(finding: Dict, old: Dict) -> None:
    """Never downgrade a finding: restore the old result if the new one is weaker."""
    if _rank(finding.get(FIX_STATUS_KEY)) < _rank(old.get(FIX_STATUS_KEY)):
        finding[FIX_STATUS_KEY] = old.get(FIX_STATUS_KEY)
        finding[FUTURE_FIX_KEY] = old.get(FUTURE_FIX_KEY)


def refresh_review_dir(commit_dir: str, checker: FixChecker, llm, force: bool = False,
                       verbose: bool = False) -> Dict:
    """Refresh one review directory.

    Returns {'state': 'skipped'|'unchanged'|'updated'|'error', 'reason': str,
             'newly_fixed': int}.
    """
    result = {'state': 'skipped', 'reason': '', 'newly_fixed': 0}
    inline_json = os.path.join(commit_dir, 'review-inline.json')
    inline_txt = os.path.join(commit_dir, 'review-inline.txt')
    pre_path = os.path.join(commit_dir, 'review-pre-verification.json')
    state_path = os.path.join(commit_dir, STATE_FILE)

    inline_path = inline_json if os.path.exists(inline_json) else inline_txt
    pre = _load_json(pre_path)
    if not os.path.exists(inline_path) or pre is None:
        result['reason'] = 'no review-inline.* or review-pre-verification.json'
        return result

    inline = load_inline_review(inline_path, pre)
    findings = inline.get('findings') or []
    # fixed findings are final; fixed-upstream may still become fixed (backport)
    open_f = [f for f in findings if _rank(f.get(FIX_STATUS_KEY)) < 2]
    if not open_f:
        result['reason'] = 'no open findings'
        return result

    heads = checker.heads()
    if not heads['downstream'] and not heads['upstream']:
        result['reason'] = 'neither target branch nor upstream available'
        return result

    state = _load_json(state_path) or {}
    if state.get('branch') != checker.branch:
        state = {}
    if not force and state and \
            state.get('downstream-head') == heads['downstream'] and \
            state.get('upstream-head') == heads['upstream']:
        result['state'] = 'unchanged'
        result['reason'] = 'branch tips did not move'
        return result

    sha = pre.get('sha') or inline.get('commit') or os.path.basename(commit_dir)
    upstream_sha = inline.get('upstream-commit') or pre.get('upstream_commit')
    commit = SimpleNamespace(
        sha=sha, subject=pre.get('subject', ''), diff=pre.get('diff', ''),
        files=pre.get('files', []), upstream_commit=upstream_sha, distro_commit=None)

    since_down = None if force else state.get('downstream-head')
    since_up = None if force else state.get('upstream-head')
    before = {id(f): _state(f) for f in findings}
    old = {id(f): dict(f) for f in open_f}

    # Group 1: not yet fixed anywhere; only commits since the last refresh matter.
    # Group 2: fixed upstream; the upstream fix must stay a candidate to be able
    # to notice its backport, so the upstream side is scanned in full.
    groups = [
        ([f for f in open_f if _rank(f.get(FIX_STATUS_KEY)) == 0], since_up),
        ([f for f in open_f if _rank(f.get(FIX_STATUS_KEY)) == 1], None),
    ]
    complete = True
    for group, s_up in groups:
        if not group:
            continue
        for f in group:
            f[FIX_STATUS_KEY] = 'not-fixed'
            f[FUTURE_FIX_KEY] = None
        complete &= checker.check(llm, commit, group, upstream_sha,
                                  max_iterations=REFRESH_MAX_ITERATIONS,
                                  since_downstream=since_down, since_upstream=s_up)
        for f in group:
            _merge(f, old[id(f)])

    changed = [f for f in findings
               if before[id(f)] != _state(f)]
    result['newly_fixed'] = sum(1 for f in changed if f.get(FIX_STATUS_KEY) == 'fixed')

    if changed:
        _write_outputs(commit_dir, inline_path, inline, findings)
    if not complete:
        # Keep the old marker so the same range is looked at again next time
        result['state'] = 'error'
        result['reason'] = 'LLM check failed; will retry on the next run'
        return result
    _write_json(state_path, {
        'branch': checker.branch,
        'downstream-head': heads['downstream'],
        'upstream-head': heads['upstream'],
        'checked-at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    })
    result['state'] = 'updated' if changed else 'unchanged'
    result['reason'] = f"{len(changed)} finding(s) changed" if changed else 'no new fixes'
    return result


def _write_outputs(commit_dir: str, inline_path: str, inline: Dict, findings: List[Dict]) -> None:
    """Patch the fix keys into review-inline.json/.txt and review-metadata.json."""
    issues_fixed = sum(1 for f in findings if f.get(FIX_STATUS_KEY) == 'fixed')
    future = summarize_future_fixes(findings)

    if inline_path.endswith('.json'):
        inline['issues-fixed'] = issues_fixed
        inline['future-fix'] = future
        _write_json(inline_path, inline)

    txt_path = os.path.join(commit_dir, 'review-inline.txt')
    if os.path.exists(txt_path):
        with open(txt_path) as f:
            text = f.read()
        _atomic_write(txt_path, patch_inline_text(text, findings))

    meta_path = os.path.join(commit_dir, 'review-metadata.json')
    meta = _load_json(meta_path)
    if meta is not None:
        meta['issues-fixed'] = issues_fixed
        meta['future-fix'] = future
        _write_json(meta_path, meta)
