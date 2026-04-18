"""Git integration module for kernel review agent."""

from .commit_extractor import CommitExtractor, Commit, MultiRepoExtractor

__all__ = ['CommitExtractor', 'Commit', 'MultiRepoExtractor']
