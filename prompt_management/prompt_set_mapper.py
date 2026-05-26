"""Map model names to appropriate prompt sets."""

import os
import json
import re
from typing import Optional, Dict, List, Tuple


class PromptSetMapper:
    """Map model names to prompt sets based on configuration and patterns."""

    def __init__(self, prompts_dir: str):
        """
        Initialize prompt set mapper.

        Args:
            prompts_dir: Base prompts directory containing prompt-sets.json
        """
        self.prompts_dir = prompts_dir
        self.mapping_file = os.path.join(prompts_dir, 'prompt-sets.json')
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> Dict:
        """
        Load prompt-sets.json metadata file.

        Returns:
            Metadata dictionary, or empty dict if file doesn't exist
        """
        if not os.path.isfile(self.mapping_file):
            return {}

        try:
            with open(self.mapping_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load {self.mapping_file}: {e}")
            return {}

    def select_prompt_set(
        self,
        model_name: str,
        explicit_set: Optional[str] = None,
        config_overrides: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Determine which prompt set to use.

        Priority order:
        1. Explicit CLI argument (if not 'auto')
        2. Config file custom mappings
        3. Auto-detect from prompt-sets.json model_mappings
        4. Pattern matching for model families
        5. Fallback to 'default'

        Args:
            model_name: LLM model name
            explicit_set: User-specified set via CLI (highest priority)
            config_overrides: Custom mappings from config file

        Returns:
            Prompt set directory name (e.g., 'default', 'small')
        """
        # Priority 1: Explicit CLI argument (not 'auto')
        if explicit_set and explicit_set != 'auto':
            return self._validate_set(explicit_set)

        # Priority 2: Config file custom mappings
        if config_overrides and model_name in config_overrides:
            return self._validate_set(config_overrides[model_name])

        # Priority 3: Auto-detect from prompt-sets.json exact mappings
        if self.metadata:
            model_mappings = self.metadata.get('model_mappings', {})
            if model_name in model_mappings:
                return model_mappings[model_name]

            # Priority 4: Pattern matching for model families
            matched_set = self._match_model_pattern(model_name)
            if matched_set:
                return matched_set

        # Fallback: default
        return 'default'

    def _match_model_pattern(self, model_name: str) -> Optional[str]:
        """
        Match model name against common patterns.

        Patterns:
        - Family prefix (e.g., 'gpt-3.5' → small)
        - Size suffix (e.g., ':7b', ':8b' → small)
        - Tier suffix (e.g., '-flash' → small, '-pro' → default)

        Args:
            model_name: Model name to match

        Returns:
            Matched prompt set name, or None if no match
        """
        patterns = self._get_pattern_mappings()

        for pattern, prompt_set in patterns:
            if self._matches_pattern(model_name, pattern):
                return prompt_set

        return None

    def _get_pattern_mappings(self) -> List[Tuple[str, str]]:
        """
        Get pattern-based mappings for model families.

        Returns:
            List of (pattern, prompt_set) tuples
        """
        # Patterns are evaluated in order, first match wins
        return [
            # Small models - by family prefix
            (r'^gpt-3\.5', 'small'),
            (r'^gpt-4o-mini', 'small'),

            # Small models - by tier suffix
            (r'-flash$', 'small'),
            (r'-flash-', 'small'),

            # Small models - by size suffix (Ollama style)
            (r':7b$', 'small'),
            (r':8b$', 'small'),
            (r':7b-', 'small'),
            (r':8b-', 'small'),

            # Small models - specific families
            (r'^llama3\.1:7b', 'small'),
            (r'^llama3\.1:8b', 'small'),
            (r'^llama3:7b', 'small'),
            (r'^llama3:8b', 'small'),
            (r'^qwen.*:7b', 'small'),
            (r'^mistral.*:7b', 'small'),

            # Default for pro/larger models
            (r'-pro$', 'default'),
            (r'-pro-', 'default'),
            (r'^gpt-4', 'default'),
            (r'^claude-', 'default'),
            (r'^gemini.*-pro', 'default'),
        ]

    def _matches_pattern(self, model_name: str, pattern: str) -> bool:
        """
        Check if model name matches pattern.

        Args:
            model_name: Model name to check
            pattern: Regex pattern

        Returns:
            True if pattern matches
        """
        try:
            return bool(re.search(pattern, model_name, re.IGNORECASE))
        except re.error:
            return False

    def _validate_set(self, prompt_set: str) -> str:
        """
        Validate that a prompt set exists.

        Args:
            prompt_set: Prompt set name to validate

        Returns:
            The validated prompt set name (may warn but doesn't fail)
        """
        # Check if set directory exists
        set_dir = os.path.join(self.prompts_dir, prompt_set)

        # New structure: prompts/<set>/
        if os.path.isdir(set_dir):
            # Verify it has review-core.md
            if os.path.isfile(os.path.join(set_dir, 'review-core.md')):
                return prompt_set
            else:
                print(f"Warning: Prompt set directory '{set_dir}' exists but missing review-core.md")

        # If metadata defines this set, trust it even if directory doesn't exist yet
        if self.metadata and prompt_set in self.metadata.get('sets', {}):
            return prompt_set

        # Return anyway - validation will happen in PromptLoader._resolve_prompt_set_dir()
        return prompt_set

    def list_available_sets(self) -> Dict[str, Dict]:
        """
        Get information about available prompt sets.

        Returns:
            Dictionary mapping set names to their metadata
        """
        available = {}

        # From metadata file
        if self.metadata:
            available.update(self.metadata.get('sets', {}))

        # Scan for additional sets in filesystem
        if os.path.isdir(self.prompts_dir):
            for entry in os.listdir(self.prompts_dir):
                set_dir = os.path.join(self.prompts_dir, entry)
                if os.path.isdir(set_dir):
                    # Check if it looks like a prompt set
                    if os.path.isfile(os.path.join(set_dir, 'review-core.md')):
                        if entry not in available:
                            # Add discovered set with minimal metadata
                            available[entry] = {
                                'name': entry.capitalize(),
                                'description': f"Custom prompt set (filesystem)",
                                'estimated_tokens': 'Unknown'
                            }

        return available

    def get_model_mappings(self) -> Dict[str, str]:
        """
        Get configured model→set mappings.

        Returns:
            Dictionary mapping model names to prompt sets
        """
        if self.metadata:
            return self.metadata.get('model_mappings', {})
        return {}
