"""Load and adapt review prompts for code-only analysis."""

import os
from typing import List


class PromptLoader:
    """Load and manage review protocol prompts."""

    def __init__(self, prompts_dir: str = None):
        """
        Initialize prompt loader.

        Args:
            prompts_dir: Directory containing prompt markdown files.
                        If None, uses prompts/ relative to installation directory.
        """
        if prompts_dir is None:
            # Get the directory where this module is located
            module_dir = os.path.dirname(os.path.abspath(__file__))
            # Go up one level to the installation directory
            install_dir = os.path.dirname(module_dir)
            # Prompts are in install_dir/prompts
            prompts_dir = os.path.join(install_dir, "prompts")

        self.prompts_dir = os.path.abspath(prompts_dir)

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

    def load_false_positive_guide(self) -> str:
        """Load false-positive-guide.md (verification checks)."""
        return self.load_file("false-positive-guide.md")

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
        subsystem_guides: List[str] = None
    ) -> str:
        """
        Build comprehensive system prompt for LLM.

        Args:
            include_technical_patterns: Include bug pattern guide
            include_false_positive_guide: Include verification guide
            subsystem_guides: List of subsystem guide filenames to include

        Returns:
            Complete system prompt
        """
        parts = [self.load_review_core()]

        if include_technical_patterns:
            parts.append("\n# TECHNICAL PATTERNS\n\n" + self.load_technical_patterns())

        if include_false_positive_guide:
            parts.append("\n# FALSE POSITIVE PREVENTION\n\n" + self.load_false_positive_guide())

        if subsystem_guides:
            subsystem_content = self.load_subsystem_guides(subsystem_guides)
            if subsystem_content:
                parts.append("\n# SUBSYSTEM-SPECIFIC PATTERNS\n\n" + subsystem_content)

        return "\n\n".join(parts)
