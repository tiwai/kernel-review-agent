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
            print(f"Loading full code context for commit {self.commit.sha[:12]}")

        context = {
            "changed_functions": [],
            "function_definitions": {},
            "callers": {},
            "headers": {}
        }

        # Extract changed functions from diff
        changed_functions = self._extract_changed_functions_from_diff()

        if self.debug:
            print(f"Found {len(changed_functions)} changed functions")

        # For each changed function, load full definition and callers
        for func_info in changed_functions:
            func_name = func_info['name']
            file_path = func_info['file']

            if self.debug:
                print(f"Loading context for {func_name} in {file_path}")

            # Load full function definition (current and parent)
            # In patch mode, commit.sha is a filename, not a git ref, so use HEAD
            commit_ref = self._get_commit_ref()
            current_def = self._load_function_definition(file_path, func_name, commit_ref)
            parent_def = self._load_function_definition(file_path, func_name, f"{commit_ref}^")

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

        # Extract and load timer/workqueue callback functions
        # These are critical for detecting API misuse (e.g., setup_timer vs timer_setup signature mismatch)
        timer_callbacks = self._extract_timer_callbacks_from_diff()

        if self.debug and timer_callbacks:
            print(f"Found {len(timer_callbacks)} timer/workqueue callbacks")

        for callback_info in timer_callbacks:
            callback_name = callback_info['name']
            file_path = callback_info['file']

            if self.debug:
                print(f"Loading timer callback: {callback_name} in {file_path}")

            # Load callback function definition
            # In patch mode, commit.sha is a filename, not a git ref, so use HEAD
            commit_ref = self._get_commit_ref()
            current_def = self._load_function_definition(file_path, callback_name, commit_ref)
            parent_def = self._load_function_definition(file_path, callback_name, f"{commit_ref}^")

            if current_def or parent_def:
                # Mark as timer callback for special attention
                context["function_definitions"][callback_name] = {
                    "current": current_def,
                    "parent": parent_def,
                    "file": file_path,
                    "is_timer_callback": True,
                    "timer_api": callback_info.get('api')
                }

        # Load related headers
        commit_ref = self._get_commit_ref()
        for file_path in self.commit.files:
            if file_path.endswith('.h'):
                header_content = self._load_file(file_path, commit_ref)
                if header_content:
                    context["headers"][file_path] = header_content

        context["changed_functions"] = changed_functions
        return context

    def _get_commit_ref(self) -> str:
        """
        Get a valid git reference for the commit.

        In patch mode, commit.sha is a filename (e.g., "test.patch"), not a git ref.
        Detect this and return "HEAD" instead.

        Returns:
            Git reference (commit SHA or "HEAD" for patches)
        """
        # Git SHAs are hex strings (0-9, a-f). If commit.sha contains other chars
        # (like dots, slashes, or non-hex chars), it's likely a patch filename.
        import re
        if re.match(r'^[0-9a-fA-F]+$', self.commit.sha):
            # Valid hex SHA
            return self.commit.sha
        else:
            # Patch mode - use HEAD
            return "HEAD"

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
                # Match " b/" (with space) to avoid matching b/ in paths like "usb/qcom"
                match = re.search(r' b/(.+)$', line)
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

    def _extract_timer_callbacks_from_diff(self) -> List[Dict]:
        """
        Extract timer/workqueue callback functions mentioned in timer setup calls.

        Looks for patterns like:
        - timer_setup(&obj->timer, callback_func, flags)
        - setup_timer(&obj->timer, callback_func, data)
        - hrtimer_setup(&obj->timer, callback_func, ...)
        - INIT_DELAYED_WORK(&obj->work, callback_func)
        - INIT_WORK(&obj->work, callback_func)

        Returns:
            List of dicts with callback name, file path, and API used
        """
        callbacks = []
        current_file = None

        # Patterns for timer/work setup functions
        setup_patterns = [
            (r'timer_setup\s*\(\s*[^,]+,\s*(\w+)', 'timer_setup'),
            (r'setup_timer\s*\(\s*[^,]+,\s*(\w+)', 'setup_timer'),
            (r'hrtimer_setup\s*\(\s*[^,]+,\s*(\w+)', 'hrtimer_setup'),
            (r'INIT_DELAYED_WORK\s*\(\s*[^,]+,\s*(\w+)', 'INIT_DELAYED_WORK'),
            (r'INIT_WORK\s*\(\s*[^,]+,\s*(\w+)', 'INIT_WORK'),
            (r'queue_work\w*\s*\([^,]+,\s*[^,]+,\s*(\w+)', 'queue_work'),
        ]

        for line in self.commit.diff.split('\n'):
            # Track current file
            if line.startswith('diff --git'):
                # Match " b/" (with space) to avoid matching b/ in paths like "usb/qcom"
                match = re.search(r' b/(.+)$', line)
                if match:
                    current_file = match.group(1)

            # Look for timer/work setup in added or context lines
            elif current_file and (line.startswith('+') or line.startswith(' ')):
                # Remove the diff prefix
                code_line = line[1:] if line[0] in ['+', ' '] else line

                # Check each pattern
                for pattern, api_name in setup_patterns:
                    match = re.search(pattern, code_line)
                    if match:
                        callback_name = match.group(1)
                        # Avoid false positives (NULL, macros, etc.)
                        if callback_name and callback_name not in ['NULL', '0', 'null']:
                            callbacks.append({
                                "name": callback_name,
                                "file": current_file,
                                "api": api_name
                            })

        # Remove duplicates
        seen = set()
        unique_callbacks = []
        for cb in callbacks:
            key = (cb['name'], cb['file'])
            if key not in seen:
                seen.add(key)
                unique_callbacks.append(cb)

        return unique_callbacks

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
                print(f"Could not load {func_name} from {commit_ref}:{file_path}: {e}")

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
                print(f"Could not find callers for {func_name}: {e}")
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

                # Highlight timer/workqueue callbacks
                if func_data.get("is_timer_callback"):
                    api = func_data.get("timer_api", "unknown")
                    sections.append(f"⚠️  TIMER/WORK CALLBACK - Used with {api}")
                    sections.append("    CHECK: Callback signature MUST match the API requirements!")
                    if api == "timer_setup":
                        sections.append("    timer_setup() requires: void callback(struct timer_list *t)")
                    elif api == "setup_timer":
                        sections.append("    setup_timer() requires: void callback(unsigned long data)")
                    elif api == "hrtimer_setup":
                        sections.append("    hrtimer_setup() requires: enum hrtimer_restart callback(struct hrtimer *timer)")

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
