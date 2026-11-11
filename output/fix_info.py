"""Helpers for the fix-status / future-fix keys of findings."""

from typing import Dict, List, Optional

FIX_STATUS_KEY = 'fix-status'
FUTURE_FIX_KEY = 'future-fix'


def summarize_future_fixes(findings: List[Dict]) -> Optional[str]:
    """One-line summary of the distinct later fixes, or None if there is none."""
    seen: List[str] = []
    for f in findings:
        fix = f.get(FUTURE_FIX_KEY)
        if not fix:
            continue
        for part in str(fix).split(';'):
            part = part.strip()
            if part and part not in seen:
                seen.append(part)
    return '; '.join(seen) if seen else None
