# Backport Verification Guide

When reviewing downstream kernel commits that are backports from upstream, pay special attention to **backport quality**. The patches are applied to an older codebase, which can lead to subtle bugs if not done correctly.

## CRITICAL: Wrong-Function Detection (Check This First)

The single most dangerous backport error is applying a fix to the **wrong function**.
Backporters sometimes apply patches to a nearby function that looks syntactically
similar but has different semantics, callers, or execution context.

### Mandatory Function-Name Check

Whenever you see backport differences (context mismatches, line shifts, etc.),
**immediately compare the function names in the hunk headers** of both diffs.

Unified diff hunk headers contain the enclosing function name:
```
@@ -150,7 +150,8 @@ static void process_request(struct request *req)
                                    ^^^^^^^^^^^^^^^ — this is the function
```

**Step 1 — Extract function names from both diffs:**
- Upstream: what does `@@ ... @@ <function>` say?
- Downstream: what does `@@ ... @@ <function>` say?

**Step 2 — If the function names differ:**

This is a **CRITICAL RED FLAG**. You must:
1. Determine whether this is a rename (same body, different name) — acceptable.
2. Verify the two functions have equivalent callers, locking context, and execution
   context (interrupt vs. process, atomic vs. sleepable).
3. Confirm the fix achieves the same semantic goal in the downstream function.
4. **If in any doubt: report as a backport error.** Wrong-function application is
   far harder to spot than wrong-line application, so err on the side of reporting.

**Step 3 — Even when function names match:**

If the context-match score is very low (< 50%), verify that the function still
serves the same purpose. It may have been split into two functions or had its
role fundamentally changed by other patches.

### Wrong-Function Red Flags

**🚩 RED FLAG: Different function name in hunk header**
```
Upstream:   @@ -150,7 +155,8 @@ static void process_request(struct request *req)
Downstream: @@ -143,7 +143,8 @@ static void handle_request(struct request *req)
```
`process_request` and `handle_request` may look similar but serve different roles.
Requires explicit justification for why the different function is the right target.

**🚩 RED FLAG: Same function name, radically different context**
```
Both say: @@ ... @@ static void foo(...)
But upstream foo() holds a spinlock; downstream foo() does not.
```
The function may have been split, merged, or had its locking model reworked.
The backport may have landed in the "wrong half" of the split function.

**🚩 RED FLAG: Function exists in both but plays a different role**
```
Upstream: foo() is the primary IRQ handler
Downstream: foo() is a helper called from the primary handler
```
A fix to an IRQ handler does NOT automatically apply correctly to a helper.

## Critical Rule: Verify Backports When Differences Detected

If the backport analysis shows ANY differences between downstream and upstream patches:
- **Line number shifts**: Patch applied at different line numbers
- **Context mismatches**: Surrounding code doesn't match
- **File path changes**: Different files modified
- **Missing hunks**: Parts of upstream patch not applied downstream
- **Extra hunks**: Additional changes not in upstream

You MUST perform deep verification to ensure the backport is correct.

## Backport Verification Process

### 1. Understand the Upstream Intent

First, read the upstream commit message to understand:
- **What bug is being fixed?**
- **What behavior is being changed?**
- **Why was this change necessary?**

The upstream commit message is your ground truth for what the patch should accomplish.

### 2. Verify the Downstream Context

When line numbers or context differ, verify:

**✓ Correct location**: Is the downstream patch applied to code that serves the same purpose as the upstream location?

**Example - CORRECT backport with line shift**:
```
Upstream (v6.1):
  Line 150: static void process_request(struct request *req)
  Line 151: {
  Line 152:     if (!req)
  Line 153:         return;              // ← Upstream adds this check
  Line 154:     handle_request(req);

Downstream (v5.10):
  Line 145: static void process_request(struct request *req)
  Line 146: {
  Line 147:     if (!req)
  Line 148:         return;              // ← Same check added at line 147
  Line 149:     handle_request(req);
```
✓ **Valid**: Same function, same logic, just different line numbers due to code evolution.

**✗ WRONG backport - applied to wrong function**:
```
Upstream: Adds check in process_request()
Downstream: Adds check in handle_request()  // ← WRONG function!
```

### 3. Handle Context Mismatches

Context mismatches occur when surrounding code differs between upstream and downstream.

**Verification checklist**:
- [ ] Does the downstream function/code block serve the same purpose as upstream?
- [ ] Are the variable names different but represent the same data?
- [ ] Is the logic flow equivalent despite code structure differences?

**Example - CORRECT backport despite context mismatch**:
```
Upstream (v6.1):
  struct request *req = blk_mq_alloc_request(q, REQ_OP_READ);
  if (!req)
      return -ENOMEM;
  req->timeout = 5000;  // ← Adds timeout

Downstream (v5.10):
  struct request *req = blk_alloc_request(q);  // ← Different API!
  if (!req)
      return -ENOMEM;
  req->timeout = 5000;  // ← Same timeout added
```
✓ **Valid**: Different API in v5.10 (`blk_alloc_request` vs `blk_mq_alloc_request`), but the backport correctly adapts to the older API while achieving the same goal.

**Example - WRONG backport due to context change**:
```
Upstream (v6.1):
  Adds spinlock protection in interrupt context
  
Downstream (v5.10):
  Same code runs in process context (not interrupt)
```
✗ **Invalid**: The context fundamentally changed - spinlock may not be needed or may need different locking primitive.

### 4. Verify Missing or Extra Hunks

**Missing hunks**: Parts of upstream patch not applied downstream
- Check if the missing code exists in a different form in downstream
- Verify if the missing hunk is needed (may not apply to older kernel version)

