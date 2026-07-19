# Callstack Regression Analysis

Analyzes regressions across the full callstack (callers and callees). See technical-patterns.md "NULL Pointer Dereference" for guidance. Note: `foo->ptr` dereferences `foo` but NOT `ptr`. Required for all non-trivial changes.

Add Tasks 1-9 to a TodoWrite. Complete every task before finishing.

---

## CRITICAL: RETRACTION RULE

If you conclude something IS a bug then reverse that conclusion, treat the reversal with extreme skepticism. State the retraction explicitly, re-examine dismissal reasoning, and apply a higher burden of proof. "Caller should prevent this" or "normally handled" are insufficient — you must prove the triggering condition is **structurally impossible** with concrete code references.

## CRITICAL: REACHABILITY DISMISSALS

A path that can infinite loop, deadlock, crash, or corrupt data is a bug even if preconditions make it unlikely. Only dismiss if the triggering condition is **structurally impossible** — code literally cannot reach that state regardless of timing, memory pressure, or concurrent operations. Do not dismiss based on:
- "The caller normally prevents this"
- "Only happens if upstream function fails"
- "The old code had a worse bug there"
- "Extremely unlikely in practice"

---

## CRITICAL: Batch All Semcode Calls

Each API turn re-sends conversation history — batch all lookups. Before starting Tasks 1-2, identify ALL callees and callers needed, then call `find_function` and `find_callers` for ALL of them in ONE message each.

---

# Task 0: Category iteration

Iterate through all CHANGE CATEGORIES if provided; otherwise treat the entire unit as one category. Skip reloading already-loaded definitions/callers/callees.

- For EVERY category: perform Tasks 1-6 separately and fully
- Output: `Category N of M: name, description`; callers loaded; callees loaded (with random sample lines as proof)

## Task 1: Callee traversal

- **callee.1**: Read each modified function body; record all callees and arguments. Output: callee names.
- **callee.2**: Load complete definition for each callee (`git grep -n "^callee_name("`, `git show <commit>:<path>`). Output: callee names + a random line from each (proof of reading).
- **callee.3**: Trace 2-3 levels deep; repeat for each callee's callees.
- **callee.4**: Apply all checks below to each callee in the chain. Output: names + random line.
- **callee.5**: Proceed to caller analysis.

## Task 2: Caller traversal

- **caller.1**: Use `git grep "modified_function(" -- "*.c"` to find call sites; identify containing functions. Output: caller names.
- **caller.2**: Load complete definition for each caller. Batch all `find_function` calls in ONE message. Output: caller name, size in lines, random line (proof of reading).
- **caller.3**: For callers that propagate return values, trace up to 3 levels. Output: caller name, return value line.
- **caller.4**: Apply Tasks 3-7 to every caller. Output: names + random line.
- **caller.5**: Continue to lock analysis.

## Task 3: Mandatory Lock requirements

- **lock.1**: Verify proper locks are held in every tracked function (including unmodified callers/callees). Output: locks required.
- **lock.1b**: Verify lock **scope**, not just presence. When a lock is acquired partway through a function, load all callees executing before acquisition — they may access the protected resource outside lock scope. Output: for each concurrent function, state the exclusion point and confirm no shared-resource access precedes it.
- **lock.2**: Ensure functions take and release locks as expected by caller.
- **lock.3**: If locks are changed/dropped during a call, verify code properly revalidates state.
- **lock.4**: Ensure caller provides all locks required by callees.
- **lock.5**: Continue to Task 4.
- Output: `Category NUMBER [ list of locks checked ]`

## Task 4: Mandatory locking in error path validation

- **lock.6**: For every lock acquired, trace all error paths to ensure locks are properly released/handed off (including unmodified callers/callees). Output: locations of all error paths.
- **lock.7**: Continue to Task 5.
- Output: `Category NUMBER [ error path lines ]`

## Task 5: Mandatory resource propagation validation

- Every pointer assignment is a potential allocation; check for leaks and misuse (including `void *`). Output: at least 3 pointer assignments in modified functions with line of code.
- **resource.1**: Trace resource ownership through function boundaries (including unmodified callers/callees); ensure resources are returned/processed before being overwritten.
- **resource.2**: For kmalloc/kcalloc/kzalloc/vmalloc: if size can be 0, report potential ZERO_SIZE_PTR crash.
- **resource.3**: For multiple pointers to same memory, track how writes through one affect others. Output: list of aliased pointers.
- **resource.4**: Verify resources are properly initialized, locked, and freed.
- **resource.5**: Continue to Task 5B.
- Output: `Category NUMBER [ list of resources checked: line where each was assigned ]`

