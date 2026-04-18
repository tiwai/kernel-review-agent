"""Generate JSON metadata for review results."""

import json
from typing import List, Dict, Optional
from git_integration import Commit


class MetadataGenerator:
    """Generate JSON metadata for review results."""

    def generate(
        self,
        commit: Commit,
        findings: List[Dict]
    ) -> Dict:
        """
        Generate metadata JSON.

        Args:
            commit: Commit object
            findings: List of findings

        Returns:
            Metadata dictionary
        """
        issues_found = len(findings)

        # Calculate severity based on findings
        severity, explanation = self._calculate_severity(findings, issues_found)

        return {
            "author": commit.author,
            "sha": commit.sha,
            "subject": commit.subject,
            "issues-found": issues_found,
            "issue-severity-score": severity,
            "issue-severity-explanation": explanation
        }

    def generate_pre_verification_metadata(
        self,
        commit: Commit,
        findings: List[Dict],
        suse_verification: Optional[Dict] = None
    ) -> Dict:
        """
        Generate metadata for pre-verification findings (before Task 3).

        This captures findings from Task 2 before false-positive check,
        including SUSE upstream verification results.

        Args:
            commit: Commit object
            findings: Findings from Task 2 (before verification)
            suse_verification: SUSE upstream verification result

        Returns:
            Pre-verification metadata dictionary
        """
        metadata = {
            "author": commit.author,
            "sha": commit.sha,
            "subject": commit.subject,
            "potential_issues_found": len(findings),
            "findings": findings,  # Include full findings list
            "verification_status": "pre_verification"
        }

        # Add SUSE upstream information if available
        if suse_verification:
            suse_info = {
                "suse_commit_sha": commit.suse_commit,
                "upstream_commit_sha": None,
                "findings_in_upstream": len(suse_verification.get('findings_in_upstream', [])),
                "findings_downstream_only": len(suse_verification.get('findings_only_downstream', []))
            }

            if suse_verification.get('upstream_commit'):
                upstream = suse_verification['upstream_commit']
                suse_info['upstream_commit_sha'] = upstream.sha
                suse_info['upstream_subject'] = upstream.subject

            metadata['suse_upstream_verification'] = suse_info

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

        # Look for keywords in findings to determine severity
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
