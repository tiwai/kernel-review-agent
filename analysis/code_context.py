"""Load code context for deeper LLM analysis."""

import subprocess
import re
from typing import List, Dict, Optional
from git_integration import Commit


class CodeContextLoader:
    """Load source code context for LLM analysis."""

    def __init__(self, commit: Commit, verbose: bool = False, debug: bool = False, git_dir: str = '.'):
        """
        Initialize context loader.

        Args:
            commit: Commit to analyze
            verbose: Enable verbose output
            debug: Enable debug output
            git_dir: Git repository directory (default: current directory)
        """
        self.commit = commit
        self.verbose = verbose
        self.debug = debug
        self.git_dir = git_dir

    def load_full_context(self) -> Dict:
        """
        Load comprehensive code context for the commit.

        Returns:
            Dictionary with full function definitions, callers, etc.
        """
        if self.debug:
            print(f"[DEBUG] Loading full code context for commit {self.commit.sha[:12]}")

        context = {
            "changed_functions": [],
            "function_definitions": {},
            "callers": {},
            "headers": {}
        }

        # Extract changed functions from diff
        changed_functions = self._extract_changed_functions_from_diff()

        if self.debug:
            print(f"[DEBUG] Found {len(changed_functions)} changed functions")

        # For each changed function, load full definition and callers
        for func_info in changed_functions:
            func_name = func_info['name']
            file_path = func_info['file']

            if self.debug:
                print(f"[DEBUG] Loading context for {func_name} in {file_path}")

            # Load full function definition (current and parent)
            current_def = self._load_function_definition(file_path, func_name, self.commit.sha)
            parent_def = self._load_function_definition(file_path, func_name, f"{self.commit.sha}^")

            if current_def or parent_def:
                context["function_definitions"][func_name] = {
                    "current": current_def,
                    "parent": parent_def,
                    "file": file_path
                }

            # Find callers
            callers = self._find_function_callers(func_name)
            if callers:
                context["callers"][func_name] = callers

        # Load related headers
        for file_path in self.commit.files:
            if file_path.endswith('.h'):
                header_content = self._load_file(file_path, self.commit.sha)
                if header_content:
                    context["headers"][file_path] = header_content

        context["changed_functions"] = changed_functions
        return context

    def _extract_changed_functions_from_diff(self) -> List[Dict]:
        """
        Extract function names and locations from diff.

        Returns:
            List of dicts with function name and file path
        """
        functions = []
        current_file = None

        for line in self.commit.diff.split('\n'):
            # Track current file
            if line.startswith('diff --git'):
                match = re.search(r'b/(.+)$', line)
                if match:
                    current_file = match.group(1)

            # Extract function from hunk header
            elif line.startswith('@@') and current_file:
                # Format: @@ -old +new @@ function_name(args)
                # Example: @@ -333,6 +333,10 @@ static int ipv6_srh_rcv(struct sk_buff *skb)
                match = re.search(r'@@.*?@@\s*(.+)', line)
                if match:
                    func_context = match.group(1).strip()
                    # Extract function name - handle return types and qualifiers
                    # Patterns: "static int func(...)", "func(...)", "bool func(...)"
                    func_match = re.search(r'\b(\w+)\s*\(', func_context)
                    if func_match:
                        func_name = func_match.group(1)
                        # Avoid common keywords that aren't function names
                        if func_name not in ['if', 'while', 'for', 'switch', 'return']:
                            functions.append({
                                "name": func_name,
                                "file": current_file,
                                "context": func_context
                            })

        # Remove duplicates while preserving order
        seen = set()
        unique_functions = []
        for func in functions:
            key = (func['name'], func['file'])
            if key not in seen:
                seen.add(key)
                unique_functions.append(func)

        return unique_functions

    def _load_function_definition(self, file_path: str, func_name: str, commit_ref: str) -> Optional[str]:
        """
        Load complete function definition from a specific commit.

        Args:
            file_path: Path to file
            func_name: Function name
            commit_ref: Git commit reference (SHA or SHA^)

        Returns:
            Function definition or None if not found
        """
        try:
            # Load full file content
            result = subprocess.run(
                ['git', '-C', self.git_dir, 'show', f'{commit_ref}:{file_path}'],
                capture_output=True,
                text=True,
                check=True,
                timeout=30
            )
            file_content = result.stdout

            # Extract function definition
            # Simple heuristic: find function signature and grab until matching brace
            lines = file_content.split('\n')
            func_def = []
            in_function = False
            brace_count = 0

            for i, line in enumerate(lines):
                # Look for function definition
                if not in_function:
                    # Match: return_type function_name(
                    if re.search(rf'\b{re.escape(func_name)}\s*\(', line):
                        in_function = True
                        func_def.append(line)
                        brace_count += line.count('{') - line.count('}')
                else:
                    func_def.append(line)
                    brace_count += line.count('{') - line.count('}')

                    # Function complete when braces balance
                    if brace_count == 0 and '{' in ''.join(func_def):
                        break

            if func_def:
                return '\n'.join(func_def)

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            if self.debug:
                print(f"[DEBUG] Could not load {func_name} from {commit_ref}:{file_path}: {e}")

        return None

    def _find_function_callers(self, func_name: str) -> List[Dict]:
        """
        Find callers of a function using git grep.

        Args:
            func_name: Function name to search for

        Returns:
            List of caller locations
        """
        try:
            # Search for function calls
            result = subprocess.run(
                ['git', '-C', self.git_dir, 'grep', '-n', f'{func_name}(', '--', '*.c'],
                capture_output=True,
                text=True,
                timeout=30
            )

            callers = []
            for line in result.stdout.split('\n'):
                if line and ':' in line:
                    parts = line.split(':', 2)
                    if len(parts) >= 3:
                        callers.append({
                            "file": parts[0],
                            "line": parts[1],
                            "code": parts[2].strip()
                        })

            # Limit to first 10 callers to avoid overwhelming the LLM
            return callers[:10]

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            if self.debug:
                print(f"[DEBUG] Could not find callers for {func_name}: {e}")
            return []

    def _load_file(self, file_path: str, commit_ref: str) -> Optional[str]:
        """Load complete file content."""
        try:
            result = subprocess.run(
                ['git', '-C', self.git_dir, 'show', f'{commit_ref}:{file_path}'],
                capture_output=True,
                text=True,
                check=True,
                timeout=30
            )
            return result.stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None

    def format_context_for_prompt(self, context: Dict) -> str:
        """
        Format loaded context for inclusion in LLM prompt.

        Args:
            context: Context dictionary from load_full_context()

        Returns:
            Formatted text for prompt
        """
        sections = []

        # Changed functions summary
        if context["changed_functions"]:
            sections.append("CHANGED FUNCTIONS:")
            for func in context["changed_functions"]:
                sections.append(f"  - {func['name']} in {func['file']}")
            sections.append("")

        # Function definitions
        if context["function_definitions"]:
            sections.append("FULL FUNCTION DEFINITIONS:")
            sections.append("="*70)
            for func_name, func_data in context["function_definitions"].items():
                sections.append(f"\nFunction: {func_name} in {func_data['file']}")
                sections.append("-"*70)

                if func_data["parent"]:
                    sections.append(f"\nPARENT VERSION (before changes):")
                    sections.append(func_data["parent"])
                    sections.append("")

                if func_data["current"]:
                    sections.append(f"\nCURRENT VERSION (after changes):")
                    sections.append(func_data["current"])
                    sections.append("")
            sections.append("="*70)
            sections.append("")

        # Callers
        if context["callers"]:
            sections.append("FUNCTION CALLERS:")
            sections.append("-"*70)
            for func_name, callers in context["callers"].items():
                sections.append(f"\nCallers of {func_name}:")
                for caller in callers[:5]:  # Limit to 5 for brevity
                    sections.append(f"  {caller['file']}:{caller['line']}: {caller['code']}")
            sections.append("")

        # Headers
        if context["headers"]:
            sections.append("RELATED HEADERS:")
            sections.append("-"*70)
            for header_path, content in context["headers"].items():
                sections.append(f"\n{header_path}:")
                # Include just the first 50 lines to avoid overwhelming
                header_lines = content.split('\n')[:50]
                sections.append('\n'.join(header_lines))
                if len(content.split('\n')) > 50:
                    sections.append("... (truncated)")
            sections.append("")

        return '\n'.join(sections)
