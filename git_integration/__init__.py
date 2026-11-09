"""Git integration module for kernel review agent."""

from .commit_extractor import CommitExtractor, Commit, MultiRepoExtractor
from .source_utils import git_ref_for_commit, extract_function

__all__ = ['CommitExtractor', 'Commit', 'MultiRepoExtractor',
           'git_ref_for_commit', 'extract_function']
