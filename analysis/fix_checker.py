"""Check whether confirmed findings were already fixed by a later commit.

Looks at the commits after the reviewed one on origin/<target> of the
reviewed repository, and at the corresponding upstream commits, then lets
the LLM decide which candidates really fix each finding.

Per finding this sets two keys (same names and values as the
re-verify-kreview command, see docs/schema/):

  fix-status: 'fixed' (a later commit already in origin/<target>),
              'fixed-upstream' (fix exists upstream only) or 'not-fixed'
  future-fix: fixing commits with their location, or None
"""

import json
import re
import subprocess
from typing import Dict, List, Optional, Tuple

from git_integration import git_ref_for_commit
from output.fix_info import FIX_STATUS_KEY, FUTURE_FIX_KEY, summarize_future_fixes  # noqa: F401
import config

MAX_CANDIDATES = 12          # per side (downstream / upstream)
MAX_DIFF_CHARS = 3000        # diff excerpt per candidate in the prompt
GIT_TIMEOUT = 120

_FIXES_RE = re.compile(r'FIXES:\s*(\{.*?\})\s*$', re.DOTALL | re.MULTILINE)


def normalize_branch(target: Optional[str]) -> Optional[str]:
    """Return 'origin/<target>' for a branch name (a leading origin/ is kept once)."""
    if not target:
        return None
    target = target.strip()
    if target.startswith('refs/remotes/'):
        target = target[len('refs/remotes/'):]
    if not target.startswith('origin/'):
        target = 'origin/' + target
    return target


def apply_default_fix_status(findings: List[Dict]) -> None:
    """Mark findings without a result as not-fixed (used when the check is skipped)."""
    for f in findings:
        f.setdefault(FIX_STATUS_KEY, 'not-fixed')
        f.setdefault(FUTURE_FIX_KEY, None)


