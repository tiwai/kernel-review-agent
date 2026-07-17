"""Format review findings as structured JSON."""

from typing import List, Dict, Optional
from git_integration import Commit


class JSONReportFormatter:
    """Format review results as a structured JSON-serialisable dict."""

    def format_report(
        self,
        commit: Commit,
        findings: List[Dict],
        summary: str = None,
        upstream_verification: Dict = None,
        backport_comparison=None,
        elapsed_time: float = None,
        is_patch: bool = False,
        model_name: str = None,
        input_tokens: int = None,
        output_tokens: int = None
    ) -> Dict:
        """
        Build a JSON-serialisable dict representing the full review result.

        The dict schema mirrors review-metadata.json for the top-level fields
        but adds a structured "findings" array (with confidence, severity, type,
        message, evidence, etc.) and a quoted "diff" section.

        Args:
            commit: Commit object
            findings: List of finding dicts (may include 'confidence' field)
            summary: Optional 1-2 sentence summary
            upstream_verification: Optional upstream verification result
            backport_comparison: Optional BackportComparison object
            elapsed_time: Optional elapsed time in seconds
            is_patch: True if reviewing a patch file (omits commit SHA)
            model_name: Optional LLM model name
            input_tokens: Optional total prompt tokens
            output_tokens: Optional total completion tokens

        Returns:
            Dict suitable for json.dumps()
        """
        report: Dict = {}

        if not is_patch:
            report["commit"] = commit.sha

        report["author"] = commit.author
        report["subject"] = commit.subject

        if not is_patch and commit.distro_commit:
            report["distro-commit"] = commit.distro_commit

        if commit.upstream_commit:
            report["upstream-commit"] = commit.upstream_commit

        # Upstream verification
        if upstream_verification and upstream_verification.get('upstream_commit'):
            upstream = upstream_verification['upstream_commit']
            uv_block: Dict = {
                "upstream-commit": upstream.sha,
                "upstream-subject": upstream.subject,
                "findings-in-upstream": len(upstream_verification.get('findings_in_upstream', [])),
                "findings-downstream-only": len(upstream_verification.get('findings_only_downstream', [])),
            }
            report["upstream-verification"] = uv_block

        # Backport comparison
        if backport_comparison and backport_comparison.has_upstream:
            up = backport_comparison.upstream_commit
            if backport_comparison.function_name_mismatches:
                status = "wrong function"
            elif backport_comparison.needs_deep_review:
                status = "needs review"
            elif backport_comparison.differences_found:
                status = "minor differences"
            else:
                status = "clean"

            bp_block: Dict = {
                "upstream": up[:12] if up else "unknown",
                "status": status,
                "summary": backport_comparison.summary or "",
            }
            if backport_comparison.function_name_mismatches:
                bp_block["function-mismatches"] = backport_comparison.function_name_mismatches
            report["backport"] = bp_block

        report["summary"] = summary or (
            f"This commit has {len(findings)} potential issue(s) that should be reviewed."
            if findings else
            "This commit appears correct with no regressions found."
        )

        # Structured findings list
        report["findings"] = [self._format_finding(f) for f in findings]

        if elapsed_time is not None:
            report["review-time-seconds"] = round(elapsed_time, 2)

        if model_name is not None:
            report["model"] = model_name

        if input_tokens is not None and output_tokens is not None:
            report["input-tokens"] = input_tokens
            report["output-tokens"] = output_tokens
            report["total-tokens"] = input_tokens + output_tokens

        return report

    def _format_finding(self, finding: Dict) -> Dict:
        """Return a clean copy of a finding dict with well-defined keys."""
        result: Dict = {}
        for key in ("category", "type", "severity", "confidence", "message",
                    "evidence", "upstream_status"):
            if key in finding:
                result[key] = finding[key]
        # Carry through any extra keys the LLM may have added
        for key, value in finding.items():
            if key not in result:
                result[key] = value
        return result
