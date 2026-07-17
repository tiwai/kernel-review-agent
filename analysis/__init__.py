"""Analysis module for kernel review agent."""

from .workflow import ReviewWorkflow
from .upstream_verifier import UpstreamVerifier, SuseUpstreamVerifier
from .hybrid_workflow import HybridReviewWorkflow
from .tool_workflow import ToolCallReviewWorkflow

__all__ = [
    'ReviewWorkflow',
    'UpstreamVerifier',
    'SuseUpstreamVerifier',  # backward-compat alias
    'HybridReviewWorkflow',
    'ToolCallReviewWorkflow'
]
