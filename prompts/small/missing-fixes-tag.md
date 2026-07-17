# Missing Fixes: Tag Detection

If this commit appears to fix a bug, search git history with `git log` for the commit
being fixed.

If found, suggest a Fixes: tag:
```
Fixes: <first 12 chars of SHA> ("<commit subject>")
```

If identified: consider the missing tag a regression and add to review-inline.txt.

If not found and doing subjective review: report that the fixed commit has not been
identified and ask the author to search for it.

Output: `Fixes: tag missing (y/n) [Fixes: line if discovered]`
