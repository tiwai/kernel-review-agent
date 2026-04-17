# Linux Kernel Commit Review Agent

AI-powered agent for automated review of Linux kernel git commits. This agent analyzes code changes in a downstream kernel tree to identify potential regressions before they reach production.

## Features

- **Code-focused analysis**: Reviews only code changes, ignoring commit message quality and tags
- **5-task review protocol**: Systematic approach based on Linux kernel review best practices
- **Subsystem-aware**: Automatically loads relevant subsystem guides (RCU, MM, networking, BPF, etc.)
- **False positive filtering**: Applies verification checks to eliminate false positives
- **LKML-compliant output**: Generates plain text reports suitable for mailing lists
- **Structured metadata**: JSON output with severity scoring for tooling integration

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Verify installation
python kernel_review_agent.py --help
```

## Prerequisites

- **Python 3.8+**
- **Git** (in PATH)
- **OpenAI-compatible LLM server** running locally or remotely
  - Example: llama.cpp server, vLLM, Ollama, etc.
- **Linux kernel git tree** (run from within a kernel repository)

## Usage

### Basic Usage

```bash
# Review single commit
python kernel_review_agent.py HEAD

# Review commit by SHA
python kernel_review_agent.py abc123def456

# Review commit range
python kernel_review_agent.py HEAD~5..HEAD

# Review range with specific endpoints
python kernel_review_agent.py v6.8..v6.9
```

### With Custom LLM Server

```bash
# Connect to custom host/port
python kernel_review_agent.py HEAD --host 192.168.1.100 --port 11434

# Use specific model
python kernel_review_agent.py HEAD --model gpt-4 --api-key your-key-here
```

### Upstream Comparison

```bash
# Compare with upstream branch to identify downstream-specific changes
python kernel_review_agent.py abc123 --upstream-branch upstream
python kernel_review_agent.py HEAD --upstream-branch origin/master
```

### Output Options

```bash
# Save to custom directory
python kernel_review_agent.py HEAD --output-dir ./reviews/

# Enable verbose output
python kernel_review_agent.py HEAD --verbose
```

### Debug Options

```bash
# Enable debug output with detailed step information
python kernel_review_agent.py HEAD --debug

# Dump LLM prompts and responses to files for debugging
python kernel_review_agent.py HEAD --dump-prompts

# Specify custom dump directory
python kernel_review_agent.py HEAD --dump-prompts --dump-dir ./debug/

# Combine verbose and debug
python kernel_review_agent.py HEAD --verbose --debug --dump-prompts
```

**Debug features:**
- `--debug`: Shows detailed information at each step (context gathered, categories found, LLM call details, token usage)
- `--dump-prompts`: Saves all LLM prompts and responses to numbered files (001_prompt.txt, 001_response.txt, etc.)
- `--dump-dir`: Specifies where to save dump files (default: `debug_dumps/`)

The dump files are useful for:
- Understanding what prompts are sent to the LLM
- Debugging LLM response parsing issues
- Analyzing token usage and prompt effectiveness
- Fine-tuning prompts for better results

## Output Files

For each commit reviewed, two files are generated:

### 1. `review-inline-<sha>.txt`

LKML-compliant plain text report with:
- Commit metadata (SHA, author, subject)
- Summary of findings
- Quoted diff with inline comments
- Detailed analysis of each issue

Example:
```
commit abc123def456789
Author: Jane Developer <jane@example.com>

mm: fix use-after-free in page reclaim

This commit has a potential memory-leak that should be reviewed.

> diff --git a/mm/vmscan.c b/mm/vmscan.c
> --- a/mm/vmscan.c
> +++ b/mm/vmscan.c
> @@ -1234,5 +1234,8 @@ static int shrink_page_list(...)
> +    folio = folio_alloc();
         ^
