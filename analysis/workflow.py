"""Main review workflow orchestration (5-task protocol)."""

import json
import re
import subprocess
import sys
from typing import List, Dict, Optional
from dataclasses import dataclass

from git_integration import Commit
from llm_integration import OpenAIClient
from prompt_management import PromptLoader, SubsystemMatcher
from analysis.code_context import CodeContextLoader
import config


@dataclass
class ReviewResult:
    """Review result containing findings and metadata."""
    findings: List[Dict]
    summary: str
    subsystems_loaded: List[str]
    upstream_verification: Optional[Dict] = None  # Upstream verification result
    backport_comparison: Optional[Dict] = None  # Backport quality comparison
    fix_patches: Optional[str] = None  # Proposed fix patches (unified diff)
    input_tokens: int = 0  # Total input/prompt tokens used
    output_tokens: int = 0  # Total output/completion tokens used
    # Pre-verification data (for re-verification support)
    pre_verification_findings: Optional[List[Dict]] = None  # Findings before Task 3 verification
    categories: Optional[List[Dict]] = None  # Change categories from Task 1
    code_context_formatted: Optional[str] = None  # Code context for re-verification


class ReviewWorkflow:
    """Orchestrate 5-task review protocol."""

    def __init__(
        self,
        llm_client: OpenAIClient,
        prompt_loader: PromptLoader,
        subsystem_matcher: SubsystemMatcher,
        verbose: bool = False,
        debug: bool = False,
        skip_verification: bool = False,
        upstream_verifier: Optional['UpstreamVerifier'] = None,
        propose_fixes: bool = False,
        max_tool_iterations: int = None,
        stop_after: Optional[str] = None,
        git_dir: str = '.'
    ):
        """
        Initialize review workflow.

        Args:
            llm_client: LLM client for API calls
            prompt_loader: Prompt loader
            subsystem_matcher: Subsystem matcher
            verbose: Enable verbose output
            debug: Enable debug output
            skip_verification: Skip false-positive verification step
            upstream_verifier: Upstream verifier for backport classification (optional)
            propose_fixes: Generate fix patch proposals for verified findings
            max_tool_iterations: Max tool-call iterations per step (None = use config default)
            stop_after: Stop workflow after stage ('categorize', 'analyze', 'verify', or None for full)
            git_dir: Path to the git repository (used for file-existence checks)
        """
        self.llm = llm_client
        self.prompts = prompt_loader
        self.matcher = subsystem_matcher
        self.verbose = verbose
        self.debug = debug
        self.skip_verification = skip_verification
        self.upstream_verifier = upstream_verifier
        self.propose_fixes = propose_fixes
        self.max_tool_iterations = max_tool_iterations if max_tool_iterations is not None else config.MAX_TOOL_ITERATIONS
        self.stop_after = stop_after
        self.git_dir = git_dir

    def reverify_from_json(self, json_path: str) -> ReviewResult:
        """
        Re-verify findings from a saved review-pre-verification.json file.

        This allows re-running the verification step (Task 3) on previously
        identified findings, useful for testing different verification strategies
        or re-evaluating findings with updated models.

        Args:
            json_path: Path to review-pre-verification.json file

        Returns:
            ReviewResult with verified findings

        Raises:
            FileNotFoundError: If json_path doesn't exist
            ValueError: If JSON is invalid or missing required fields
        """
        import json
        import os

        # Reset token usage counters
        self.llm.reset_token_usage()

        if not os.path.exists(json_path):
            raise FileNotFoundError(f"Pre-verification file not found: {json_path}")

        # Load pre-verification data
        with open(json_path, 'r') as f:
            pre_data = json.load(f)

        # Validate required fields
        required_fields = ['sha', 'subject', 'diff', 'findings']
        missing = [f for f in required_fields if f not in pre_data]
        if missing:
            raise ValueError(f"Missing required fields in {json_path}: {', '.join(missing)}")

        if self.verbose:
            print(f"\nRe-verifying findings from {json_path}...")
            print(f"SHA: {pre_data['sha'][:12]}")
            print(f"Subject: {pre_data['subject']}")
            print(f"Pre-verification findings: {pre_data.get('potential_issues_found', 0)}\n")

        # Reconstruct commit object from saved data
        from git_integration import Commit
        commit = Commit(
            sha=pre_data['sha'],
            author=pre_data.get('author', 'Unknown'),
            date=pre_data.get('date', 'Unknown'),  # Add date field
            subject=pre_data['subject'],
            message=pre_data.get('message', pre_data['subject']),
            diff=pre_data['diff'],
            files=pre_data.get('files', []),
            upstream_commit=pre_data.get('upstream_commit'),
            distro_commit=pre_data.get('upstream_verification', pre_data.get('suse_upstream_verification', {})).get('distro_commit_sha')
        )

        # Reconstruct context
        context = {
            'files': pre_data.get('files', []),
            'code_context_formatted': pre_data.get('code_context', '')
        }

        # Get findings to verify
        findings = pre_data['findings']
        categories = pre_data.get('categories', [])
        subsystems = pre_data.get('subsystems', [])
        upstream_verification = pre_data.get('upstream_verification', pre_data.get('suse_upstream_verification'))

        if self.verbose:
            print(f"[3/3] Re-verifying {len(findings)} findings...")

        # Task 3: Verify findings (same as normal workflow)
        if self.skip_verification:
            if self.verbose:
                print("      Verification skipped (--skip-verification enabled)")
            verified = findings
        else:
            verified = self._verify_findings(findings, context, commit)
            if self.verbose:
                print(f"      {len(verified)} issues after re-verification")
                discarded = len(findings) - len(verified)
                if discarded > 0:
                    print(f"      Discarded {discarded} as false positives")

        # Generate summary
        summary = self._generate_summary(commit, verified, upstream_verification)

        # Get token usage
        token_usage = self.llm.get_token_usage()

        if self.verbose:
            print(f"\nRe-verification complete: {len(verified)} issue(s) confirmed\n")

        return ReviewResult(
            findings=verified,
            summary=summary,
            subsystems_loaded=subsystems,
            upstream_verification=upstream_verification,
            input_tokens=token_usage['prompt_tokens'],
            output_tokens=token_usage['completion_tokens'],
            pre_verification_findings=findings,
            categories=categories,
            code_context_formatted=context.get('code_context_formatted')
        )

    def execute_review(self, commit: Commit, commit_output_dir: Optional[str] = None) -> ReviewResult:
        """
        Execute full 5-task review protocol.

        Args:
            commit: Commit to review
            commit_output_dir: Output directory for this commit (for prompt dumping)

        Returns:
            ReviewResult with findings and metadata
        """
        # Reset token usage counters at the start of each review
        self.llm.reset_token_usage()

        if self.verbose:
            print(f"\nReviewing commit {commit.sha[:12]}...")
            print(f"Subject: {commit.subject}\n")

        # Task 0: Context management (automated)
        if self.verbose:
            print("[1/5] Gathering context...")
        if self.debug:
            print(f"Task 0: Context management")
            print(f"Commit SHA: {commit.sha}")
            print(f"Files changed: {len(commit.files)}")
            print(f"Diff size: {len(commit.diff)} chars")

        context = self._gather_context(commit)

        if self.debug:
            print(f"Context gathered:")
            print(f"  - Changed functions: {context.get('changed_functions', [])}")
            print(f"  - Files: {context.get('files', [])}")

        # Match subsystems
        subsystems = self.matcher.match_diff(commit.files, commit.diff)
        if self.verbose and subsystems:
            print(f"      Matched subsystems: {', '.join(subsystems)}")
        if self.debug:
            print(f"Subsystems matched: {subsystems}")

        # Task 1: Categorize changes (LLM-driven)
        if self.verbose:
            print("\n[2/5] Categorizing changes...")
        if self.debug:
            print(f"Task 1: Categorizing changes")
            print(f"Calling LLM for categorization...")

        categories = self._categorize_changes(commit, context, commit_output_dir)

        if self.verbose:
            print(f"      Found {len(categories)} change categories")
        if self.debug:
            print(f"Categories:")
            for cat in categories:
                print(f"  - {cat.get('id')}: {cat.get('type')} - {cat.get('description', '')[:60]}")

        # Early exit if stop_after == 'categorize'
        if self.stop_after == 'categorize':
            if self.verbose:
                print("\nStopping after categorization (--stop-after categorize)")
            token_usage = self.llm.get_token_usage()
            return ReviewResult(
                findings=[],
                summary="Stopped after categorization stage",
                subsystems_loaded=[],
                input_tokens=token_usage['prompt_tokens'],
                output_tokens=token_usage['completion_tokens'],
                categories=categories,
                code_context_formatted=context.get('code_context_formatted')
            )

        # Task 2: Analyze for regressions (LLM-driven)
        if self.verbose:
            print("\n[3/5] Analyzing for regressions...")
        if self.debug:
            print(f"Task 2: Analyzing for regressions")
            print(f"Loading subsystem guides: {subsystems}")
            print(f"Calling LLM for regression analysis...")

        findings = self._analyze_regressions(commit, categories, context, subsystems, commit_output_dir)

        if self.verbose:
            print(f"      Found {len(findings)} potential issues")
        if self.debug:
            print(f"Findings:")
            for i, finding in enumerate(findings):
                print(f"  {i+1}. {finding.get('type')}: {finding.get('message', '')[:60]}...")

        # Early exit if stop_after == 'analyze'
        if self.stop_after == 'analyze':
            if self.verbose:
                print("\nStopping after regression analysis (--stop-after analyze)")
            token_usage = self.llm.get_token_usage()
            return ReviewResult(
                findings=findings,
                summary="Stopped after regression analysis stage",
                subsystems_loaded=subsystems,
                input_tokens=token_usage['prompt_tokens'],
                output_tokens=token_usage['completion_tokens'],
                pre_verification_findings=findings,
                categories=categories,
                code_context_formatted=context.get('code_context_formatted')
            )

        # Task 2.5: Upstream verification (conditional)
        upstream_verification_result = None
        if self.upstream_verifier and self.upstream_verifier.should_verify(commit, findings):
            if self.verbose:
                print("\n[3.5/5] Verifying against upstream...")
            if self.debug:
                print(f"Task 2.5: Upstream verification")

            upstream_verification_result = self.upstream_verifier.verify_against_upstream(
                commit, findings
            )

            # Annotate findings with upstream status
            findings_in_upstream = set(
                id(f) for f in upstream_verification_result.get('findings_in_upstream', [])
            )

            for finding in findings:
                if id(finding) in findings_in_upstream:
                    finding['upstream_status'] = 'present_in_upstream'
                else:
                    finding['upstream_status'] = 'downstream_only'

            if self.debug:
                print(f"Upstream verification complete")
                print(f"  Findings in upstream: {len(upstream_verification_result.get('findings_in_upstream', []))}")
                print(f"  Downstream-only: {len(upstream_verification_result.get('findings_only_downstream', []))}")

        # Task 3: Verify findings (eliminate false positives)
        if self.skip_verification:
            if self.verbose:
                print("\n[4/5] Skipping verification (--skip-verification enabled)...")
            if self.debug:
                print(f"Task 3: SKIPPED (verification disabled)")
            verified = findings
        else:
            if self.verbose:
                print("\n[4/5] Verifying findings...")
            if self.debug:
                print(f"Task 3: Verifying findings")
                print(f"Applying false-positive checks to {len(findings)} findings...")

            verified = self._verify_findings(findings, context, commit, commit_output_dir)

            if self.verbose:
                print(f"      {len(verified)} issues after verification")
            if self.debug:
                discarded = len(findings) - len(verified)
                print(f"Verification complete: {len(verified)} verified, {discarded} discarded as false positives")

        # Task 4: Generate summary
        if self.verbose:
            print("\n[5/5] Generating summary...")
        if self.debug:
            print(f"Task 4: Generating summary")

        summary = self._generate_summary(commit, verified, upstream_verification_result)

        if self.debug:
            print(f"Summary: {summary}")

        # Task 5 (optional): Propose fix patches
        fix_patches = None
        if self.propose_fixes and verified:
            if self.verbose:
                print("\n[+] Proposing fix patches...")
            if self.debug:
                print(f"Task 5: Proposing fixes for {len(verified)} finding(s)")
            fix_patches = self._propose_fixes(commit, verified, context, categories)

        if self.verbose:
            print(f"\nReview complete: {len(verified)} issue(s) found\n")

        # Get token usage from LLM client
        token_usage = self.llm.get_token_usage()
        if self.debug:
            print(f"Total token usage - Input: {token_usage['prompt_tokens']}, "
                  f"Output: {token_usage['completion_tokens']}, "
                  f"Total: {token_usage['total_tokens']}")

        return ReviewResult(
            findings=verified,
            summary=summary,
            subsystems_loaded=subsystems,
            upstream_verification=upstream_verification_result,
            fix_patches=fix_patches,
            input_tokens=token_usage['prompt_tokens'],
            output_tokens=token_usage['completion_tokens'],
            # Pre-verification data for re-verification support
            pre_verification_findings=findings if not self.skip_verification else None,
            categories=categories,
            code_context_formatted=context.get("code_context_formatted")
        )

    def _gather_context(self, commit: Commit) -> Dict:
        """
        Task 0: Automated context gathering.

        Returns:
            Context dictionary with changed functions, files, etc.
        """
        context = {
            "files": commit.files,
            "changed_functions": self._extract_changed_functions(commit.diff),
            "diff_stats": {
                "files_changed": len(commit.files),
                "has_c_files": any(f.endswith('.c') for f in commit.files),
                "has_h_files": any(f.endswith('.h') for f in commit.files)
            }
        }

        # Load full source code context for deeper analysis
        if self.debug:
            print(f"Loading full source code context...")

        code_loader = CodeContextLoader(commit, verbose=self.verbose, debug=self.debug)
        full_context = code_loader.load_full_context()
        context["code_context"] = full_context
        context["code_context_formatted"] = code_loader.format_context_for_prompt(full_context)

        if self.debug:
            print(f"Loaded {len(full_context.get('function_definitions', {}))} function definitions")
            print(f"Loaded {sum(len(v) for v in full_context.get('callers', {}).values())} caller references")

        return context

    # C keywords that appear at the start of hunk context lines but are not function names
    _C_NON_FUNCTION_WORDS = frozenset({
        'static', 'inline', 'extern', 'const', 'volatile', 'struct', 'union',
        'enum', 'typedef', 'void', 'int', 'long', 'unsigned', 'signed', 'char',
        'short', 'float', 'double', 'bool', 'if', 'else', 'for', 'while', 'do',
        'switch', 'case', 'return', 'goto', 'break', 'continue', 'sizeof',
    })

    def _extract_changed_functions(self, diff: str) -> List[str]:
        """Extract function names from diff hunk headers (@@ ... @@ context)."""
        functions = set()

        for line in diff.split('\n'):
            if not line.startswith('@@'):
                continue
            # Hunk header: @@ -a,b +c,d @@ [optional context]
            # Context is typically "type qualifier... funcname(..." or just "funcname(..."
            # Grab the identifier immediately before the first '('
            after = re.search(r'@@[^@]*@@\s*(.*)', line)
            if not after:
                continue
            context = after.group(1).strip()
            # Find the word just before '(' — that's the function name
            m = re.search(r'(\w+)\s*\(', context)
            if m:
                name = m.group(1)
                if name not in self._C_NON_FUNCTION_WORDS:
                    functions.add(name)
                    continue
            # Fallback: first non-keyword word in the context
            for word in re.findall(r'\w+', context):
                if word not in self._C_NON_FUNCTION_WORDS:
                    functions.add(word)
                    break

        return list(functions)

    def _looks_truncated(self, json_str: str) -> bool:
        """
        Check if JSON string appears to be truncated.

        Args:
            json_str: JSON string to check

        Returns:
            True if the JSON appears incomplete/truncated
        """
        # Strip whitespace from end
        trimmed = json_str.rstrip()

        # Check if it ends with proper closing for a JSON array/object
        if not trimmed:
            return True

        # JSON array should end with ]
        # JSON object should end with }
        # If it ends mid-string, mid-value, or with unclosed brackets, it's truncated
        if trimmed[-1] not in [']', '}']:
            return True

        # Count opening/closing brackets
        open_brackets = trimmed.count('[') + trimmed.count('{')
        close_brackets = trimmed.count(']') + trimmed.count('}')

        # If brackets don't match, likely truncated
        if open_brackets != close_brackets:
            return True

        return False

    def _sanitize_json_string(self, json_str: str) -> str:
        """
        Sanitize JSON string by escaping control characters.

        LLMs sometimes output literal control characters (newlines, tabs, etc.)
        within JSON strings, which are invalid in JSON. This function finds
        string values and escapes control characters within them.

        Args:
            json_str: Raw JSON string from LLM

        Returns:
            Sanitized JSON string safe for parsing
        """
        # Replace common control characters that appear literally in JSON strings
        # We need to be careful to only replace them inside string values, not
        # in the JSON structure itself (like between "key": "value" pairs)

        # Simple approach: replace literal control characters with escaped versions
        # This works because JSON structure uses {, }, [, ], :, , which aren't affected
        result = json_str

        # Replace literal tab, newline, carriage return with escaped versions
        # But only if they appear within quoted strings
        import re

        # Find all string values (content between quotes)
        def escape_string_content(match):
            content = match.group(1)
            # Escape control characters
            content = content.replace('\n', '\\n')
            content = content.replace('\r', '\\r')
            content = content.replace('\t', '\\t')
            content = content.replace('\b', '\\b')
            content = content.replace('\f', '\\f')
            return f'"{content}"'

        # Match quoted strings, but be careful with already-escaped quotes
        # This pattern matches: "any content including \" but not unescaped ""
        result = re.sub(r'"((?:[^"\\]|\\.)*)?"', escape_string_content, result)

        return result

    def _attempt_json_repair(self, json_str: str) -> Optional[str]:
        """
        Attempt to repair common JSON formatting issues from LLM output.

        This handles cases like:
        - Missing commas between array elements or object properties
        - Extra commas before closing brackets
        - Mismatched brackets (simple cases)

        Args:
            json_str: Potentially malformed JSON string

        Returns:
            Repaired JSON string, or None if repair failed
        """
        if not json_str:
            return None

        result = json_str

        # Fix 1: Missing comma after closing bracket/brace before opening quote
        # Pattern: ]  "key" or }  "key" should be ], "key" or }, "key"
        result = re.sub(r'(\]|\})\s*\n\s*(")', r'\1,\n  \2', result)

        # Fix 2: Missing comma between object elements (closing brace before opening brace)
        # Pattern: }  { should be }, {
        result = re.sub(r'(\})\s*\n\s*(\{)', r'\1,\n  \2', result)

        # Fix 3: Missing comma after string value before opening quote
        # Pattern: "value"  "key" should be "value", "key"
        result = re.sub(r'("\s*)\n\s*(")', r'\1,\n  \2', result)

        # Fix 4: Remove trailing commas before closing brackets
        # Pattern: ,  ] or ,  } should be  ] or  }
        result = re.sub(r',(\s*[\]}])', r'\1', result)

        # Fix 5: Missing comma between array elements (number/bool/null followed by opening brace/bracket)
        result = re.sub(r'(\d+|true|false|null)\s*\n\s*([{\[])', r'\1,\n  \2', result)

        return result

    def _reformat_as_json(
        self,
        prose_response: str,
        schema_example: str,
        max_tokens: int = 4096,
        stage_name: Optional[str] = None,
        commit_output_dir: Optional[str] = None
    ) -> Optional[str]:
        """
        Fallback: ask the model to reformat a prose response as a JSON array.
        Used when the primary call returns prose instead of JSON.
        Uses a minimal system prompt to avoid the conflicting OUTPUT FORMAT instructions.

        Args:
            prose_response: The prose response to reformat
            schema_example: Example JSON schema for the expected format
            max_tokens: Maximum tokens for the reformatting response
            stage_name: Original stage name (will be prefixed with "reformat-")
            commit_output_dir: Output directory for prompt dumping
        """
        if self.verbose or self.debug:
            print("[WARNING] Retrying with JSON reformatter...", file=sys.stderr)

        system_prompt = (
            "You are a JSON formatter. "
            "Convert the provided analysis to a JSON array. "
            "Return ONLY valid JSON — no prose, no markdown, no explanation."
        )
        user_prompt = (
            f"Convert this analysis to a JSON array.\n"
            f"Format: {schema_example}\n"
            f"If the analysis concludes there are no issues or all are false positives, return: []\n\n"
            f"Analysis:\n{prose_response}\n\n"
            f"JSON array:"
        )
        try:
            # Use reformat-{stage} as the stage name for prompt dumping
            reformat_stage = f"reformat-{stage_name}" if stage_name else None
            response = self.llm.analyze_code(
                system_prompt,
                user_prompt,
                stage_name=reformat_stage,
                commit_output_dir=commit_output_dir,
                max_tokens=max_tokens
            )
            return self._extract_json_array(response)
        except Exception:
            return None

    def _extract_json_array(self, response: str) -> Optional[str]:
        """
        Extract the JSON array from an LLM response that may contain prose.

        Some models wrap their analysis in markdown (e.g. [# Heading ...]) before
        appending the JSON array. The naive [.*] regex picks up the first [
        which is prose, not JSON. This method scans for a [ that actually starts
        a JSON array (followed by { for objects or ] for empty array).
        """
        # Try ```json code block first
        code_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', response, re.DOTALL)
        if code_match:
            return code_match.group(1)

        # Scan for [ that begins a JSON array, skipping prose-style [text] patterns
        pos = 0
        while pos < len(response):
            bracket_pos = response.find('[', pos)
            if bracket_pos == -1:
                break
            rest = response[bracket_pos + 1:].lstrip()
            if rest.startswith('{') or rest.startswith(']'):
                # Found a [ followed by { (array of objects) or ] (empty array)
                sub_match = re.search(r'\[.*\]', response[bracket_pos:], re.DOTALL)
                if sub_match:
                    return sub_match.group(0)
            pos = bracket_pos + 1

        return None

    def _categorize_changes(self, commit: Commit, context: Dict, commit_output_dir: Optional[str] = None) -> List[Dict]:
        """
        Task 1: Categorize changes using LLM.

        Args:
            commit: Commit to categorize
            context: Code context
            commit_output_dir: Output directory for this commit (for prompt dumping)

        Returns:
            List of change categories
        """
        # Build prompt for categorization
        system_prompt = self.prompts.load_review_core()

        # Build commit context with message if available
        commit_context = f"Subject: {commit.subject}"
        if commit.message and commit.message.strip() and commit.message != commit.subject:
            commit_context += f"\n\nCommit message:\n{commit.message}"

        user_prompt = f"""IMPORTANT: Your response must be a valid JSON array only. No prose, no explanation, no markdown. Start with [ and end with ].

Analyze this commit and categorize the changes.

For each distinct change, create a category with:
- id: CHANGE-1, CHANGE-2, etc.
- type: control-flow, resource-management, locking, initialization, cleanup, or other
- description: Brief description of what changed
- location: File and function name

{commit_context}

Diff:
{commit.diff}

Return ONLY a JSON array of changes. No text before or after the JSON.
Example format: [{{"id": "CHANGE-1", "type": "...", "description": "...", "location": "..."}}]
If there are no distinct changes, return: []

JSON array:"""

        response = self.llm.analyze_code(
            system_prompt,
            user_prompt,
            stage_name="categorize",
            commit_output_dir=commit_output_dir,
            max_tokens=config.CATEGORIZE_MAX_TOKENS
        )

        # Parse JSON response
        try:
            # Extract JSON from response (may have markdown code blocks)
            json_str = self._extract_json_array(response)
            if json_str is not None:
                # Sanitize JSON to handle literal control characters from LLM
                json_str = self._sanitize_json_string(json_str)
                categories = json.loads(json_str)
                return categories if isinstance(categories, list) else []
            else:
                if self.verbose or self.debug:
                    print("[WARNING] No JSON array found in categorization response", file=sys.stderr)
                    print(f"[WARNING] Response preview: {response[:200]}...", file=sys.stderr)
                schema = '[{{"id": "CHANGE-1", "type": "...", "description": "...", "location": "..."}}]'
                json_str = self._reformat_as_json(
                    response,
                    schema,
                    max_tokens=config.CATEGORIZE_MAX_TOKENS,
                    stage_name="categorize",
                    commit_output_dir=commit_output_dir
                )
                if json_str is not None:
                    try:
                        categories = json.loads(self._sanitize_json_string(json_str))
                        return categories if isinstance(categories, list) else []
                    except json.JSONDecodeError:
                        pass
        except json.JSONDecodeError as e:
            # Check if this looks like truncation
            is_truncated = self._looks_truncated(json_str if 'json_str' in locals() else response)

            if self.verbose or self.debug:
                print(f"[ERROR] Failed to parse categorization JSON: {e}", file=sys.stderr)

                if is_truncated:
                    print(f"[ERROR] Response appears truncated (incomplete JSON)", file=sys.stderr)
                    print(f"[ERROR] Last 100 chars: ...{response[-100:]}", file=sys.stderr)
                    print(f"[ERROR] Try increasing CATEGORIZE_MAX_TOKENS in config.py (current: {config.CATEGORIZE_MAX_TOKENS})", file=sys.stderr)
                else:
                    print(f"[ERROR] JSON format issue (not truncation)", file=sys.stderr)

            # Attempt to repair the JSON and try parsing again
            if not is_truncated and 'json_str' in locals() and json_str:
                if self.verbose or self.debug:
                    print(f"[WARNING] Attempting to repair malformed JSON...", file=sys.stderr)

                repaired = self._attempt_json_repair(json_str)
                if repaired:
                    try:
                        categories = json.loads(repaired)
                        if isinstance(categories, list):
                            if self.verbose or self.debug:
                                print(f"[SUCCESS] JSON repair successful, parsed {len(categories)} categories", file=sys.stderr)
                            return categories
                    except json.JSONDecodeError as repair_error:
                        if self.verbose or self.debug:
                            print(f"[ERROR] JSON repair failed: {repair_error}", file=sys.stderr)

        return []

    def _analyze_regressions(
        self,
        commit: Commit,
        categories: List[Dict],
        context: Dict,
        subsystems: List[str],
        commit_output_dir: Optional[str] = None
    ) -> List[Dict]:
        """
        Task 2: Analyze for regressions using LLM.

        Args:
            commit: Commit to analyze
            categories: Change categories from Task 1
            context: Code context
            subsystems: Matched subsystems
            commit_output_dir: Output directory for this commit (for prompt dumping)

        Returns:
            List of potential findings
        """
        # Build comprehensive system prompt with subsystem guides
        # Include backport guide if this is a backport with upstream reference
        include_backport = bool(commit.upstream_commit)

        system_prompt = self.prompts.build_system_prompt(
            include_technical_patterns=True,
            include_false_positive_guide=False,
            include_backport_guide=include_backport,
            subsystem_guides=subsystems
        )

        # Build user prompt with categorized changes
        categories_text = json.dumps(categories, indent=2)

        # Build commit context with message if available
        commit_context = f"Subject: {commit.subject}"
        if commit.message and commit.message.strip() and commit.message != commit.subject:
            commit_context += f"\n\nCommit message:\n{commit.message}"

        # Include full code context if available
        code_context_section = ""
        if context.get("code_context_formatted"):
            code_context_section = f"""
COMPLETE SOURCE CODE CONTEXT:
The following sections show the full function definitions (before and after changes),
their callers, and related code. Use this to understand the complete call paths and
verify your findings.

{context["code_context_formatted"]}

"""

        user_prompt = f"""IMPORTANT: Your response must be a valid JSON array only. No prose, no explanation, no markdown. Start with [ and end with ].

Analyze this commit for potential regressions.

{commit_context}

Categories of changes:
{categories_text}

{code_context_section}Full diff:
{commit.diff}

You have been provided with the full function definitions (both before and after
the changes) and their callers above. Use this complete context to:
1. Verify how the changed functions are actually called
2. Check what happens to return values
3. Trace error handling paths in both current and parent versions
4. Confirm your analysis against the actual source code, not just the diff

For each potential issue found, include a JSON object with:
- category: Which CHANGE-X this relates to
- type: Type of issue (use-after-free, memory-leak, null-deref, race-condition, etc.)
- message: Question or description of the issue (conversational, no ALL CAPS)
- evidence: Code snippets or call traces supporting the finding
- severity: low, medium, or high

Return ONLY a JSON array of findings. No text before or after the JSON.
Example format: [{{"category": "CHANGE-1", "type": "...", "message": "...", "evidence": "...", "severity": "..."}}]
If no issues found, return: []

JSON array:"""

        response = self.llm.analyze_code(
            system_prompt,
            user_prompt,
            stage_name="analyze",
            commit_output_dir=commit_output_dir,
            max_tokens=config.ANALYZE_MAX_TOKENS
        )

        # Parse JSON response
        try:
            json_str = self._extract_json_array(response)
            if json_str is not None:

                # Sanitize JSON: LLMs sometimes output literal control characters
                # in strings which are invalid in JSON. We need to escape them.
                # This handles newlines, tabs, carriage returns, etc.
                json_str = self._sanitize_json_string(json_str)

                findings = json.loads(json_str)
                return findings if isinstance(findings, list) else []
            else:
                if self.verbose or self.debug:
                    print("[WARNING] No JSON array found in regression analysis response", file=sys.stderr)
                    print(f"[WARNING] Response preview: {response[:200]}...", file=sys.stderr)
                schema = '[{{"category": "CHANGE-1", "type": "...", "message": "...", "evidence": "...", "severity": "..."}}]'
                json_str = self._reformat_as_json(
                    response,
                    schema,
                    max_tokens=config.ANALYZE_MAX_TOKENS,
                    stage_name="analyze",
                    commit_output_dir=commit_output_dir
                )
                if json_str is not None:
                    try:
                        findings = json.loads(self._sanitize_json_string(json_str))
                        return findings if isinstance(findings, list) else []
                    except json.JSONDecodeError:
                        pass
        except json.JSONDecodeError as e:
            # Check if this looks like truncation (incomplete JSON)
            is_truncated = self._looks_truncated(json_str if 'json_str' in locals() else response)

            if self.verbose or self.debug:
                print(f"[ERROR] Failed to parse regression analysis JSON: {e}", file=sys.stderr)

                # Try to show the problematic area
                if hasattr(e, 'pos'):
                    start = max(0, e.pos - 50)
                    end = min(len(response), e.pos + 50)
                    print(f"[ERROR] Context around error position {e.pos}: ...{response[start:end]}...", file=sys.stderr)

                if is_truncated:
                    print(f"[ERROR] Response appears truncated (incomplete JSON)", file=sys.stderr)
                    print(f"[ERROR] Last 100 chars: ...{response[-100:]}", file=sys.stderr)
                    print(f"[ERROR] Try increasing ANALYZE_MAX_TOKENS in config.py (current: {config.ANALYZE_MAX_TOKENS})", file=sys.stderr)
                else:
                    print(f"[ERROR] JSON format issue (not truncation)", file=sys.stderr)

                if self.llm.dump_prompts:
                    print(f"[ERROR] Check dump files in {self.llm.dump_dir}/ for full response", file=sys.stderr)

            # Attempt to repair the JSON and try parsing again
            if not is_truncated and 'json_str' in locals() and json_str:
                if self.verbose or self.debug:
                    print(f"[WARNING] Attempting to repair malformed JSON...", file=sys.stderr)

                repaired = self._attempt_json_repair(json_str)
                if repaired:
                    try:
                        findings = json.loads(repaired)
                        if isinstance(findings, list):
                            if self.verbose or self.debug:
                                print(f"[SUCCESS] JSON repair successful, parsed {len(findings)} findings", file=sys.stderr)
                            return findings
                    except json.JSONDecodeError as repair_error:
                        if self.verbose or self.debug:
                            print(f"[ERROR] JSON repair failed: {repair_error}", file=sys.stderr)

        return []

    def _verify_findings(
        self,
        findings: List[Dict],
        context: Dict,
        commit: Commit,
        commit_output_dir: Optional[str] = None
    ) -> List[Dict]:
        """
        Task 3: Verify findings using false-positive guide and adversarial persona.

        Now processes findings sequentially to maintain model focus and uses
        a skeptical persona to reduce confirmation bias.

        Args:
            findings: Findings to verify
            context: Code context
            commit: Commit being reviewed
            commit_output_dir: Output directory for this commit (for prompt dumping)

        Returns:
            List of verified findings
        """
        if not findings:
            return []

        # Step 1: Hallucination Pre-Pass
        # Deterministically check if cited evidence exists in the context/diff
        real_findings = []
        for finding in findings:
            if self._verify_evidence_physical_existence(finding, context, commit):
                real_findings.append(finding)
            elif self.verbose or self.debug:
                print(f"      [PRE-PASS] Discarding hallucinated finding: {finding.get('type')}")

        if not real_findings:
            return []

        # Step 2: Sequential Adversarial Verification
        verified = []
        
        # Define adversarial persona once
        adversarial_instruction = """
# ADVERSARIAL PERSONA: THE SKEPTICAL SENIOR MAINTAINER

You are a legendary, crusty Linux kernel maintainer. You have seen thousands of
incorrect bug reports from junior developers. Your default assumption is that
the reported bug is a FALSE POSITIVE until proven otherwise.

Your goal is to DISPROVE the reported finding. You must look for:
1. Implicit guard conditions (e.g. caller already holds the lock, or checked NULL)
2. Subtle kernel invariants that make the "bug" structurally impossible
3. Defensive programming suggestions masquerading as bugs
4. Hallucinations where the junior developer misunderstood the C code logic
"""

        for i, finding in enumerate(real_findings):
            if self.verbose:
                print(f"      Verifying finding {i+1}/{len(real_findings)}: {finding.get('type')}...")

            finding_type = finding.get('type', '')
            finding_text = json.dumps(finding, indent=2)

            # Build commit context with message if available
            commit_context = f"Subject: {commit.subject}"
            if commit.message and commit.message.strip() and commit.message != commit.subject:
                commit_context += f"\n\nCommit message:\n{commit.message}"

            # Step 2.1: Dynamically build system prompt for THIS specific finding category
            include_backport = bool(commit.upstream_commit)
            system_prompt_base = self.prompts.build_system_prompt(
                include_technical_patterns=True,
                include_false_positive_guide=True,
                include_backport_guide=include_backport,
                subsystem_guides=[],
                fp_category=finding_type
            )
            system_prompt = adversarial_instruction + "\n" + system_prompt_base

            # Include full code context for verification
            code_context_section = ""
            if context.get("code_context_formatted"):
                code_context_section = f"""
COMPLETE SOURCE CODE CONTEXT FOR VERIFICATION:
{context["code_context_formatted"]}
"""

            user_prompt = f"""IMPORTANT: Your response must be a valid JSON array. Return [] for a false positive, or [{{"...finding fields...", "confidence": 0.0}}] for a real finding.

Task: As a skeptical maintainer, verify if this specific finding is a REAL BUG or a FALSE POSITIVE.

{commit_context}

{code_context_section}Commit diff:
{commit.diff}

FINDING TO VERIFY:
{finding_text}

Rules:
1. Use the False Positive Prevention Guide strictly.
2. If this is clearly a FALSE POSITIVE (defensive programming, kernel invariant prevents it, hallucination), return [].
3. Otherwise return the finding (preserving all original fields) with a "confidence" field set to a scalar between 0.0 and 1.0:
   - 0.9–1.0: You are certain this is a real regression
   - 0.6–0.8: You believe this is likely real but have some uncertainty
   - 0.3–0.5: You have significant doubts but a human should review it
   - Below 0.3: Very weak signal; return [] instead

Example format: [{{"category": "CHANGE-1", "type": "...", "message": "...", "evidence": "...", "severity": "...", "confidence": 0.85}}]

JSON array (empty [] if false positive):"""

            try:
                response = self.llm.analyze_code(
                    system_prompt,
                    user_prompt,
                    stage_name="verify",
                    commit_output_dir=commit_output_dir,
                    max_tokens=config.VERIFY_MAX_TOKENS
                )
                
                json_str = self._extract_json_array(response)
                if json_str is not None:
                    json_str = self._sanitize_json_string(json_str)
                    result = json.loads(json_str)
                    if isinstance(result, list) and len(result) > 0:
                        verified.append(result[0])
                    elif self.verbose or self.debug:
                        print(f"      [VERIFY] Finding discarded as false positive: {finding.get('type')}")
                else:
                    # If parsing fails for one finding, we err on the side of caution with small models
                    if self.debug:
                        print(f"Verification failed to return JSON for finding {i+1}")
            except Exception as e:
                if self.debug:
                    print(f"Error verifying finding {i+1}: {e}")
                # On error, we keep it to be safe? Or discard? 
                # The directive was to reduce false positives, so maybe discard if we can't verify.
                # But for now, let's keep it to avoid missing real bugs due to transient errors.
                verified.append(finding)

        return verified

    def _verify_evidence_physical_existence(self, finding: Dict, context: Dict, commit: Commit) -> bool:
        """
        Hallucination Pre-Pass: Deterministically verify that cited code symbols
        actually exist in the context or diff.

        Two checks, both structural (no text understanding required):

        1. Code-symbol check: every underscore-containing identifier cited in the
           finding's message or evidence must appear somewhere in the diff or code
           context.  Underscore identifiers are unambiguously C symbols, not prose
           words, so any cited one that is absent is a hallucinated symbol.

        2. File-path check: any path-like token (word/word…/word.c|h) that refers
           to a file NOT in the commit's changed-files list is verified with
           git ls-files.  If the file does not exist in the tree the finding is
           almost certainly hallucinated.
        """
        # Combine message + evidence so we catch hallucinations stated in either field
        message = finding.get('message', '')
        evidence = finding.get('evidence', '')
        if isinstance(evidence, list):
            evidence = '\n'.join(str(item) for item in evidence)
        combined = message + "\n" + evidence
        if not combined.strip():
            return True

        full_text = commit.diff + "\n" + context.get("code_context_formatted", "")
        changed_files = set(commit.files)

        # --- Check 1: code-symbol identifiers (contain underscore → C symbol) ---
        # Extract only underscore-containing identifiers; these are never English prose.
        code_symbols = set(re.findall(r'\b[a-zA-Z_][a-zA-Z0-9]*(?:_[a-zA-Z0-9_]+)+\b', combined))
        for sym in code_symbols:
            if sym not in full_text:
                if self.verbose or self.debug:
                    print(f"      [PRE-PASS] Hallucinated symbol '{sym}' not in context")
                return False

        # --- Check 2: file-path tokens not present in the diff ---
        # Matches patterns like  drivers/char/mmtimer.c  net/wireless/pmsr.c
        file_paths = set(re.findall(r'\b(?:[a-zA-Z0-9_]+/)+[a-zA-Z0-9_]+\.[ch]\b', combined))
        for fpath in file_paths:
            if fpath in changed_files:
                continue  # Changed by this commit; fine
            if fpath in full_text:
                continue  # Already in code context; fine
            # Check whether the file actually exists in the tree
            result = subprocess.run(
                ['git', 'ls-files', '--error-unmatch', fpath],
                capture_output=True,
                cwd=self.git_dir
            )
            if result.returncode != 0:
                if self.verbose or self.debug:
                    print(f"      [PRE-PASS] Hallucinated file path '{fpath}' not in tree")
                return False

        return True

    def _propose_fixes(
        self,
        commit: Commit,
        findings: List[Dict],
        context: Dict,
        categories: List[Dict]
    ) -> str:
        """
        Task 5 (optional): Propose fix patches for verified findings.

        When the LLM client supports tool calling, the model can read actual
        source files via git_show/git_grep to produce more accurate patches.

        Returns:
            Unified diff text with proposed fixes, or empty string on failure.
        """
        findings_text = json.dumps(findings, indent=2)
        categories_text = json.dumps(categories, indent=2)

        commit_context = f"Subject: {commit.subject}"
        if commit.message and commit.message.strip() and commit.message != commit.subject:
            commit_context += f"\n\nCommit message:\n{commit.message}"

        code_context_section = ""
        if context.get("code_context_formatted"):
            code_context_section = (
                "FULL SOURCE CODE CONTEXT:\n"
                + context["code_context_formatted"]
                + "\n"
            )

        # Check if the LLM client supports tool calling
        has_tools = hasattr(self.llm, 'analyze_with_tools')

        if has_tools:
            system_prompt = (
                "You are a Linux kernel patch developer. "
                "You have access to git tools (git_show, git_grep) to read the actual source files. "
                "Use them to verify the exact current state of the code before writing patches. "
                "Output only the patch hunks — no prose, no explanation."
            )
            tool_instruction = (
                f"\nBefore writing each patch:\n"
                f"1. Use git_show with commit='{commit.sha}' and the relevant file path to read the "
                f"current source around the issue location\n"
                f"2. Verify the exact line numbers and surrounding context\n"
                f"3. Then write the patch with correct line numbers\n"
            )
        else:
            system_prompt = (
                "You are a Linux kernel patch developer. "
                "Generate minimal, correct unified diff patches to fix the identified issues. "
                "Output only the patch hunks — no prose, no explanation."
            )
            tool_instruction = ""

        user_prompt = f"""IMPORTANT: Output unified diff patch hunks only. No prose before or after the patches.

{commit_context}

Change categories:
{categories_text}

{code_context_section}Original diff that introduced the issues:
{commit.diff}

Verified issues to fix:
{findings_text}
{tool_instruction}
Generate a unified diff patch for each issue using standard format:
  # Finding: <finding category and type>
  --- a/path/to/file.c
  +++ b/path/to/file.c
  @@ -line,count +line,count @@ context_function
   context line
  -removed line
  +added line
   context line

Rules:
- One patch hunk per finding; label each with the finding ID (e.g. CHANGE-2 / memory-leak)
- Use correct file paths (relative, as in the original diff)
- Keep patches minimal — fix only the specific issue, do not refactor
- If a fix is not possible to express as a diff (e.g. needs design change), write: # No patch: <reason>

Patches:"""

        try:
            if has_tools:
                response = self.llm.analyze_with_tools(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_iterations=self.max_tool_iterations,
                    max_tokens=config.ANALYZE_MAX_TOKENS
                )
            else:
                response = self.llm.analyze_code(
                    system_prompt, user_prompt,
                    max_tokens=config.ANALYZE_MAX_TOKENS
                )
            patches = response.strip()
            if not self._is_valid_diff(patches):
                preview = '\n'.join(patches.splitlines()[:5])
                print(f"[WARNING] Proposed fix patches do not look like a valid diff; discarding", file=sys.stderr)
                if self.debug:
                    print(f"Discarded patch content (first lines):\n{preview}", file=sys.stderr)
                return None
            return patches
        except Exception as e:
            if self.verbose or self.debug:
                print(f"[WARNING] Failed to propose fixes: {e}", file=sys.stderr)
            return None

    @staticmethod
    def _is_valid_diff(text: str) -> bool:
        """Return True if text looks like a unified diff (has @@ hunk and --- / +++ headers)."""
        if not text:
            return False
        lines = text.splitlines()
        has_hunk = any(l.startswith('@@') for l in lines)
        has_header = any(l.startswith('---') or l.startswith('+++') for l in lines)
        return has_hunk and has_header

    def _generate_summary(
        self,
        commit: Commit,
        findings: List[Dict],
        upstream_verification: Optional[Dict] = None
    ) -> str:
        """
        Generate 1-2 sentence summary of review.

        Args:
            commit: Commit object
            findings: Verified findings
            upstream_verification: Upstream verification result (optional)

        Returns:
            Summary string
        """
        if not findings:
            base = "This commit appears correct with no regressions found."
            if upstream_verification and upstream_verification.get('upstream_commit'):
                upstream = upstream_verification['upstream_commit']
                base += f" Verified against upstream: {upstream.subject}"
            return base

        count = len(findings)
        types = set(f.get('type', 'issue') for f in findings)

        # Check for upstream/downstream split
        if upstream_verification:
            in_upstream = len(upstream_verification.get('findings_in_upstream', []))
            downstream_only = len(upstream_verification.get('findings_only_downstream', []))

            if downstream_only > 0:
                return (f"This commit has {count} potential issues, "
                       f"{downstream_only} unique to this downstream tree that should be reviewed.")
            elif in_upstream > 0:
                return (f"This commit has {count} potential issues also present in upstream. "
                       f"Consider reporting to upstream maintainers.")

        # Default summary (existing logic)
        if count == 1:
            issue_type = findings[0].get('type', 'issue')
            return f"This commit has a potential {issue_type} that should be reviewed."
        else:
            types_str = ", ".join(sorted(types))
            return f"This commit has {count} potential issues ({types_str}) that should be reviewed."
