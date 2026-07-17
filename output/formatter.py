"""Format review findings as LKML-compliant plain text."""

import textwrap
from typing import List, Dict, Optional
from git_integration import Commit


class ReportFormatter:
    """Format review results as LKML-compliant plain text."""

    def __init__(self, template_path: str = "prompts/inline-template.md"):
        """
        Initialize report formatter.

        Args:
            template_path: Path to inline-template.md
        """
        self.template_path = template_path
        self.line_width = 78

    def format_report(
        self,
        commit: Commit,
        findings: List[Dict],
        summary: str = None,
        suse_verification: Dict = None,
        backport_comparison=None,
        elapsed_time: float = None,
        is_patch: bool = False,
        model_name: str = None,
        input_tokens: int = None,
        output_tokens: int = None
    ) -> str:
        """
        Format review findings as LKML-compliant plain text.

        Args:
            commit: Commit object
            findings: List of finding dictionaries
            summary: Optional 1-2 sentence summary
            suse_verification: Optional SUSE upstream verification result
            elapsed_time: Optional elapsed time in seconds
            is_patch: True if reviewing a patch file (omits commit SHA)
            model_name: Optional LLM model name used for review
            input_tokens: Optional total input/prompt tokens used
            output_tokens: Optional total output/completion tokens used

        Returns:
            Formatted plain text report
        """
        lines = []

        # Header: commit SHA (omit for patches)
        if not is_patch:
            lines.append(f"commit {commit.sha}")

        # Author line
        lines.append(f"Author: {commit.author}")
        lines.append("")

        # Subject
        lines.append(commit.subject)
        lines.append("")

        # Git-commit tag (if present in patch, skip suse-commit in patch mode)
        if is_patch:
            if commit.upstream_commit:
                lines.append(f"Git-commit: {commit.upstream_commit}")
                lines.append("")
        else:
            # SUSE commit information (if present in commit mode)
            if commit.suse_commit or commit.upstream_commit:
                if commit.suse_commit:
                    lines.append(f"suse-commit: {commit.suse_commit}")
                if commit.upstream_commit:
                    lines.append(f"Git-commit: {commit.upstream_commit}")
            lines.append("")

        # Verified upstream commit (if SUSE verification was performed)
        if suse_verification and suse_verification.get('upstream_commit'):
            upstream = suse_verification['upstream_commit']
            lines.append(f"Verified-against: {upstream.sha}")
            lines.append(f"Upstream-subject: {upstream.subject}")

            # Show upstream/downstream classification if available
            findings_in_upstream = len(suse_verification.get('findings_in_upstream', []))
            findings_downstream = len(suse_verification.get('findings_only_downstream', []))

            if findings_in_upstream > 0 or findings_downstream > 0:
                lines.append(f"Findings-in-upstream: {findings_in_upstream}")
                lines.append(f"Findings-downstream-only: {findings_downstream}")

            lines.append("")

        # Backport comparison results (if Phase 0 ran)
        if backport_comparison and backport_comparison.has_upstream:
            up = backport_comparison.upstream_commit
            lines.append(f"Backport-upstream: {up[:12] if up else 'unknown'}")

            if backport_comparison.function_name_mismatches:
                lines.append("Backport-status: wrong function")
                lines.append("")
                for m in backport_comparison.function_name_mismatches:
                    lines.extend(self._wrap_text(
                        f"WARNING: The downstream patch was applied to "
                        f"{m['downstream_function']}() in {m['file']}, "
                        f"but the upstream commit targets "
                        f"{m['upstream_function']}(). "
                        f"Please verify that {m['downstream_function']}() is "
                        f"the correct location for this fix in this kernel "
                        f"version, or re-apply the patch to "
                        f"{m['upstream_function']}()."
                    ))
            elif backport_comparison.needs_deep_review:
                lines.append("Backport-status: needs review")
                lines.append("")
                lines.append(backport_comparison.summary)
            elif backport_comparison.differences_found:
                lines.append("Backport-status: minor differences")
                lines.append("")
                lines.append(backport_comparison.summary)
            else:
                lines.append("Backport-status: clean")
            lines.append("")

        # Summary (if provided or generate default)
        if summary:
            wrapped_summary = self._wrap_text(summary)
            lines.extend(wrapped_summary)
        else:
            # Default summary if findings exist
            if findings:
                count = len(findings)
                plural = "issues" if count > 1 else "issue"
                default_summary = f"This commit has {count} potential {plural} that should be reviewed."
                lines.append(default_summary)
            else:
                lines.append("This commit appears correct with no regressions found.")

        lines.append("")

        # Processing time (if provided)
        if elapsed_time is not None:
            lines.append(f"Review-time: {elapsed_time:.2f} seconds")
            lines.append("")

        # Model name (if provided)
        if model_name is not None:
            lines.append(f"Review-model: {model_name}")
            lines.append("")

        # Token usage (if provided)
        if input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
            lines.append(f"Input-tokens: {input_tokens}")
            lines.append(f"Output-tokens: {output_tokens}")
            lines.append(f"Total-tokens: {total_tokens}")
            lines.append("")

        # If no findings, end here
        if not findings:
            return "\n".join(lines)

        # Quoted diff with inline findings
        diff_with_findings = self._insert_findings_in_diff(commit.diff, findings)
        lines.append(diff_with_findings)

        lines.append("")
        return "\n".join(lines)

    def _wrap_text(self, text: str) -> List[str]:
        """Wrap text at 78 characters."""
        return textwrap.wrap(text, width=self.line_width)

    def _insert_findings_in_diff(
        self,
        diff: str,
        findings: List[Dict]
    ) -> str:
        """
        Insert findings inline with quoted diff.

        Format:
        > diff --git a/file.c b/file.c
        > @@ -100,5 +100,8 @@ void func(void)
        > +    new_code();
                 ^
        Can this leak memory? The allocation is not freed...

        Args:
            diff: Unified diff content
            findings: List of findings with 'location' and 'message'

        Returns:
            Diff with findings inserted inline
        """
        # Quote all diff lines with "> "
        quoted_lines = [f"> {line}" if line else ">" for line in diff.split('\n')]

        # For now, append findings at the end
        # TODO: In a more sophisticated implementation, match findings to specific hunks
        result = "\n".join(quoted_lines)

        if findings:
            result += "\n\n"
            for i, finding in enumerate(findings, 1):
                # Build header with type, severity, and confidence if available
                ftype = finding.get('type', '')
                severity = finding.get('severity', '')
                confidence = finding.get('confidence', '')
                header_parts = []
                if ftype:
                    header_parts.append(f"type: {ftype}")
                if severity:
                    header_parts.append(f"severity: {severity}")
                if confidence:
                    header_parts.append(f"confidence: {confidence}")
                if header_parts:
                    result += f"[Finding {i} — {', '.join(header_parts)}]\n"
                message = finding.get('message', 'Potential issue found')
                wrapped = self._wrap_text(message)
                result += "\n".join(wrapped) + "\n"

                # Add evidence if available
                evidence = finding.get('evidence', '')
                # Handle both string and list types for evidence (LLM might return either)
                if isinstance(evidence, list):
                    evidence = '\n'.join(str(item) for item in evidence)
                if evidence:
                    # Evidence may contain formatted text (markdown, code blocks)
                    # Preserve formatting but ensure reasonable line lengths
                    evidence_lines = evidence.split('\n')
                    formatted_evidence = []
                    for line in evidence_lines:
                        # If line is very long and doesn't look like code, wrap it
                        if len(line) > self.line_width and not line.strip().startswith(('>', '-', '*', '`')):
                            formatted_evidence.extend(self._wrap_text(line))
                        else:
                            formatted_evidence.append(line)
                    result += "\n" + "\n".join(formatted_evidence) + "\n"

                if i < len(findings):
                    result += "\n"

        return result