class FixChecker:
    """Find later fixes of review findings on the target branch and upstream."""

    def __init__(
        self,
        downstream_dir: str = '.',
        target_branch: Optional[str] = None,
        upstream_dir: Optional[str] = None,
        upstream_ref: str = 'origin/master',
        verbose: bool = False,
        debug: bool = False,
    ):
        self.downstream_dir = downstream_dir or '.'
        self.branch = normalize_branch(target_branch)
        self.upstream_dir = upstream_dir
        self.upstream_ref = upstream_ref
        self.verbose = verbose
        self.debug = debug

    # ------------------------------------------------------------------ git

    def _git(self, repo: str, args: List[str]) -> Optional[str]:
        """Run git in repo; None on failure.  Callers keep every walk range-bounded."""
        try:
            r = subprocess.run(
                ['git', '-C', repo] + args,
                capture_output=True, text=True, timeout=GIT_TIMEOUT
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            if self.debug:
                print(f"      [FIXCHECK] git {' '.join(args[:3])} failed: {e}")
            return None
        if r.returncode != 0:
            if self.debug:
                print(f"      [FIXCHECK] git {' '.join(args[:3])}: {r.stderr.strip()}")
            return None
        return r.stdout

    def _ref_exists(self, repo: str, ref: str) -> bool:
        return self._git(repo, ['rev-parse', '--verify', '--quiet', ref + '^{commit}']) is not None

    def _is_ancestor(self, repo: str, sha: str, ref: str) -> bool:
        return self._git(repo, ['merge-base', '--is-ancestor', sha, ref]) is not None

    def _log(self, repo: str, rng: str, grep: Optional[str], files: List[str]) -> List[Tuple[str, str]]:
        """Return [(sha, subject)] of commits in the range, filtered by --grep or paths."""
        args = ['log', '--no-merges', '-n', str(MAX_CANDIDATES), '--format=%H %s', rng]
        if grep:
            args[1:1] = ['-E', '--grep=' + grep]
        if files:
            args += ['--'] + files
        elif not grep:
            return []
        out = self._git(repo, args)
        if not out:
            return []
        result = []
        for line in out.splitlines():
            sha, _, subject = line.partition(' ')
            if sha:
                result.append((sha, subject))
        return result

    def _diff_excerpt(self, repo: str, sha: str, files: List[str]) -> str:
        args = ['show', '--format=%s%n%n%b', '-p', sha]
        if files:
            args += ['--'] + files
        out = self._git(repo, args) or ''
        return out[:MAX_DIFF_CHARS]

    # ----------------------------------------------------------- candidates

    def _downstream_candidates(self, commit, upstream_sha: Optional[str]) -> List[Dict]:
        """Later commits on origin/<target> that mention the commit or touch its files."""
        if not self.branch or not self._ref_exists(self.downstream_dir, self.branch):
            return []
        if not self._is_ancestor(self.downstream_dir, commit.sha, self.branch):
            if self.verbose:
                print(f"      [FIXCHECK] {commit.sha[:12]} is not in {self.branch}; "
                      "skipping the downstream check")
            return []
        rng = f"{commit.sha}..{self.branch}"
        files = list(commit.files or [])
        ids = [commit.sha[:12]]
        if upstream_sha:
            ids.append(upstream_sha[:12])
        found: Dict[str, str] = {}
        for sha, subject in self._log(self.downstream_dir, rng, f"Fixes: ({'|'.join(ids)})", []):
            found[sha] = subject
        for sha, subject in self._log(self.downstream_dir, rng, None, files):
            found.setdefault(sha, subject)
        return [
            {'sha': sha, 'subject': subject, 'where': self.branch,
             'diff': self._diff_excerpt(self.downstream_dir, sha, files)}
            for sha, subject in list(found.items())[:MAX_CANDIDATES]
        ]

    def _upstream_candidates(self, commit, upstream_sha: Optional[str]) -> List[Dict]:
        """Later upstream commits with a Fixes: tag for the upstream commit, or touching its files."""
        if not upstream_sha or not self.upstream_dir:
            return []
        ref = self.upstream_ref
        if not self._ref_exists(self.upstream_dir, ref):
            for alt in ('master', 'HEAD'):
                if self._ref_exists(self.upstream_dir, alt):
                    ref = alt
                    break
            else:
                return []
        if not self._is_ancestor(self.upstream_dir, upstream_sha, ref):
            return []
        rng = f"{upstream_sha}..{ref}"
        files = list(commit.files or [])
        found: Dict[str, str] = {}
        for sha, subject in self._log(self.upstream_dir, rng, f"Fixes: {upstream_sha[:12]}", []):
            found[sha] = subject
        # Path-scoped commits are only useful as leads when no Fixes: tag matched
        if not found:
            for sha, subject in self._log(self.upstream_dir, rng, None, files):
                found.setdefault(sha, subject)
        result = []
        for sha, subject in list(found.items())[:MAX_CANDIDATES]:
            result.append({
                'sha': sha, 'subject': subject, 'where': 'upstream',
                'diff': self._diff_excerpt(self.upstream_dir, sha, files),
                'in_branch': self._backported_to_branch(sha, upstream_sha, commit.sha),
            })
        return result

    def _backported_to_branch(self, upstream_fix: str, upstream_sha: str, base_sha: str) -> bool:
        """True if the upstream fix shows up (by its ID) on origin/<target> after the commit."""
        if not self.branch or not self._ref_exists(self.downstream_dir, self.branch):
            return False
        if not self._is_ancestor(self.downstream_dir, base_sha, self.branch):
            return False
        out = self._git(self.downstream_dir, [
            'log', '--no-merges', '-n', '1', '--format=%H',
            f"{base_sha}..{self.branch}", '--grep', upstream_fix[:12],
        ])
        return bool(out and out.strip())

    # ----------------------------------------------------------------- LLM

    def check(self, llm, commit, findings: List[Dict], upstream_sha: Optional[str],
              max_iterations: Optional[int] = None) -> None:
        """Annotate findings in place with fix-status and future-fix."""
        if not findings:
            return
        apply_default_fix_status(findings)

        down = self._downstream_candidates(commit, upstream_sha)
        up = self._upstream_candidates(commit, upstream_sha)
        if self.verbose:
            print(f"      [FIXCHECK] candidates: {len(down)} on {self.branch or 'n/a'}, "
                  f"{len(up)} upstream")
        if not down and not up:
            return

        cands = {c['sha']: c for c in down + up}
        verdict = self._ask_llm(llm, commit, findings, down, up, max_iterations)
        if verdict is None:
            return

        for idx, f in enumerate(findings, 1):
            shas = verdict.get(str(idx)) or []
            fixes_down: List[str] = []
            fixes_up: List[str] = []
            for sha12 in shas:
                full = next((s for s in cands if s.startswith(str(sha12))), None)
                if not full:
                    continue
                c = cands[full]
                if c['where'] == 'upstream':
                    if c.get('in_branch'):
                        fixes_down.append(f"{full[:12]} ({self.branch}, backport of upstream fix)")
                    else:
                        fixes_up.append(f"{full[:12]} (upstream)")
                else:
                    fixes_down.append(f"{full[:12]} ({c['where']})")
            if fixes_down:
                f[FIX_STATUS_KEY] = 'fixed'
            elif fixes_up:
                f[FIX_STATUS_KEY] = 'fixed-upstream'
            else:
                continue
            f[FUTURE_FIX_KEY] = '; '.join(fixes_down + fixes_up)

    def _ask_llm(self, llm, commit, findings, down, up, max_iterations) -> Optional[Dict]:
        system_prompt = (
            "You're a Linux kernel expert.  A downstream commit was reviewed and "
            "the findings below were confirmed as real issues.  Decide for each "
            "finding whether one of the listed LATER commits already fixes it "
            "(or removes/reverts the flawed code).  Only commits listed as candidates "
            "can be named.  A candidate that merely touches the same file does not "
            "count; the diff must address the reported flaw.  Use the git tools to read "
            "code if needed, but stay within the given candidates.\n\n"
            "Finish with one line in exactly this format:\n"
            "FIXES: {\"1\": [\"<sha12>\", ...], \"2\": []}\n"
            "mapping each finding number to the fixing candidate IDs "
            "(empty list if none)."
        )

        def fmt(cands: List[Dict], title: str) -> str:
            if not cands:
                return ''
            lines = [title]
            for c in cands:
                lines.append(f"--- candidate {c['sha'][:12]} ({c['where']}): {c['subject']}\n{c['diff']}")
            return '\n'.join(lines) + '\n\n'

        findings_txt = []
        for i, f in enumerate(findings, 1):
            evidence = f.get('evidence', '')
            if isinstance(evidence, list):
                evidence = '\n'.join(str(x) for x in evidence)
            findings_txt.append(
                f"Finding {i} [{f.get('type', 'unknown')}]: {f.get('message', '')}\n"
                f"  Evidence: {str(evidence)[:1500]}"
            )

        user_prompt = (
            f"Commit: {commit.sha}\nSubject: {commit.subject}\n\n"
            f"Diff:\n{commit.diff}\n\n"
            + fmt(down, f"Later commits on {self.branch}:")
            + fmt(up, "Later upstream commits:")
            + "Confirmed findings:\n\n" + "\n\n".join(findings_txt)
            + "\n\nOutput the FIXES line."
        )

        try:
            response = llm.analyze_with_tools(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_iterations=max_iterations or config.MAX_TOOL_ITERATIONS,
                commit_ref=git_ref_for_commit(commit.sha),
                max_tokens=config.VERIFY_MAX_TOKENS,
            )
            m = _FIXES_RE.search(response or '')
            if not m:
                if self.verbose or self.debug:
                    print("      [FIXCHECK] No FIXES line in response; leaving not-fixed")
                return None
            data = json.loads(m.group(1))
            return {str(k): [str(s) for s in v] for k, v in data.items() if isinstance(v, list)}
        except Exception as e:
            if self.verbose or self.debug:
                print(f"      [FIXCHECK] Error: {e}; leaving not-fixed")
            return None