Can this leak the folio? The allocation is not freed in the error path
when the function returns early...
```

### 2. `review-metadata-<sha>.json`

Structured JSON metadata:
```json
{
  "author": "Jane Developer <jane@example.com>",
  "sha": "abc123def456789",
  "subject": "mm: fix use-after-free in page reclaim",
  "issues-found": 1,
  "issue-severity-score": "medium",
  "issue-severity-explanation": "1 issue found that should be fixed"
}
```

Severity levels: `none`, `low`, `medium`, `high`, `urgent`

## Architecture

```
kernel_review_agent.py          # CLI entry point
├── git_integration/            # Git operations
│   └── commit_extractor.py     # Extract commits, diffs
├── llm_integration/            # LLM communication
│   └── openai_client.py        # OpenAI-compatible API client
├── prompt_management/          # Review protocols
│   ├── prompt_loader.py        # Load and adapt prompts
│   └── subsystem_matcher.py    # Match diffs to subsystems
├── analysis/                   # Review workflow
│   └── workflow.py             # 5-task orchestration
├── output/                     # Report generation
│   ├── formatter.py            # LKML plain-text formatting
│   └── metadata.py             # JSON metadata
└── prompts/                    # Review protocols
    ├── review-core.md          # Core review protocol
    ├── technical-patterns.md   # Bug patterns
    ├── false-positive-guide.md # Verification checks
    └── subsystem/              # 51 subsystem guides
```

## Review Protocol (5 Tasks)

1. **Context Gathering**: Extract changed functions, files, and structures
2. **Change Categorization**: Break changes into categories (control-flow, resource-management, etc.)
3. **Regression Analysis**: Apply bug patterns and subsystem-specific checks
4. **Verification**: Eliminate false positives using concrete evidence requirements
5. **Reporting**: Generate LKML-compliant report and JSON metadata

## Subsystem Coverage

The agent automatically loads guides for 51+ kernel subsystems:

- **Memory Management**: Page tables, folios, VMA, allocation, reclaim
- **Concurrency**: RCU, locking, synchronization
- **Networking**: Sockets, skb handling, protocols
- **BPF**: Verifier, maps, kfuncs
- **Filesystems**: VFS, btrfs, NFSD
- **Hardware**: Block, DRM/GPU, PCI, TTY
- And many more...

## Examples

### Review Recent Commits

```bash
# Review last 10 commits
python kernel_review_agent.py HEAD~10..HEAD --output-dir ./reviews/

# Count issues found
grep -c "issues-found" ./reviews/*.json
```

### Integration with CI/CD

```bash
#!/bin/bash
# review-commits.sh - Review all commits in a branch

BRANCH="downstream-6.8"
BASE="upstream"

python kernel_review_agent.py "$BASE..$BRANCH" \
    --host localhost \
    --port 11434 \
    --output-dir "./reviews/$BRANCH" \
    --upstream-branch "$BASE"

# Check for high-severity issues
jq -r 'select(."issue-severity-score" == "high") | .sha' \
    "./reviews/$BRANCH"/*.json
```

## Configuration

Edit `config.py` to change defaults:

```python
# LLM API defaults
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8080
DEFAULT_MODEL = "gpt-4"

# LLM parameters
DEFAULT_MAX_TOKENS = 8000
DEFAULT_TEMPERATURE = 0.1

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 1.0
RETRY_BACKOFF = 2.0
```

## Limitations

- **Merge commits**: Skipped (too complex for automated analysis)
- **Binary files**: Ignored (focuses on text-based code changes)
- **Commit messages**: Not evaluated (code-only review)
- **Fixes tags**: Not verified (downstream focus)

## Troubleshooting

### "Must run in a git repository"
Run the agent from within a Linux kernel git tree.

### "Cannot connect to LLM API"
Ensure your LLM server is running and accessible:
```bash
curl http://localhost:8080/v1/models
```

### "Failed to parse JSON"
The LLM may not be returning valid JSON. Try:
- Using a more capable model
- Increasing `DEFAULT_MAX_TOKENS` in config.py
- Enabling `--verbose` to see raw responses

## License

This tool is provided as-is for Linux kernel development and review purposes.

## Credits

Based on Linux kernel review protocols and best practices from the kernel community.
