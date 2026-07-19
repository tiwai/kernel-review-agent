# AI "slop" indicators

**Risk**: None. Subjective quality only — never raise slop in the regression pass.

Load when performing subjective review (`subsystem/subjective-review.md`). Never raise slop as a bug.

## What this is NOT

- Not a bug hunt — correctness belongs in the regression pass.
- Not an authorship verdict — never write "AI-generated", never mention author or tool.
- Not an attribution check — `Assisted-by:`/`Co-developed-by:` trailers are fine.
- Not a style-guide sweep — only raise what checkpatch misses and a careful human would flag.

## Confidence model (high bar)

- **Cluster requirement**: one weak signal is never enough; require a clearly-located instance plus corroboration (repeated tell or two different tells).
- **Compare to neighbours**: judge against surrounding code in the same file/subsystem; if the pattern already exists nearby, suppress.
- **Plausible-reason test**: if a competent kernel developer could have a sane reason, suppress.
- **Hard cap**: at most 3 slop questions per patch; pick the most concrete.

## Indicators

Each entry: signal → confirm → norm → example question.

### SLOP-COMMENT: comments that restate the code
- Signal: paraphrases the next line, narrates unrelated internals, or explains the obvious.
- Confirm: removing the comment loses no information a kernel developer wouldn't already have.
- Norm: comments explain WHY, not WHAT.
- Question: "Does this comment add anything over the code below it?"

### SLOP-VERBOSE: verbose/deeply-nested code
- Signal: repeated long dereference chains, deeper indentation than surrounding code, gratuitous wrappers.
- Confirm: check if a local variable or early return/goto would flatten it.
- Question: "Could `x->y->z->w` be hoisted into a local here?"

### SLOP-COPYPASTE: duplicated logic instead of factoring
- Signal: near-verbatim copy of an existing function/block.
- Confirm: locate original via `git grep`, diff by eye.
- Question: "This looks close to `<existing>()` — could they share a helper?"

### SLOP-DEFENSIVE: redundant guards (style angle only)
- Signal: NULL/bounds check where surrounding contract already guarantees the condition.
- Confirm: only raise if redundancy is obvious from local context; if reachability is in doubt, leave it to the regression pass.
- Question: "Is this check reachable, or is the value already constrained by the caller?"

### SLOP-DEADCODE: additions with no consumer
- Signal: new enum value, label, local, or helper that nothing references.
- Confirm: `grep` for the new symbol; no user in the series = candidate.
- Question: "Is `<symbol>` used anywhere in the series?"

### SLOP-CHURN: cosmetic edits with no behavioural reason
- Signal: unexplained reformatting, renaming, or movement folded into a focused change.
- Confirm: check commit message for a stated reason.
- Question: "Is this rename/move needed, or could it be split out?"

### SLOP-OVERENG: heavy machinery for a small problem
- Signal: large new abstraction or reinvented facility that an existing kernel helper already provides.
- Confirm: identify the existing facility; weigh added lines against problem size.
- Question: "Is the existing `<facility>` usable here instead?"

### SLOP-NAMING: identifiers that fight kernel convention
- Signal: overlong descriptive identifiers where terse locals are the norm; opaque numeric test names.
- Confirm: compare against nearby identifiers of the same kind.
- Not slop: width/size literals in format strings that cannot interpolate a macro.
- Question: "Would a shorter name like `<suggestion>` fit better alongside nearby code?"

### SLOP-MSG: changelog that explains the what, not the why
- Signal: narrates the diff line-by-line, omits rationale, or uses non-kernel format (e.g. `Test Plan:` block).
- Confirm: check whether a reviewer learns *why* the change is needed, not just *what* changed.
- Question: "Could the changelog say why this is needed rather than restating the diff?"

## Output marking

Emit every finding as SR-* style: gentle, posed as a question, "this isn't a bug, but …", no author mention, no ALL CAPS, naming the exact code or prose. See `inline-template.md`.
