# Backport Verification Guide

## CRITICAL: Wrong-Function Detection (Check This First)

The most dangerous backport error is applying a fix to the **wrong function**.

### Mandatory First Step: Compare Hunk Header Function Names

Every unified diff hunk header contains the enclosing function name:
```
@@ -150,7 +150,8 @@ static void process_request(struct request *req)
                                    ^^^^^^^^^^^^^^^ — this is the function
```

**Check: do the `@@ ... @@ func_name` texts match between upstream and downstream?**

- If function names **differ**: treat as a CRITICAL RED FLAG.
  - Confirm it is not a simple rename (same body, new name).
  - Verify both functions have the same callers, locking context, and execution
    context (interrupt vs. process, atomic vs. sleepable).
  - If in any doubt: report as `backport-error: patch applied to wrong function`.

- If function names **match** but context-match score is very low (< 50%):
  - Verify the function still serves the same purpose (may have been split/merged).

## Verify Backports When Differences Detected

When the backport analysis shows differences (context mismatches, line shifts,
missing/extra hunks), verify:

1. **(MANDATORY)** Compare function names from hunk headers — if different, investigate.
2. Is the downstream patch in a functionally equivalent code location?
3. Are all critical parts of the upstream patch present?
4. Do the logic and semantics match upstream intent?
5. Is there any missing error handling or cleanup?
6. Do both locations have the same locking requirements and execution context?

## Red Flags

**🚩 CRITICAL: Different function name in hunk header**
```
Upstream:   @@ -150,7 +155,8 @@ static void process_request(...)
Downstream: @@ -143,7 +143,8 @@ static void handle_request(...)
```

**🚩 Wrong function content**
```
Upstream: Patches handle_request()
Downstream: Patches process_request()  // Different function!
```

**🚩 Opposite logic** — upstream changes `if (foo)` to `if (!foo)`, downstream keeps `if (foo)`

**🚩 Critical code missing** — upstream adds both error check AND cleanup; downstream adds only check

**🚩 Wrong struct field** — upstream sets `req->cmd_flags`; downstream sets `req->flags`

## Reporting

```
backport-error: Incorrect backport - patch applied to wrong function
backport-error: Incorrect backport - missing critical cleanup code
backport-error: Incorrect backport - logic inverted compared to upstream
```

**If in doubt, report it.** Better to flag a possibly-correct backport than to miss
an incorrect one that introduces a regression.
