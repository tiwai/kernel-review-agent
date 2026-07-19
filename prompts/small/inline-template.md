Produce a report of regressions found based on this template.

- Plain text only. No markdown, no special characters. Wrap added text at 78
  characters. Preserve long lines from the unified diff as-is.
- Never include false positives.
- End the report with a blank line.
- Conversational, undramatic, factual. Frame issues as questions, not
  accusations. Call issues "regressions", never "critical".
- NEVER USE ALL CAPS except when directly quoting code.
- Do not mention the author. Say "Can this corrupt memory?" not "Did you
  corrupt memory here?"
- Vary question phrasing. Do not start every question with "Does this code..."
- SR-* pattern issues are subjective. Do not add a SUBJECTIVE header; simply
  say "this isn't a bug, but ..."
- Name the specific resource in leak questions: "Does this code leak the
  folio?" not "Is there a resource leak?"
- When the issue is in the commit message, quote the exact incorrect portion.
  No need to include diff hunks if the only issue is in the commit message.
- Include additional details (later fixes, lore links) in the summary,
  reworded to fit the template.
- Include every issue sent, even if already fixed upstream.
- No extra explanatory content about why something matters. State the issue
  and suggestion only. Do not explain why typos are a problem.

## Clear, concise paragraphs

Never write long dense paragraphs. Ask short questions backed by code
snippets or call chains. Break up factual sentences into logical groups with
a blank line between each. Put a blank line before the closing question.

### AVOID
```
Can this sequence actually occur?  Looking at bt_accept_dequeue() in
af_bluetooth.c, if CPU1 already called bt_accept_unlink() which sets
bt_sk(sk)->parent = NULL, wouldn't CPU2 check parent at line 284,
detect it is NULL, and take the 'already unlinked' path with
release_sock/sock_put/goto restart instead of calling bt_accept_unlink()
again?
```

### USE INSTEAD
```
Can this sequence actually occur?  Looking at bt_accept_dequeue() in
af_bluetooth.c, if CPU1 already called bt_accept_unlink() and set
bt_sk(sk)->parent = NULL:

CPU1
bt_accept_unlink()
   bt_sk(sk)->parent = NULL;

CPU2 would see this in bt_accept_dequeue():
    if (!bt_sk(sk)->parent) {
        release_sock(sk);
        sock_put(sk);
        goto restart;
    }

and take the goto restart path instead of calling bt_accept_unlink() again?
```

## Never quote line numbers

Use function names and call chains (funcA()->funcB()) instead of line
numbers. The audience does not know your exact codebase. Use small code
snippets any time you feel the urge to reference a line number.

### AVOID
```
it can happen if the LRU cache evicts the entry (see line 2327 in
__get_cur_name_and_parent)
```

### USE INSTEAD
```
it can happen if the LRU cache evicts the entry:

fs/btrfs/send.c:__get_cur_name_and_parent() {
    ...
    nce = name_cache_search(sctx, ino, gen);
    if (nce) {
        if (ino < sctx->send_progress && nce->need_later_update) {
            btrfs_lru_cache_remove(&sctx->name_cache, &nce->entry);
    ...
}
```

## Structure

The report must include:

- git sha of the commit
- Author: line from the commit
- One-line subject from the commit
- Brief summary of the commit (max 3 sentences)
- Any Link: tags from the commit header
- Unified diff quoted as an email reply ("> " prefix on each line)
  - Regenerate the diff from the commit diff provided; do not generate from
    context. Ensure quoted portions exactly match the original.
- Place questions alongside the relevant code in the diff, without "> " on
  your added text. Place questions as close as possible to the buggy code.
- Aggressively snip unrelated content:
  - Replace snipped content with [ ... ]
  - Drop diff headers for entirely snipped files
  - Snip entire files, hunks, and functions unrelated to review comments
  - Snip trailing hunks and files after your last review comment unless
    needed for context
  - Keep only enough quoted material for the review to make sense

Sample:

```
commit 06e4fcc91a224c6b7119e87fc1ecc7c533af5aed
Author: Kairui Song <kasong@tencent.com>

mm, swap: only scan one cluster in fragment list

<brief description>

> diff --git a/mm/swapfile.c b/mm/swapfile.c
> index b4f3cc7125804..1f1110e37f68b 100644
> --- a/mm/swapfile.c
> +++ b/mm/swapfile.c

[ ... ]

> @@ -926,32 +926,25 @@ static unsigned long cluster_alloc_swap_entry(...)
> -		frags_existing = atomic_long_read(&si->frag_cluster_nr[order]);
> -		while (frags < frags_existing &&
> -		       (ci = isolate_lock_cluster(si, &si->frag_clusters[order]))) {
> -			atomic_long_dec(&si->frag_cluster_nr[order]);
                        ^^^^

Is it ok to remove this atomic_long_dec()?  It looks like the counter
updates are getting lost.

> +		 * allocation will surely success, and large allocation
                 ^^^^^^^^ this isn't a bug, but you've duplicated this line
```

Sample commit message issue:

```
commit 535a36aad18ce99e3270486fdb073bb5eb1f1c59
Author: SeongJae Park <sj@kernel.org>

Docs/mm/damon/maintainer-profile: fix wrong MAITNAINERS section name

This commit fixes the documentation to reference the correct MAINTAINERS
section name after commit 9044cbe50a70 renamed the DAMON section from
"DATA ACCESS MONITOR" to "DAMON".

Link: https://lkml.kernel.org/r/20260118180305.70023-8-sj@kernel.org

> Docs/mm/damon/maintainer-profile: fix wrong MAITNAINERS section name

This isn't a bug, but there's a typo (MAITNAINERS) in the subject line.
```
