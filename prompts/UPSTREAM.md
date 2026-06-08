# Upstream Tracking Information

This directory contains Linux kernel review prompts derived from Chris Mason's review-prompts repository.

## Upstream Repository

- **URL**: https://github.com/masoncl/review-prompts
- **License**: MIT (Copyright 2024 Chris Mason)

## Sync History

### Initial Import
- **Date**: April 17, 2026
- **Base Commit**: ~6c277db09b22 (April 10, 2026)
  - "review-core: Gate on code-path reachability before deep analysis"
- **Notes**: Prompts were adapted with git commands instead of semcode MCP tools

### Current Sync
- **Date**: June 8, 2026
- **Target Commit**: 169f0864346a (May 29, 2026)
  - "Merge pull request #69 from leitao/main"
- **Commits Applied**: ~42 commits affecting kernel/ prompt files

## Our Modifications vs Upstream

### Structural Differences
1. **No agent integration files**: We exclude `kernel/agent/`, `kernel/skills/`, `kernel/slash-commands/`
2. **Prompt organization**: We organize into `default/` and `small/` subdirectories
3. **Model-specific optimization**: `prompt-sets.json` maps models to appropriate prompt sets

### Content Differences
1. **Git commands instead of semcode MCP**:
   - Upstream: Uses semcode MCP tools (`diff_functions`, `find_callchain`, `grep_functions`)
   - Ours: Uses standard git commands (`git show`, `git grep`, `grep`)
   - Location: `review-core.md` Task 1 section

2. **Simplified default/ set**:
   - Core review protocol from upstream `kernel/`
   - Subsystem guides from upstream `kernel/subsystem/`
   - Excludes advanced tooling integration

3. **Small model optimization** (`small/` directory):
   - Subset of subsystems (11 vs 60+ files)
   - Condensed prose and examples
   - ~3x smaller token budget (~5k vs ~15k)
   - Focuses on critical patterns: memory management, locking, RCU, scheduler, VFS

## Update Procedure

When syncing with upstream:

1. Identify new/changed files in upstream `kernel/` directory
2. Update `default/` prompts:
   - Preserve git command approach in Task 1
   - Exclude agent/skills/slash-commands content
   - Apply all subsystem guide updates
3. Update `small/` prompts:
   - Sync critical subsystems only
   - Maintain condensed format
   - Evaluate new subsystems for inclusion based on value/size ratio
4. Update this file with new sync information

## File Mapping

| Our Path | Upstream Path | Notes |
|----------|---------------|-------|
| `default/review-core.md` | `kernel/review-core.md` | Modified: git commands instead of semcode |
| `default/technical-patterns.md` | `kernel/technical-patterns.md` | Direct copy |
| `default/false-positive-guide.md` | `kernel/false-positive-guide.md` | Direct copy |
| `default/subsystem/*.md` | `kernel/subsystem/*.md` | Direct copy of subsystem guides |
| `small/review-core.md` | `kernel/review-core.md` | Condensed version |
| `small/subsystem/*.md` | `kernel/subsystem/*.md` | Subset, condensed versions |
