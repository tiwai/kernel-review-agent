# Git Commands for Code Review

## Reading Files

```bash
git show <commit>:<path>          # Current commit version
git show <commit>^:<path>         # Parent commit version (deleted/modified code)
git show <commit-sha>:<path>      # Specific revision
```

## Finding Function Definitions

```bash
git grep -n "^function_name("            # Find definition in current tree
git grep -n "^function_name(" -- "*.c"  # Limit to file type
git grep -n "^struct struct_name" -- "*.h"  # Struct/type definitions
```

## Searching for Patterns

```bash
git grep "function_name(" -- "*.c"    # Function calls
git grep -n "pattern"                  # With line numbers
git grep "pattern" -- "drivers/net/*.c"  # Specific paths
git grep -i "pattern"                  # Case-insensitive
git log -S "symbol_name" -- <path>    # Commits adding/removing symbol (pickaxe)
git log --grep="pattern"              # Search commit messages
```

## Extracting Code Context

```bash
git show <commit>:<path> | grep -A 50 "^function_name("  # Function body
git show <commit>:<path> | grep -A 20 "^struct name"     # Struct definition
git show <commit>:<path> | sed -n '100,150p'             # Lines by number
```

## Tracing Changes

```bash
git log -p -S "function_name" -- <path>  # Changes to a function
git log -L :function_name:<path>         # Commits modifying specific lines
git log --oneline <start>..<end>         # Commits in range
```

## Analyzing Commit Ranges

```bash
git log --format="%H %s" <start>..<end>   # List commits
git log --grep="pattern" <start>..<end>   # Search range by message
git log -S "symbol" <start>..<end>        # Search range by symbol change
```

## Best Practices

- **Always load complete functions**: use `git show <commit>:<path>` for full file; never rely on diff fragments alone.
- **Verify file paths**: `git ls-tree <commit> <path>` confirms existence.
- **Deleted code**: always use parent commit (`<commit>^:<path>`).
- **Headers**: load corresponding headers via `git show <commit>:include/linux/header.h` and trace includes as needed.
- **Systematic exploration**: list required context first; load headers before implementations; trace call chains one level at a time.

## Common Patterns

### Analyzing a function change
```bash
git show HEAD:path/file.c | grep -A 50 "^function_name("   # Current
git show HEAD^:path/file.c | grep -A 50 "^function_name("  # Parent
git grep "function_name(" -- "*.c"                          # All callers
```

### Tracing error handling
```bash
git grep -n "error_function\|goto.*err\|return.*ERR" -- <path>
git show HEAD:<path> | grep -A 30 "^err_label:"
```

### Finding API usage examples
```bash
git grep "api_function(" -- "*.c"   # All uses
git show HEAD:<path_to_example>     # Load example
```
