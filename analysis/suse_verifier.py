"""Backward-compatible shim — use upstream_verifier instead."""
from .upstream_verifier import UpstreamVerifier as SuseUpstreamVerifier, UpstreamVerifier

__all__ = ['SuseUpstreamVerifier', 'UpstreamVerifier']