**Example - Acceptable missing hunk**:
```
Upstream: Patches both foo_new() and foo_old()
Downstream: Only patches foo_old()

Reason: foo_new() was introduced in v5.15, downstream is v5.10
✓ Valid if foo_new() doesn't exist in downstream
```

**Extra hunks**: Changes in downstream not in upstream
- Determine why extra changes were needed
- Common valid reasons:
  - API adaptation (older kernel uses different API)
  - Additional fixes needed for older code structure
  - Backport dependencies (fixing additional call sites)

**Example - Valid extra hunk**:
```
Upstream: Fixes one call site of vulnerable function
Downstream: Fixes two call sites

Reason: Downstream has an extra legacy call site that was removed before upstream fix
✓ Valid if extra fix prevents the same vulnerability
```

### 5. Detect Red Flags

These indicate likely **incorrect backport**:

**🚩 RED FLAG: Function name mismatch in hunk header (MOST CRITICAL)**
```
Upstream hunk header:   @@ -150,7 +155,8 @@ static void process_request(...)
Downstream hunk header: @@ -143,7 +143,8 @@ static void handle_request(...)
```
The fix landed in `handle_request` but was meant for `process_request`.
Always read the text after the second `@@` in each hunk header.

**🚩 RED FLAG: Function name mismatch (content level)**
```
Upstream: Patches handle_request()
Downstream: Patches process_request()  // Different function!
```

**🚩 RED FLAG: Opposite logic**
```
Upstream: Changes if (foo) to if (!foo)
Downstream: Keeps if (foo)  // Logic not inverted!
```

**🚩 RED FLAG: Critical code missing**
```
Upstream: Adds both error check AND cleanup
Downstream: Adds only error check, no cleanup  // Memory leak!
```

**🚩 RED FLAG: Wrong struct field**
```
Upstream: Sets req->cmd_flags
Downstream: Sets req->flags  // Different field!
```

**🚩 RED FLAG: Off-by-one in array access**
```
Upstream: Changes array[i] to array[i+1]
Downstream: Keeps array[i]  // Index not updated!
```

## Reporting Backport Issues

When you find a potential backport problem, report it with:

### Title Format
```
type: Incorrect backport - <specific issue>

Examples:
- backport-error: Incorrect backport - patch applied to wrong function
- backport-error: Incorrect backport - missing critical cleanup code
- backport-error: Incorrect backport - logic inverted compared to upstream
```

### Description Format
```markdown
**Backport Issue**: <What's wrong>

**Upstream (v<version>)**:
<Show upstream code/behavior>

**Downstream (v<version>)**:
<Show downstream code/behavior>

**Analysis**:
<Explain why this is incorrect>

**Impact**:
<What bug/vulnerability this creates>

**Recommendation**:
<How to fix it>
```

### Example Report
```markdown
**Backport Issue**: Patch applied to wrong function with different locking context

**Upstream (v6.1)**:
The patch adds a NULL check in `process_request()` which runs under `req_lock` spinlock:
```c
spin_lock(&req_lock);
if (!req)              // ← NULL check added
    goto unlock;
process_request(req);
unlock:
spin_unlock(&req_lock);
```

**Downstream (v5.10)**:
The patch was applied to `handle_request()` which runs in process context without locks:
```c
void handle_request(struct request *req)
{
    if (!req)              // ← Check added here
        return;
    // No locking!
    process(req);
}
```

**Analysis**:
The upstream patch was meant to fix a race condition by adding a NULL check under spinlock protection. The downstream backport applied the NULL check to a different function that doesn't have the same locking, so it doesn't fix the race condition.

**Impact**:
The original race condition remains unfixed in downstream. A concurrent thread could free `req` while another thread checks it, leading to use-after-free.

**Recommendation**:
Apply the NULL check in the correct location: inside `process_request()` under the same `req_lock` spinlock that exists in the v5.10 codebase.
```

## When Differences Are Acceptable

Not all differences indicate problems. These are often **acceptable**:

### API Adaptation
Upstream and downstream use different APIs for the same purpose:
```
Upstream: blk_mq_alloc_request()  // Multi-queue API (v5.0+)
Downstream: blk_alloc_request()   // Legacy API (v5.10)
✓ Valid if functionality is equivalent
```

### Helper Function Inline
Code moved into/out of helper functions:
```
Upstream: Calls helper_function(x, y)
Downstream: Inlines the helper code directly
✓ Valid if logic is identical
```

### Variable Rename
Same purpose, different names:
```
Upstream: Uses 'req->cmd_flags'
Downstream: Uses 'req->flags' (field renamed in later versions)
✓ Valid if field serves same purpose
```

### Additional Call Sites
More locations need fixing in downstream:
```
Upstream: Fixes 1 call site
Downstream: Fixes 2 call sites (old code had more usage)
✓ Valid if extra fixes prevent same issue
```

## Verification Strategy

0. **(MANDATORY FIRST STEP) Compare function names** — Read the `@@ ... @@ func_name`
   text in every hunk header from both the upstream and downstream diff.
   If any hunk lands in a different function: treat as critical red flag (see above).
1. **Read upstream commit message** - Understand the intent
2. **Compare code structure** - Is the location equivalent?
3. **Check semantics** - Does it achieve the same goal?
4. **Verify completeness** - All critical parts backported?
5. **Test logic** - Would it fix the same bug in downstream?
6. **Verify execution context** - Same locking, same interrupt/process context?

**If in doubt, report it as a potential backport issue.**

Better to flag a possibly-correct backport for human review than to miss an incorrect one that introduces a regression.
