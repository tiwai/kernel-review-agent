"""Load and adapt review prompts for code-only analysis."""

import os
from typing import List, Optional, Dict

from .prompt_set_mapper import PromptSetMapper


class PromptLoader:
    """Load and manage review protocol prompts."""

    def __init__(
        self,
        prompts_dir: str = None,
        prompt_set: str = 'default',
        model_name: Optional[str] = None,
        config_overrides: Optional[Dict[str, str]] = None
    ):
        """
        Initialize prompt loader with prompt-set support.

        Args:
            prompts_dir: Base prompts directory containing prompt sets.
                        If None, uses prompts/ relative to installation directory.
            prompt_set: Explicit prompt set name or 'auto' for auto-detection
            model_name: Model name for auto-detection (if prompt_set='auto')
            config_overrides: Custom model→set mappings from config file
        """
        if prompts_dir is None:
            # Get the directory where this module is located
            module_dir = os.path.dirname(os.path.abspath(__file__))
            # Go up one level to the installation directory
            install_dir = os.path.dirname(module_dir)
            # Prompts are in install_dir/prompts
            prompts_dir = os.path.join(install_dir, "prompts")

        self.base_dir = os.path.abspath(prompts_dir)

        # Determine which prompt set to use
        mapper = PromptSetMapper(self.base_dir)
        resolved_set = mapper.select_prompt_set(
            model_name or 'unknown',
            explicit_set=prompt_set,
            config_overrides=config_overrides
        )

        # Store prompt set name and resolve to directory
        self.prompt_set = resolved_set
        self.prompts_dir = self._resolve_prompt_set_dir(resolved_set)

        # Load metadata for this prompt set
        self.metadata = mapper.metadata.get('sets', {}).get(resolved_set, {})

    def _resolve_prompt_set_dir(self, prompt_set: str) -> str:
        """
        Resolve prompt set name to actual directory path.

        Supports both new structure (prompts/<set>/) and legacy structure (prompts/).

        Args:
            prompt_set: Prompt set name (e.g., 'default', 'small')

        Returns:
            Absolute path to the prompt set directory

        Raises:
            RuntimeError: If prompt set directory not found
        """
        # New structure: prompts/<set>/
        set_dir = os.path.join(self.base_dir, prompt_set)
        if os.path.isdir(set_dir) and os.path.isfile(os.path.join(set_dir, 'review-core.md')):
            return set_dir

        # Legacy structure: prompts/ (flat directory)
        # If review-core.md exists at base level, treat base as the prompt set
        if os.path.isfile(os.path.join(self.base_dir, 'review-core.md')):
            if prompt_set != 'default':
                print(f"Warning: Prompt set '{prompt_set}' not found, using legacy flat structure")
            return self.base_dir

        raise RuntimeError(
            f"Prompt set '{prompt_set}' not found. "
            f"Expected directory: {set_dir} with review-core.md"
        )

    def get_available_subsystems(self) -> List[str]:
        """
        Get list of available subsystem guides for current prompt set.

        Returns:
            List of subsystem filenames (e.g., ['rcu.md', 'locking.md'])
        """
        subsys_dir = os.path.join(self.prompts_dir, 'subsystem')
        if not os.path.isdir(subsys_dir):
            return []

        try:
            return sorted([
                f for f in os.listdir(subsys_dir)
                if f.endswith('.md') and os.path.isfile(os.path.join(subsys_dir, f))
            ])
        except OSError:
            return []

    def load_file(self, filename: str) -> str:
        """Load a prompt file."""
        filepath = os.path.join(self.prompts_dir, filename)
        try:
            with open(filepath, 'r') as f:
                return f.read()
        except FileNotFoundError:
            raise RuntimeError(f"Prompt file not found: {filepath}")

    def load_review_core(self) -> str:
        """
        Load review-core.md adapted for code-only review.

        Modifications:
        - Focus on code changes only
        - Remove commit message tag evaluation
        - Remove Fixes tag verification
        - Remove lore thread checking
        """
        content = self.load_file("review-core.md")

        # Add adaptation note at the beginning
        adaptation_note = """
# ADAPTATION FOR CODE-ONLY REVIEW

This review focuses ONLY on code changes. Do NOT evaluate:
- Commit message quality or formatting
- Fixes tags or commit tags
- Subjective reviews
- Lore thread discussions

Focus exclusively on finding potential regressions in the code changes.

---

"""
        return adaptation_note + content

    def load_technical_patterns(self) -> str:
        """Load technical-patterns.md (bug pattern encyclopedia)."""
        return self.load_file("technical-patterns.md")

    def load_false_positive_guide(self, category: str = None) -> str:
        """
        Load false-positive-guide.md (verification checks).
        Supports modular guides if category is provided.
        """
        core_guide = self.load_file("fp-guide-core.md")
        
        if not category:
            # Fallback to the original full guide if it exists, or just core
            try:
                return self.load_file("false-positive-guide.md")
            except RuntimeError:
                return core_guide

        # Map categories to specific guide files
        category_map = {
            'lock': 'fp-guide-locking.md',
            'deadlock': 'fp-guide-locking.md',
            'uaf': 'fp-guide-refcount.md',
            'use-after-free': 'fp-guide-refcount.md',
            'refcount': 'fp-guide-refcount.md',
            'leak': 'fp-guide-leaks.md',
            'race': 'fp-guide-races.md',
            'null': 'fp-guide-null.md'
        }

        specific_guide_file = None
        for key, filename in category_map.items():
            if key in category.lower():
                specific_guide_file = filename
                break
        
        if specific_guide_file:
            try:
                specific_content = self.load_file(specific_guide_file)
                return core_guide + "\n\n" + specific_content
            except RuntimeError:
                return core_guide
        
        return core_guide

    def load_backport_verification_guide(self) -> str:
        """Load backport-verification.md (backport quality checks)."""
        try:
            return self.load_file("backport-verification.md")
        except RuntimeError:
            # Backport guide is optional
            return ""

    def load_callstack_guide(self) -> str:
        """Load callstack.md (bidirectional analysis)."""
        return self.load_file("callstack.md")

    def load_inline_template(self) -> str:
        """Load inline-template.md (LKML formatting rules)."""
        return self.load_file("inline-template.md")

    def load_subsystem_guide(self, subsystem_file: str) -> str:
        """
        Load a specific subsystem guide.

        Args:
            subsystem_file: Filename like "rcu.md", "bpf.md", etc.

        Returns:
            Subsystem guide content
        """
        filepath = os.path.join("subsystem", subsystem_file)
        return self.load_file(filepath)

    def load_subsystem_guides(self, subsystem_files: List[str]) -> str:
        """
        Load multiple subsystem guides and concatenate.

        Args:
            subsystem_files: List of subsystem filenames

        Returns:
            Concatenated subsystem guide content
        """
        if not subsystem_files:
            return ""

        guides = []
        for filename in subsystem_files:
            try:
                guide = self.load_subsystem_guide(filename)
                guides.append(f"# SUBSYSTEM GUIDE: {filename}\n\n{guide}\n\n")
            except RuntimeError as e:
                # Log warning but continue
                print(f"Warning: {e}")
                continue

        return "\n".join(guides)

    def build_system_prompt(
        self,
        include_technical_patterns: bool = True,
        include_false_positive_guide: bool = False,
        include_backport_guide: bool = False,
        subsystem_guides: List[str] = None,
        fp_category: str = None
    ) -> str:
        """
        Build comprehensive system prompt for LLM.

        Args:
            include_technical_patterns: Include bug pattern guide
            include_false_positive_guide: Include verification guide
            include_backport_guide: Include backport verification guide
            subsystem_guides: List of subsystem guide filenames to include
            fp_category: Specific category for false-positive guide

        Returns:
            Complete system prompt
        """
        parts = [self.load_review_core()]

        if include_technical_patterns:
            parts.append("\n# TECHNICAL PATTERNS\n\n" + self.load_technical_patterns())

        if include_false_positive_guide:
            parts.append("\n# FALSE POSITIVE PREVENTION\n\n" + self.load_false_positive_guide(fp_category))

        if include_backport_guide:
            backport_content = self.load_backport_verification_guide()
            if backport_content:
                parts.append("\n# BACKPORT VERIFICATION\n\n" + backport_content)

        if subsystem_guides:
            subsystem_content = self.load_subsystem_guides(subsystem_guides)
            if subsystem_content:
                parts.append("\n# SUBSYSTEM-SPECIFIC PATTERNS\n\n" + subsystem_content)

        # Override the OUTPUT FORMAT from review-core.md for API use.
        # The user prompt specifies the exact JSON format required for each task.
        parts.append("""
# OUTPUT FORMAT OVERRIDE

CRITICAL: This agent operates via API, not as an interactive session.
Ignore the OUTPUT FORMAT section above. Do NOT output FINAL REGRESSIONS FOUND,
FINAL TOKENS USED, Assisted-by, or any prose summary.
Your response must be ONLY the JSON array requested in the user prompt.
""")

        return "\n\n".join(parts)
