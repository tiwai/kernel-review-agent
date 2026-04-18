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
# Clone or copy the repository
git clone <repository-url> /path/to/kernel-review-agent
cd /path/to/kernel-review-agent

# Install core dependencies (OpenAI-compatible and Ollama support)
pip install -r requirements.txt

# Optional: Install Anthropic Claude API support
pip install anthropic

# Optional: Install Google Vertex AI support
pip install google-cloud-aiplatform

# Verify installation
python kernel_review_agent.py --help
```

### Running from Anywhere

The agent can be run from any directory - it automatically finds its prompts and configuration files relative to the installation directory:

```bash
# Run from any directory
cd /path/to/linux-kernel
python /path/to/kernel-review-agent/kernel_review_agent.py HEAD

# Or add to PATH
export PATH="/path/to/kernel-review-agent:$PATH"
kernel_review_agent.py HEAD
```

### Environment Variables

**`KREVIEW_HOME`** (optional): Override the installation directory location
```bash
export KREVIEW_HOME=/opt/kernel-review-agent
python kernel_review_agent.py HEAD
```

This is useful if:
- The agent is installed in a non-standard location
- You want to use a custom set of review prompts
- You're running from a symlink or wrapper script

## Prerequisites

- **Python 3.8+**
- **Git** (in PATH)
- **LLM Provider** - one of:
  - **OpenAI-compatible** server (llama.cpp, vLLM, etc.) - uses `openai` package
  - **Ollama** - local LLM server - uses `openai` package
  - **Anthropic Claude API** - requires `anthropic` package and API key
  - **Google Vertex AI** - requires `google-cloud-aiplatform` package and GCP project
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

### LLM Provider Options

The agent supports multiple LLM providers:

#### OpenAI-Compatible (llama.cpp, vLLM, etc.)
```bash
# Default - auto-detected for custom host/port
python kernel_review_agent.py HEAD --host localhost --port 8080

# Explicit provider selection
python kernel_review_agent.py HEAD --provider openai --host localhost --port 8080 --model gpt-4
```

#### Ollama
```bash
# Auto-detected when using port 11434
python kernel_review_agent.py HEAD --host localhost --port 11434 --model llama3.1

# Explicit provider selection
python kernel_review_agent.py HEAD --provider ollama --model llama3.1
```

#### Anthropic Claude API
```bash
# Set API key via environment variable
export ANTHROPIC_API_KEY=your-api-key-here
python kernel_review_agent.py HEAD --provider anthropic --model claude-3-5-sonnet-20241022

# Or pass API key directly
python kernel_review_agent.py HEAD --provider anthropic --anthropic-api-key your-key --model claude-3-5-sonnet-20241022
```

#### Google Vertex AI
```bash
# Set project ID via environment variable
export GOOGLE_CLOUD_PROJECT=your-project-id
python kernel_review_agent.py HEAD --provider google --model gemini-1.5-pro

# Or pass project ID and location directly
python kernel_review_agent.py HEAD --provider google --google-project your-project-id --google-location us-central1
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

### Performance Options

```bash
# Skip false-positive verification for faster review
python kernel_review_agent.py HEAD --skip-verification

# This skips the verification step, which can:
# - Reduce review time by 20-40%
# - Report more potential issues (may include false positives)
# - Be useful for initial quick scans
```

**When to use `--skip-verification`:**
- Quick initial scans of large commit ranges
- When verification step times out frequently
- When you prefer to manually review all findings
- During development/testing to see raw analysis results

**Trade-offs:**
- **Faster**: Skips one LLM call per commit (saves time and tokens)
- **More findings**: May report defensive programming as issues
- **Less precise**: False positives not filtered out

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
└── prompts/                    # Review protocols (from review-prompts by Chris Mason)
    ├── review-core.md          # Core review protocol
    ├── technical-patterns.md   # Bug patterns
    ├── false-positive-guide.md # Verification checks
    └── subsystem/              # 51 subsystem guides
