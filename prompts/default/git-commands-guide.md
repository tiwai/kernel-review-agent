# Git Commands for Code Review

This guide provides explicit git commands for accessing and analyzing code during kernel commit reviews.

## Reading Files

### Current commit version
```bash
git show <commit>:<path>
```
Example: `git show HEAD:drivers/net/e1000/e1000_main.c`

### Parent commit version (for deleted or modified code)
```bash
git show <commit>^:<path>
```
Example: `git show HEAD^:drivers/net/e1000/e1000_main.c`

### Specific revision
```bash
git show <commit-sha>:<path>
```

## Finding Function Definitions

### Find function definition in current tree
```bash
git grep -n "^function_name("
```
Returns file:line for function definitions

### Find function in specific file type
```bash
git grep -n "^function_name(" -- "*.c"
```

### Find struct/type definitions
```bash
git grep -n "^struct struct_name" -- "*.h"
```

## Searching for Patterns

### Search for function calls
```bash
git grep "function_name(" -- "*.c"
```

### Search with line numbers
```bash
git grep -n "pattern"
```

### Search in specific paths
```bash
git grep "pattern" -- "drivers/net/*.c"
```

### Case-insensitive search
```bash
git grep -i "pattern"
```

### Search for symbol usage (pickaxe)
```bash
git log -S "symbol_name" -- <path>
```
Finds commits that added or removed the symbol

### Search commit messages
```bash
git log --grep="pattern"
```

## Finding Call Relationships

### Find all callers of a function
```bash
git grep "function_name(" -- "*.c"
```
Then read each file to identify the calling function

### Find callees in a function
1. Read the function body using `git show <commit>:<path>`
2. Parse for function calls in the body
3. Search for each callee definition using `git grep`

## Extracting Code Context

### Extract function body with context
```bash
git show <commit>:<path> | grep -A 50 "^function_name("
```
Shows function definition plus 50 lines

### Extract struct definition
```bash
git show <commit>:<path> | grep -A 20 "^struct name"
```

### Get file context around line number
```bash
git show <commit>:<path> | sed -n '100,150p'
```
Shows lines 100-150 from the file

## Tracing Changes

### Show what changed in a function
```bash
git log -p -S "function_name" -- <path>
```

### Find commits that modified specific lines
```bash
git log -L :function_name:<path>
```

### Show commits in a range
```bash
git log --oneline <start>..<end>
```

## Analyzing Commit Ranges

### List commits in range
```bash
git log --format="%H %s" <start>..<end>
```

### Search range for pattern
```bash
git log --grep="pattern" <start>..<end>
```

### Search range for symbol changes
```bash
git log -S "symbol" <start>..<end>
```

## Best Practices

1. **Always load complete functions**: Never use fragments from diffs
   - Use `git show <commit>:<path>` to get full file
   - Extract complete function bodies, not just changed lines

2. **Verify file paths**: Check that files exist at the commit
   - Use `git ls-tree <commit> <path>` to verify

3. **Document your references**: Note the commit and path when loading code
   - Example: "Loading e1000_main.c from commit abc123"

4. **Systematic exploration**:
   - List all required context first
   - Load files in logical order (headers, then implementations)
   - Trace call chains systematically (one level at a time)

5. **For deleted code**: Always use parent commit
   - `git show <commit>^:<path>` for the version before deletion

6. **Reading headers**:
   - Check #include statements in C files
   - Load corresponding headers: `git show <commit>:include/linux/header.h`
   - Trace through included headers as needed

## Common Patterns

### Analyzing a function change
```bash
# 1. Get current version
git show HEAD:path/to/file.c | grep -A 50 "^function_name("

# 2. Get parent version
git show HEAD^:path/to/file.c | grep -A 50 "^function_name("

# 3. Find all callers
git grep "function_name(" -- "*.c"

# 4. Load caller functions
git show HEAD:path/to/caller.c | grep -A 50 "^caller_function("
```

### Tracing error handling
```bash
# 1. Find error path functions
git grep -n "error_function\|goto.*err\|return.*ERR" -- <path>

# 2. Load each error handler
git show HEAD:<path> | grep -A 30 "^err_label:"
```

### Finding API usage examples
```bash
# 1. Find all uses of an API
git grep "api_function(" -- "*.c"

# 2. Load example usage
git show HEAD:<path_to_example>
```
