#!/usr/bin/env python3
"""Tests for --refresh-fix-status (analysis/fix_refresh.py)."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis.fix_checker import FixChecker
from analysis.fix_refresh import refresh_review_dir, patch_inline_text, STATE_FILE
from test_fix_checker import FakeLLM, commit_file, git, make_repo


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.up = make_repo(os.path.join(root, 'up'))
        self.down = make_repo(os.path.join(root, 'down'))
        self.up_bug = commit_file(self.up, 'a.c', 'bug\n', 'upstream: add feature')
        self.bug = commit_file(self.down, 'a.c', 'bug\n', 'downstream backport')
        self.set_origin(self.down, 'SL-1')
        self.set_origin(self.up, 'master')
        self.dir = os.path.join(root, 'out', self.bug[:2], self.bug)
        os.makedirs(self.dir)
        findings = [{'type': 'x', 'severity': 'high', 'confidence': 0.9,
                     'message': 'm', 'evidence': 'e'}]
        self.write('review-inline.json', {'commit': self.bug, 'upstream-commit': self.up_bug,
                                          'findings': findings})
        self.write('review-pre-verification.json', {'sha': self.bug, 'subject': 's',
                                                    'diff': '+bug', 'files': ['a.c']})
        self.write('review-metadata.json', {'sha': self.bug, 'issues-found': 1})
        with open(os.path.join(self.dir, 'review-inline.txt'), 'w') as f:
            f.write('commit x\n\n[Finding 1 — type: x, severity: high, confidence: 0.9]\nm\n')

    def tearDown(self):
        self.tmp.cleanup()

    def set_origin(self, repo, branch):
        git(repo, 'update-ref', f'refs/remotes/origin/{branch}', 'HEAD')

    def write(self, name, data):
        with open(os.path.join(self.dir, name), 'w') as f:
            json.dump(data, f)

    def read(self, name):
        with open(os.path.join(self.dir, name)) as f:
            return json.load(f)

    def refresh(self, llm, **kw):
        checker = FixChecker(self.down, 'SL-1', self.up, 'origin/master')
        return refresh_review_dir(self.dir, checker, llm, **kw)

    def test_fix_landing_later_is_picked_up(self):
        llm = FakeLLM('FIXES: {"1": []}')
        self.assertEqual(self.refresh(llm)['state'], 'unchanged')      # nothing new yet
        self.assertEqual(llm.calls, 0)
        self.assertEqual(self.refresh(llm)['reason'], 'branch tips did not move')

        fix = commit_file(self.down, 'a.c', 'fixed\n', f'fix\n\nFixes: {self.bug[:12]}')
        self.set_origin(self.down, 'SL-1')
        llm = FakeLLM(f'FIXES: {{"1": ["{fix[:12]}"]}}')
        res = self.refresh(llm)
        self.assertEqual((res['state'], res['newly_fixed']), ('updated', 1))
        f = self.read('review-inline.json')['findings'][0]
        self.assertEqual(f['fix-status'], 'fixed')
        self.assertEqual(self.read('review-inline.json')['issues-fixed'], 1)
        meta = self.read('review-metadata.json')
        self.assertEqual((meta['issues-fixed'], meta['future-fix']), (1, f'{fix[:12]} (origin/SL-1)'))
        with open(os.path.join(self.dir, 'review-inline.txt')) as fh:
            self.assertIn('fix-status: fixed', fh.read())

        # fixed findings are final: no further LLM calls
        llm = FakeLLM('')
        self.assertEqual(self.refresh(llm)['state'], 'skipped')
        self.assertEqual(llm.calls, 0)

    def test_only_new_commits_are_candidates(self):
        old = commit_file(self.down, 'a.c', 'other\n', 'earlier unrelated change')
        self.set_origin(self.down, 'SL-1')
        llm = FakeLLM('FIXES: {"1": []}')
        self.refresh(llm)                       # sees `old`, rejects it
        self.assertEqual(llm.calls, 1)
        commit_file(self.down, 'b.c', 'x\n', 'unrelated file')
        self.set_origin(self.down, 'SL-1')
        self.refresh(llm)                       # moved tip, but no candidate touches a.c
        self.assertEqual(llm.calls, 1)
        self.assertEqual(self.read('review-inline.json')['findings'][0].get('fix-status'), None)
        self.assertEqual(self.read(STATE_FILE)['downstream-head'],
                         git(self.down, 'rev-parse', 'origin/SL-1'))

    def test_llm_failure_keeps_marker_for_retry(self):
        fix = commit_file(self.down, 'a.c', 'fixed\n', f'fix\n\nFixes: {self.bug[:12]}')
        self.set_origin(self.down, 'SL-1')
        self.assertEqual(self.refresh(FakeLLM('garbage'))['state'], 'error')
        self.assertFalse(os.path.exists(os.path.join(self.dir, STATE_FILE)))
        res = self.refresh(FakeLLM(f'FIXES: {{"1": ["{fix[:12]}"]}}'))
        self.assertEqual(res['newly_fixed'], 1)

    def test_fixed_upstream_promoted_by_backport_and_never_downgraded(self):
        fix = commit_file(self.up, 'a.c', 'fixed\n', f'upstream fix\n\nFixes: {self.up_bug[:12]}')
        self.set_origin(self.up, 'master')
        llm = FakeLLM(f'FIXES: {{"1": ["{fix[:12]}"]}}')
        self.refresh(llm)
        self.assertEqual(self.read('review-inline.json')['findings'][0]['fix-status'], 'fixed-upstream')

        commit_file(self.down, 'a.c', 'fixed\n', f'backport\n\nGit-commit: {fix}')
        self.set_origin(self.down, 'SL-1')
        self.refresh(llm)
        self.assertEqual(self.read('review-inline.json')['findings'][0]['fix-status'], 'fixed')

    def test_fixed_upstream_not_downgraded_when_llm_says_no(self):
        fix = commit_file(self.up, 'a.c', 'fixed\n', f'upstream fix\n\nFixes: {self.up_bug[:12]}')
        self.set_origin(self.up, 'master')
        self.refresh(FakeLLM(f'FIXES: {{"1": ["{fix[:12]}"]}}'))
        commit_file(self.down, 'a.c', 'unrelated\n', 'unrelated change')
        self.set_origin(self.down, 'SL-1')
        self.refresh(FakeLLM('FIXES: {"1": []}'))
        f = self.read('review-inline.json')['findings'][0]
        self.assertEqual(f['fix-status'], 'fixed-upstream')
        self.assertEqual(f['future-fix'], f'{fix[:12]} (upstream)')

    def test_review_without_pre_verification_uses_git(self):
        os.unlink(os.path.join(self.dir, 'review-pre-verification.json'))
        fix = commit_file(self.down, 'a.c', 'fixed\n', f'fix\n\nFixes: {self.bug[:12]}')
        self.set_origin(self.down, 'SL-1')
        from git_integration import Commit
        get = lambda sha: Commit(sha=sha, author='a', date='', subject='s', message='s',
                                 diff='+bug', files=['a.c'])
        res = self.refresh(FakeLLM(f'FIXES: {{"1": ["{fix[:12]}"]}}'), get_commit=get)
        self.assertEqual(res['newly_fixed'], 1)

    def test_patch_inline_text(self):
        text = '[Finding 1 — type: x, fix-status: fixed, future-fix: a (b), c]\nmsg\n'
        out = patch_inline_text(text, [{'type': 'x', 'fix-status': 'fixed-upstream',
                                        'future-fix': 'd (upstream)'}])
        self.assertIn('[Finding 1 — type: x, fix-status: fixed-upstream, future-fix: d (upstream)]', out)
        out = patch_inline_text(text, [{'fix-status': 'not-fixed'}])
        self.assertIn('[Finding 1 — type: x]', out)


if __name__ == '__main__':
    unittest.main()