```

## Review Protocol (5 Tasks)

1. **Context Gathering**: Extract changed functions, files, and structures
2. **Change Categorization**: Break changes into categories (control-flow, resource-management, etc.)
3. **Regression Analysis**: Apply bug patterns and subsystem-specific checks
4. **Verification**: Eliminate false positives using concrete evidence requirements (optional, use `--skip-verification` to disable)
5. **Reporting**: Generate LKML-compliant report and JSON metadata

**Note**: The verification step (Task 4) can be skipped with `--skip-verification` for faster reviews at the cost of potentially more false positives.

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
# LLM API defaults (for OpenAI-compatible providers)
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8080
DEFAULT_MODEL = "gpt-4"
DEFAULT_API_KEY = "dummy"  # Most local servers don't require real keys

# LLM parameters
DEFAULT_MAX_TOKENS = 16000  # Increased for complex kernel reviews
DEFAULT_TEMPERATURE = 0.1

# Task-specific token limits
CATEGORIZE_MAX_TOKENS = 8000    # Task 1: Categorize changes
ANALYZE_MAX_TOKENS = 16000       # Task 2: Analyze for regressions
VERIFY_MAX_TOKENS = 16000        # Task 3: Verify findings

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 1.0
RETRY_BACKOFF = 2.0

# Timeout configuration
LLM_TIMEOUT = 300  # seconds (5 minutes) - timeout for LLM API calls
CONNECT_TIMEOUT = 10  # seconds - timeout for initial connection
```

**Timeout Configuration:**
- `LLM_TIMEOUT`: Maximum time to wait for LLM response (default: 300s / 5 minutes)
- `CONNECT_TIMEOUT`: Maximum time to wait for initial connection (default: 10s)
- Increase `LLM_TIMEOUT` if you see timeout errors with large diffs or complex commits
- The agent will retry up to `MAX_RETRIES` times on timeout before giving up

## Limitations

- **Merge commits**: Skipped (too complex for automated analysis)
- **Binary files**: Ignored (focuses on text-based code changes)
- **Commit messages**: Not evaluated (code-only review)
- **Fixes tags**: Not verified (downstream focus)

## Troubleshooting

### "Must run in a git repository"
Run the agent from within a Linux kernel git tree.

### "Cannot connect to LLM API" or "Failed to initialize client"

**For OpenAI-compatible servers:**
```bash
# Verify server is running
curl http://localhost:8080/v1/models
```

**For Ollama:**
```bash
# Start Ollama server
ollama serve

# Verify it's running (in another terminal)
curl http://localhost:11434/api/tags
```

**For Anthropic:**
- Verify your API key is set: `echo $ANTHROPIC_API_KEY`
- Check your API key is valid at https://console.anthropic.com/

**For Google Vertex AI:**
- Verify your project ID is set: `echo $GOOGLE_CLOUD_PROJECT`
- Ensure you're authenticated: `gcloud auth application-default login`
- Check the API is enabled in your GCP project

### "Failed to parse JSON" or "Response may be truncated"
The LLM response was cut off before completing the JSON output. This happens when the response exceeds the token limit.

**Solutions:**
- Increase task-specific token limits in config.py:
  ```python
  CATEGORIZE_MAX_TOKENS = 16000   # For large commits
  ANALYZE_MAX_TOKENS = 32000      # For complex analysis
  VERIFY_MAX_TOKENS = 16000
  ```
- Use a model with larger context window
- Use `--dump-prompts` to see the full truncated response
- Check warnings like `[WARNING] Response was truncated due to token limit`

**Note:** The agent will automatically warn when responses are close to or exceed the token limit.

### "LLM request timed out"
The LLM took too long to respond. Solutions:
- Increase `LLM_TIMEOUT` in config.py (default: 300 seconds)
- Use a faster model or reduce `DEFAULT_MAX_TOKENS`
- Check if the LLM server is overloaded
- Enable `--debug` to see which task is timing out

**Note:** When processing multiple commits, the agent will skip timed-out commits and continue with the rest.

## License

The kernel review prompts in the `prompts/` directory are licensed under the MIT License.
These prompts are maintained by Chris Mason in the review-prompts repository:
https://github.com/masoncl/review-prompts

See the LICENSE file for the full MIT license text.

The agent code (Python modules) is provided as-is for Linux kernel development and review purposes.

## Credits

**Review Prompts**: The systematic kernel review protocols and subsystem guides used by this
agent are from the [review-prompts](https://github.com/masoncl/review-prompts) project
by [Chris Mason](https://github.com/masoncl), licensed under the MIT License.

**Agent Implementation**: Based on Linux kernel review best practices from the kernel community.
