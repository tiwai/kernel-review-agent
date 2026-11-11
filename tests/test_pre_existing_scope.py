"""Tests for pre-existing-issue detection (diff scope hint, upstream Strategy 0)."""
import sys
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from analysis.workflow import ReviewWorkflow
from analysis.upstream_verifier import UpstreamVerifier

DIFF = """diff --git a/a.c b/a.c
--- a/a.c
+++ b/a.c
@@ -10,3 +10,4 @@ static void commit_release(struct nft_trans *trans)
-\t\tnft_set_elem_destroy(set, elem);
+\t\t__nft_set_elem_destroy(&trans->ctx, set, elem);
+\t\tnft_trans_release_done(trans);
"""


def _workflow():
    wf = ReviewWorkflow.__new__(ReviewWorkflow)
    return wf


def test_outside_diff():
    f = {'evidence': 'Line 4182: nft_set_elem_destroy(nft_trans_elem_set(trans), x) - still old'}
    assert _workflow()._classify_finding_scope(f, SimpleNamespace(diff=DIFF)) == 'outside-diff'


def test_in_diff():
    f = {'evidence': ['+\t\t__nft_set_elem_destroy(&trans->ctx, set, elem);']}
    assert _workflow()._classify_finding_scope(f, SimpleNamespace(diff=DIFF)) == 'in-diff'


def test_unknown_without_evidence():
    assert _workflow()._classify_finding_scope({}, SimpleNamespace(diff=DIFF)) == 'unknown'


def test_strategy0_ignores_context_evidence():
    uv = UpstreamVerifier.__new__(UpstreamVerifier)
    uv.debug = False
    uv.verbose = False
    uv.llm = None
    finding = {'evidence': 'nft_set_elem_destroy(nft_trans_elem_set(trans), elem);'}
    up = SimpleNamespace(diff=DIFF, files=['a.c'])
    down = SimpleNamespace(diff=DIFF, files=['a.c'])
    # Evidence is in neither diff; must not short-circuit to downstream-only (False)
    # via the "unmatched evidence" rule; identical diffs then count as upstream.
    assert uv._finding_exists_in_upstream(finding, up, down) is True
