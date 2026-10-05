"""Parse a plain-text review-inline.txt back into review-inline.json form.

Older reviews only saved review-inline.txt.  This module reconstructs the
subset of the review-inline.json schema needed by --reverify-update
(findings, timing/token metadata, upstream/backport blocks) from the text
produced by ReportFormatter.
"""

import re
from typing import List, Dict, Optional

_FINDING_HEADER_RE = re.compile(r'^\[Finding (\d+)(?: — (.*))?\]$')
_HEADER_KEYS = ('type', 'severity', 'confidence')


def _squash(text) -> str:
    """Strip all whitespace so text re-wrapped by textwrap still compares equal."""
    if isinstance(text, list):
        text = '\n'.join(str(item) for item in text)
    return re.sub(r'\s+', '', str(text or ''))


def _parse_header_fields(header: Optional[str]) -> Dict:
    """Parse 'type: X, severity: Y, confidence: Z' from a finding header."""
    fields: Dict = {}
    if not header:
        return fields
    # Split only at ", <key>: " boundaries so commas inside values survive
    pattern = r'(?:^|, )(' + '|'.join(_HEADER_KEYS) + r'): '
    parts = re.split(pattern, header)
    # parts = ['', key1, val1, key2, val2, ...]
    for key, value in zip(parts[1::2], parts[2::2]):
        fields[key] = value
    if 'confidence' in fields:
        try:
            fields['confidence'] = float(fields['confidence'])
        except ValueError:
            pass
    return fields


def _join_wrapped(lines: List[str]) -> str:
    """Re-join lines produced by textwrap.wrap() into a single paragraph."""
    text = ''
    for line in lines:
        line = line.strip()
        if not text:
            text = line
        elif re.search(r'\w-$', text):
            # textwrap breaks on hyphens ("use-" / "after-free")
            text += line
        else:
            text += ' ' + line
    return text


def _parse_finding_blocks(lines: List[str]) -> List[Dict]:
    """Parse findings written with '[Finding N — ...]' header lines."""
    starts = [i for i, line in enumerate(lines) if _FINDING_HEADER_RE.match(line)]
    findings = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        header = _FINDING_HEADER_RE.match(lines[start]).group(2)
        body = lines[start + 1:end]

        # Message is the first paragraph, evidence is everything after it
        msg_lines = []
        pos = 0
        while pos < len(body) and body[pos].strip():
            msg_lines.append(body[pos])
            pos += 1
        evidence_lines = body[pos:]
        while evidence_lines and not evidence_lines[0].strip():
            evidence_lines.pop(0)
        while evidence_lines and not evidence_lines[-1].strip():
            evidence_lines.pop()

        finding = _parse_header_fields(header)
        finding['message'] = _join_wrapped(msg_lines)
        if evidence_lines:
            finding['evidence'] = '\n'.join(evidence_lines)
        findings.append(finding)
    return findings


def _match_pre_finding(finding: Dict, pre_findings: List[Dict], used: set) -> Optional[int]:
    """Find the pre-verification finding a parsed finding originated from."""
    msg = _squash(finding.get('message'))
    if msg:
        for i, pre in enumerate(pre_findings):
            if i not in used and _squash(pre.get('message')) == msg:
                return i
    # The verifier may have reworded the message; fall back to the type
    ftype = finding.get('type')
    if ftype:
        candidates = [i for i, pre in enumerate(pre_findings)
                      if i not in used and pre.get('type') == ftype]
        if len(candidates) == 1:
            return candidates[0]
    return None


def parse_inline_findings(text: str, pre_findings: Optional[List[Dict]] = None) -> List[Dict]:
    """
    Extract findings from review-inline.txt text.

    Findings written with '[Finding N — ...]' headers are parsed directly and,
    where possible, merged with the matching pre-verification finding to
    recover fields not rendered in text (category, location, ...).  Older
    reports without headers are matched purely against pre_findings by
    message text.
    """
    pre_findings = pre_findings or []
    lines = text.split('\n')

    # Findings follow the quoted diff; ignore the header/summary part
    first_quoted = next((i for i, line in enumerate(lines) if line.startswith('>')), None)
    if first_quoted is None:
        return []
    body_lines = lines[first_quoted:]

    parsed = _parse_finding_blocks(body_lines)
    used: set = set()
    if parsed:
        findings = []
        for finding in parsed:
            idx = _match_pre_finding(finding, pre_findings, used)
            if idx is not None:
                used.add(idx)
                # Text values reflect the final (post-verification) state
                findings.append({**pre_findings[idx], **finding})
            else:
                findings.append(finding)
        return findings

    # No headers: locate each pre-verification finding's message in the text
    squashed_body = _squash('\n'.join(body_lines))
    return [dict(pre) for pre in pre_findings
            if _squash(pre.get('message')) and _squash(pre.get('message')) in squashed_body]


def parse_inline_txt(text: str, pre_findings: Optional[List[Dict]] = None) -> Dict:
    """
    Parse review-inline.txt into a dict using review-inline.json key names.

    Only keys that can be recovered from the text are present.
    """
    data: Dict = {}
    lines = text.split('\n')
    uv: Dict = {}

    for line in lines:
        if line.startswith('>') or _FINDING_HEADER_RE.match(line):
            break
        key, sep, value = line.partition(': ')
        if not sep:
            continue
        value = value.strip()
        if key == 'Author' and 'author' not in data:
            data['author'] = value
        elif key == 'distro-commit':
            data['distro-commit'] = value
        elif key == 'Git-commit':
            data['upstream-commit'] = value
        elif key == 'Verified-against':
            uv['upstream-commit'] = value
        elif key == 'Upstream-subject':
            uv['upstream-subject'] = value
        elif key == 'Findings-in-upstream':
            uv['findings-in-upstream'] = int(value)
        elif key == 'Findings-downstream-only':
            uv['findings-downstream-only'] = int(value)
        elif key == 'Backport-upstream':
            data.setdefault('backport', {})['upstream'] = value
        elif key == 'Backport-status':
            data.setdefault('backport', {})['status'] = value
        elif key == 'Review-time':
            data['review-time-seconds'] = float(value.split()[0])
        elif key == 'Review-model':
            data['model'] = value
        elif key == 'Input-tokens':
            data['input-tokens'] = int(value)
        elif key == 'Output-tokens':
            data['output-tokens'] = int(value)

    # Subject is the first non-empty line after the Author line
    for i, line in enumerate(lines):
        if line.startswith('Author: '):
            subject = next((s for s in lines[i + 1:] if s.strip()), None)
            if subject:
                data['subject'] = subject
            break

    if uv:
        uv.setdefault('findings-in-upstream', 0)
        uv.setdefault('findings-downstream-only', 0)
        data['upstream-verification'] = uv

    data['findings'] = parse_inline_findings(text, pre_findings)
    return data


def load_inline_review(inline_path: str, pre_data: Dict) -> Dict:
    """
    Load an existing inline review as a review-inline.json style dict.

    inline_path may point to review-inline.json or, for older reviews, to
    review-inline.txt (parsed with pre_data's findings as a reference).
    """
    import json

    with open(inline_path, 'r') as f:
        if inline_path.endswith('.json'):
            return json.load(f)
        return parse_inline_txt(f.read(), pre_data.get('findings', []))
