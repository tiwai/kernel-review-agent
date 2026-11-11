#!/usr/bin/env python3
"""Tests for the later-fix check and the fix-status/future-fix schemas."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.fix_checker import FixChecker, normalize_branch
from output.fix_info import summarize_future_fixes
from output.json_formatter import JSONReportFormatter

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs', 'schema')


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t',
               GIT_COMMITTER_EMAIL='t@t')
    return subprocess.run(['git', '-C', repo] + list(args), check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


def commit_file(repo, name, content, msg):
    with open(os.path.join(repo, name), 'w') as f:
        f.write(content)
    git(repo, 'add', name)
    git(repo, 'commit', '-q', '-m', msg)
    return git(repo, 'rev-parse', 'HEAD')


def make_repo(path):
    os.makedirs(path)
    git(path, 'init', '-q', '-b', 'master')
    return path


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def analyze_with_tools(self, **kwargs):
        self.calls += 1
        return self.response


class FixCheckerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.up = make_repo(os.path.join(root, 'up'))
        self.down = make_repo(os.path.join(root, 'down'))
        self.up_bug = commit_file(self.up, 'a.c', 'bug\n', 'upstream: add feature')
        self.down_bug = commit_file(self.down, 'a.c', 'bug\n', 'downstream backport')
        self.commit = SimpleNamespace(sha=self.down_bug, subject='s', diff='+bug', files=['a.c'],
                                      upstream_commit=self.up_bug, distro_commit=None)
        self.findings = [{'type': 'x', 'message': 'm', 'evidence': 'e'}]

    def tearDown(self):
        self.tmp.cleanup()

    def set_origin(self, repo, branch='master'):
        git(repo, 'update-ref', f'refs/remotes/origin/{branch}', 'HEAD')

    def checker(self, branch='SL-1'):
        return FixChecker(self.down, branch, self.up, 'origin/master')

    def test_normalize_branch(self):
        self.assertEqual(normalize_branch('SL-1'), 'origin/SL-1')
        self.assertEqual(normalize_branch('origin/SL-1'), 'origin/SL-1')
        self.assertIsNone(normalize_branch(None))

    def test_fixed_on_target_branch(self):
        fix = commit_file(self.down, 'a.c', 'fixed\n', f'fix it\n\nFixes: {self.down_bug[:12]}')
        self.set_origin(self.down, 'SL-1')
        self.set_origin(self.up)
        llm = FakeLLM(f'FIXES: {{"1": ["{fix[:12]}"]}}')
        self.checker().check(llm, self.commit, self.findings, self.up_bug)
        self.assertEqual(self.findings[0]['fix-status'], 'fixed')
        self.assertEqual(self.findings[0]['future-fix'], f'{fix[:12]} (origin/SL-1)')

    def test_fixed_upstream_only(self):
        fix = commit_file(self.up, 'a.c', 'fixed\n', f'upstream fix\n\nFixes: {self.up_bug[:12]}')
        self.set_origin(self.up)
        self.set_origin(self.down, 'SL-1')
        llm = FakeLLM(f'FIXES: {{"1": ["{fix[:12]}"]}}')
        self.checker().check(llm, self.commit, self.findings, self.up_bug)
        self.assertEqual(self.findings[0]['fix-status'], 'fixed-upstream')
        self.assertEqual(self.findings[0]['future-fix'], f'{fix[:12]} (upstream)')

    def test_upstream_fix_backported_counts_as_fixed(self):
        fix = commit_file(self.up, 'a.c', 'fixed\n', f'upstream fix\n\nFixes: {self.up_bug[:12]}')
        self.set_origin(self.up)
        commit_file(self.down, 'a.c', 'fixed\n', f'backport\n\nGit-commit: {fix}')
        self.set_origin(self.down, 'SL-1')
        llm = FakeLLM(f'FIXES: {{"1": ["{fix[:12]}"]}}')
        self.checker().check(llm, self.commit, self.findings, self.up_bug)
        self.assertEqual(self.findings[0]['fix-status'], 'fixed')
        self.assertIn('origin/SL-1', self.findings[0]['future-fix'])

    def test_not_fixed_when_llm_rejects_candidates(self):
        commit_file(self.down, 'a.c', 'other change\n', 'unrelated change to the file')
        self.set_origin(self.down, 'SL-1')
        llm = FakeLLM('FIXES: {"1": []}')
        self.checker().check(llm, self.commit, self.findings, None)
        self.assertEqual(llm.calls, 1)
        self.assertEqual(self.findings[0]['fix-status'], 'not-fixed')
        self.assertIsNone(self.findings[0]['future-fix'])

    def test_no_candidates_skips_llm(self):
        self.set_origin(self.down, 'SL-1')
        self.set_origin(self.up)
        llm = FakeLLM('')
        self.checker().check(llm, self.commit, self.findings, self.up_bug)
        self.assertEqual(llm.calls, 0)
        self.assertEqual(self.findings[0]['fix-status'], 'not-fixed')

    def test_missing_branch_checks_upstream_only(self):
        fix = commit_file(self.up, 'a.c', 'fixed\n', f'upstream fix\n\nFixes: {self.up_bug[:12]}')
        self.set_origin(self.up)
        llm = FakeLLM(f'FIXES: {{"1": ["{fix[:12]}"]}}')
        self.checker(branch=None).check(llm, self.commit, self.findings, self.up_bug)
        self.assertEqual(self.findings[0]['fix-status'], 'fixed-upstream')

    def test_garbled_llm_answer_leaves_not_fixed(self):
        commit_file(self.down, 'a.c', 'x\n', 'touch')
        self.set_origin(self.down, 'SL-1')
        self.checker().check(FakeLLM('no idea'), self.commit, self.findings, None)
        self.assertEqual(self.findings[0]['fix-status'], 'not-fixed')

    def test_summary_and_report_keys(self):
        findings = [
            {'message': 'a', 'fix-status': 'fixed', 'future-fix': 'aaa (origin/SL-1)'},
            {'message': 'b', 'fix-status': 'fixed-upstream', 'future-fix': 'bbb (upstream); aaa (origin/SL-1)'},
            {'message': 'c', 'fix-status': 'not-fixed', 'future-fix': None},
        ]
        self.assertEqual(summarize_future_fixes(findings), 'aaa (origin/SL-1); bbb (upstream)')
        commit = SimpleNamespace(sha='a' * 40, author='A', subject='S', distro_commit=None,
                                 upstream_commit=None)
        report = JSONReportFormatter().format_report(commit, findings)
        self.assertEqual(report['issues-fixed'], 1)
        self.assertEqual(report['future-fix'], 'aaa (origin/SL-1); bbb (upstream)')
        self.assertEqual(report['findings'][0]['fix-status'], 'fixed')


class SchemaTest(unittest.TestCase):
    def setUp(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest('jsonschema not installed')
        self.jsonschema = jsonschema

    def load(self, name):
        with open(os.path.join(DOCS, name)) as f:
            return json.load(f)

    def example(self):
        return {
            "schema-version": 2,
            "commit": "d984f559d501f6be918baac0fcd548e0c6df1d49",
            "model": "mglimmer",
            "branch": "origin/SL-16.0",
            "verified-by": "claude-opus-5-5",
            "verified-date": "2026-10-13",
            "verdict": "unsafe",
            "summary": "1 of 2 findings confirmed.",
            "original-findings": 2, "issues-found": 1, "issues-pruned": 1, "issues-fixed": 0,
            "future-fix": "595ca21f797e (upstream)",
            "findings": [
                {"category": "CHANGE-2", "type": "uninitialized-variable", "severity": "high",
                 "confidence": 0.9, "message": "m", "evidence": "e",
                 "upstream-status": "present-in-upstream", "status": "confirmed",
                 "reason": "r", "fix-status": "fixed-upstream", "future-fix": "595ca21f797e (upstream)"},
                {"category": "CHANGE-1", "type": "resource-leak", "severity": "medium",
                 "confidence": 0.5, "message": "m", "evidence": "e",
                 "upstream-status": "unknown", "status": "pruned", "reason": "r",
                 "fix-status": None, "future-fix": None},
            ],
        }

    def test_verified_result_example_valid(self):
        schema = self.load('verified-result.schema.json')
        self.jsonschema.validate(self.example(), schema)

    def test_verified_result_rejects_bad_values(self):
        schema = self.load('verified-result.schema.json')
        bad = self.example()
        bad['findings'][0]['fix-status'] = 'maybe'
        with self.assertRaises(self.jsonschema.ValidationError):
            self.jsonschema.validate(bad, schema)
        bad = self.example()
        bad['findings'][1]['fix-status'] = 'fixed'      # pruned must be null
        with self.assertRaises(self.jsonschema.ValidationError):
            self.jsonschema.validate(bad, schema)
        bad = self.example()
        bad['findings'][0]['aliased_key'] = 1
        with self.assertRaises(self.jsonschema.ValidationError):
            self.jsonschema.validate(bad, schema)

    def test_review_inline_report_valid(self):
        schema = self.load('review-inline.schema.json')
        commit = SimpleNamespace(sha='a' * 40, author='A', subject='S', distro_commit=None,
                                 upstream_commit=None)
        findings = [{'category': 'CHANGE-1', 'type': 'x', 'severity': 'high', 'confidence': 0.8,
                     'message': 'm', 'evidence': 'e', 'upstream_status': 'downstream_only',
                     'fix-status': 'fixed', 'future-fix': 'aaa (origin/SL-1)'}]
        report = JSONReportFormatter().format_report(commit, findings)
        self.jsonschema.validate(report, schema)


if __name__ == '__main__':
    unittest.main()
