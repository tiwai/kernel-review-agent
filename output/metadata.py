"""Generate JSON metadata for review results."""

import json
from typing import List, Dict, Optional
from git_integration import Commit


class MetadataGenerator:
    """Generate JSON metadata for review results."""

    def generate(
        self,
        commit: Commit,
        findings: List[Dict],
        elapsed_time: float = None,
        is_patch: bool = False,
        model_name: str = None,
        input_tokens: int = None,
        output_tokens: int = None,
        backport_comparison=None
    ) -> Dict:
        """
        Generate metadata JSON.

        Args:
            commit: Commit object
            findings: List of findings
            elapsed_time: Optional elapsed time in seconds
            is_patch: True if reviewing a patch file (omits SHA field)
            model_name: Optional LLM model name used for review
            input_tokens: Optional total input/prompt tokens used
            output_tokens: Optional total output/completion tokens used

        Returns:
            Metadata dictionary
        """
        issues_found = len(findings)

        # Calculate severity based on findings
        severity, explanation = self._calculate_severity(findings, issues_found)

        metadata = {
            "author": commit.author,
            "subject": commit.subject,
            "issues-found": issues_found,
            "issue-severity-score": severity,
            "issue-severity-explanation": explanation
        }

        # Include commit SHA for commits (not for patches)
        if not is_patch:
            metadata["sha"] = commit.sha

        # Include elapsed time if provided
        if elapsed_time is not None:
            metadata["review-time-seconds"] = round(elapsed_time, 2)

        # Include model name if provided
        if model_name is not None:
            metadata["model"] = model_name

        # Include token usage if provided
        if input_tokens is not None and output_tokens is not None:
            metadata["input-tokens"] = input_tokens
            metadata["output-tokens"] = output_tokens
            metadata["total-tokens"] = input_tokens + output_tokens

        # Include distro commit ID if present (not in patch mode)
        if not is_patch and commit.distro_commit:
            metadata["distro-commit"] = commit.distro_commit

        # Include upstream commit if present
        if commit.upstream_commit:
            metadata["upstream-commit"] = commit.upstream_commit

        # Include backport comparison results if Phase 0 ran
        if backport_comparison and backport_comparison.has_upstream:
            metadata["backport-verification"] = {
                "differences-found": backport_comparison.differences_found,
                "needs-deep-review": backport_comparison.needs_deep_review,
                "summary": backport_comparison.summary,
                "wrong-function-mismatches": len(backport_comparison.function_name_mismatches),
                "line-number-shifts": len(backport_comparison.line_number_shifts),
                "context-mismatches": len(backport_comparison.context_mismatches),
                "missing-hunks": len(backport_comparison.missing_hunks),
                "extra-hunks": len(backport_comparison.extra_hunks),
            }

        return metadata

    def generate_pre_verification_metadata(
        self,
        commit: Commit,
        findings: List[Dict],
        upstream_verification: Optional[Dict] = None,
        categories: Optional[List[Dict]] = None,
        subsystems: Optional[List[str]] = None,
        code_context_formatted: Optional[str] = None
    ) -> Dict:
        """
        Generate metadata for pre-verification findings (before Task 3).

        This captures findings from Task 2 before false-positive check,
        including upstream verification results and all information
        needed to re-verify the findings later.

        Args:
            commit: Commit object
            findings: Findings from Task 2 (before verification)
            upstream_verification: Upstream verification result
            categories: Change categories from Task 1 (optional, for re-verification)
            subsystems: Matched subsystems (optional, for re-verification)
            code_context_formatted: Formatted code context (optional, for re-verification)

        Returns:
            Pre-verification metadata dictionary with complete re-verification data
        """
        metadata = {
            "author": commit.author,
            "sha": commit.sha,
            "subject": commit.subject,
            "message": commit.message,  # Full commit message for re-verification
            "diff": commit.diff,  # Full diff needed for re-verification
            "files": commit.files,  # Changed files list
            "potential_issues_found": len(findings),
            "findings": findings,  # Include full findings list
            "verification_status": "pre_verification"
        }

        # Add change categories if provided (from Task 1)
        if categories:
            metadata['categories'] = categories

        # Add matched subsystems if provided (for loading correct guides)
        if subsystems:
            metadata['subsystems'] = subsystems

        # Add code context if provided (for full re-verification)
        if code_context_formatted:
            metadata['code_context'] = code_context_formatted

        # Add upstream verification information if available
        if upstream_verification:
            uv_info = {
                "distro_commit_sha": commit.distro_commit,
                "upstream_commit_sha": None,
                "findings_in_upstream": len(upstream_verification.get('findings_in_upstream', [])),
                "findings_downstream_only": len(upstream_verification.get('findings_only_downstream', []))
            }

            if upstream_verification.get('upstream_commit'):
                upstream = upstream_verification['upstream_commit']
                uv_info['upstream_commit_sha'] = upstream.sha
                uv_info['upstream_subject'] = upstream.subject

            metadata['upstream_verification'] = uv_info

        # Add upstream commit if present
        if commit.upstream_commit:
            metadata['upstream_commit'] = commit.upstream_commit

        return metadata

    def _calculate_severity(
        self,
        findings: List[Dict],
        count: int
    ) -> tuple[str, str]:
        """
        Calculate severity score and explanation.

        Args:
            findings: List of findings
            count: Number of findings

        Returns:
            (severity_level, explanation) tuple
        """
        if count == 0:
            return "none", "No issues found"

        # Look for severity in findings to determine overall severity
        high_severity_keywords = [
            "use-after-free", "double-free", "null pointer", "crash",
            "memory corruption", "deadlock", "race condition"
        ]

        medium_severity_keywords = [
            "leak", "missing check", "incorrect", "wrong"
        ]

        # Check all findings for severity indicators
        has_high = False
        has_medium = False

        for finding in findings:
            # Prefer explicit severity field set by the LLM
            sev = finding.get('severity', '').lower()
            if sev == 'high' or sev == 'urgent':
                has_high = True
                continue
            if sev == 'medium':
                has_medium = True
                continue

            # Fall back to keyword scan when severity field is absent
            message = finding.get('message', '').lower()
            issue_type = finding.get('type', '').lower()
            combined = message + " " + issue_type

            for keyword in high_severity_keywords:
                if keyword in combined:
                    has_high = True
                    break

            for keyword in medium_severity_keywords:
                if keyword in combined:
                    has_medium = True

        # Determine severity
        if has_high:
            severity = "high"
            explanation = "Critical issues found that could cause crashes or data corruption"
        elif has_medium:
            severity = "medium"
            explanation = f"{count} issue{'s' if count > 1 else ''} found that should be fixed"
        else:
            severity = "low"
            explanation = f"{count} minor issue{'s' if count > 1 else ''} found"

        return severity, explanation

    def save_json(self, metadata: Dict, filepath: str):
        """Save metadata to JSON file."""
        with open(filepath, 'w') as f:
            json.dump(metadata, f, indent=2)