## Task 5B: Mandatory RCU ordering validation

**CRITICAL**: Catches use-after-free bugs in RCU-protected structures.

- **rcu.1**: For any `call_rcu()`, `synchronize_rcu()`, or `kfree_rcu()` in the diff: load `subsystem/rcu.md`. Output: loaded y/n.
- **rcu.2**: Identify data structures the object belongs to. Output: list.
- **rcu.3**: Verify removal from ALL lookup structures happens BEFORE `call_rcu()`. Output: removal location.
- **rcu.4**: If removal is in the callback — flag as use-after-free (wrong pattern; new readers can find the object after grace period but before removal). Output: `RCU-001 VIOLATION: removal in callback at [location]`.
- **rcu.5**: Check for field accesses between lookup and `refcount_inc_not_zero()` — those accesses are NOT protected. Output: accesses before refcount.
- **rcu.6**: Continue to Task 6a.

## Task 5C: Caller/callee argument analysis

Some bugs are only eliminated or triggered by specific arguments. Assess how the arguments used change any possible bugs.

## Task 6a: Loop control analysis

Examine loop control flow carefully, especially nested loops and gotos that restart loop machinery.
- Identify variables controlling loop flow
- Identify inner loops that modify control variables
- Identify conditions allowing normal exit
- Identify unloaded functions controlling iteration/exit — add to TodoWrite and load them

**DO NOT SKIP loading those functions** — skipping causes missing critical information needed to judge loop safety.

Example of dangerous pattern:
```c
while (current < limit) {
    current++;
    for (i = 0; i < SOME_COUNT; i++) {
        if (func())
            current = start;  // resets outer loop
    }
}
```

Output: `<FILENAME>:<FUNCTION> <loop description>`, control variables, additional functions identified, exit conditions. Load all newly identified functions.

## Task 6b: Mandatory loop control flow validation

- **loop.1**: Track resource-holding variables across loop iterations.
- **loop.2**: Assume all loops iterate multiple times; check pointer assignments for leaks and logic errors in both outer and inner loops.
- **loop.3**: If pointers are reassigned without freeing the previous value, check the entire function context for leaks.
- **loop.4**: Compare loop exit conditions across all parallel code paths (debug vs. non-debug, error vs. success) for consistency. Finding one `break` in one path is not sufficient.
- **loop.5**: Continue to Task 7.

## Task 7: Initialization validation

- For every function loaded into context (including unmodified callers/callees), check for variables and objects accessed without initialization. Output: function name, random line.
- Output: `Category NUMBER [ list of variables properly initialized ]`

## Task 8: Code Quality Checks

**MANDATORY — DO NOT SKIP**

1. Verify every comment matches actual behavior — check for logic inversions (e.g., comment says "if true" but code checks `!true`). Flag any mismatch as a regression.
2. Verify commit message claims are accurate.
3. Question design decisions; require proof of correctness.
4. Check naming conventions for new APIs.
5. Check against kernel C best practices.
6. Dead code and unused variables/functions are reportable issues.
7. Check spelling/grammar in comments and commit messages — flag only mistakes that impair understanding; ignore capitalization unless it changes meaning.
8. If a subsystem guide is loaded, check new/modified code against its coding-style rules (comment style, macro conventions, API preferences). Only flag new or modified lines.

## Task 9

Output a one-line description of each potential regression found and ruled out:

```
Ruled out regression N: Task N <one sentence description>
```

Reconsider each ruled-out regression against the RETRACTION RULE and REACHABILITY DISMISSALS at the top. Was it wrong to exclude them?

### Forward search for latent issues

For regressions dismissed because a code path "isn't reachable yet" or "no callers exist yet": patch series add infrastructure in one commit and wire it later — a bug in infrastructure is still a bug.

- If a git range was provided (`current_sha..series_end_sha`): use `git log --grep` or `git log -S` to search forward for commits enabling the dismissed path. If found, **reinstate as confirmed**.
- If no git range: report the issue and note a subsequent commit may enable it. Do NOT dismiss solely because the current commit doesn't trigger it.

Reconsider issues hidden by focusing too heavily on bugs later ruled out.

- Did you fully complete Tasks 1-9 for every category? y/n
- Did you gather all necessary context systematically? y/n
