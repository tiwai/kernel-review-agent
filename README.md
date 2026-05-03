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

Multiple installation methods are available. See [INSTALL.md](INSTALL.md) for complete details.

### Quick Install (System-Wide)

```bash
git clone <repository-url> /path/to/kernel-review-agent
cd /path/to/kernel-review-agent
pip install -r requirements.txt  # Install Python dependencies
sudo make install PREFIX=/usr    # Install to /usr/bin
```

After installation:
```bash
kernel-review-agent HEAD --verbose  # Works from anywhere!
```

### Quick Install (User)

No root required:
```bash
git clone <repository-url> /path/to/kernel-review-agent
cd /path/to/kernel-review-agent
pip install -r requirements.txt
make install PREFIX=~/.local
export PATH="$HOME/.local/bin:$PATH"
```

### Development / Local Use

Run directly without installation:
```bash
cd /path/to/kernel-review-agent
pip install -r requirements.txt
python kernel_review_agent.py HEAD --verbose
```

### Optional Provider Dependencies

```bash
# For Anthropic Claude API (direct)
pip install anthropic

# For Claude on Google Vertex AI
pip install 'anthropic[vertex]'

# For Google Vertex AI (Gemini)
pip install google-genai
```

See [INSTALL.md](INSTALL.md) for all installation methods (system-wide, user, pip, development).

### Custom Prompts Directory

You can use custom review prompts instead of the defaults:

```bash
# Use custom prompts directory
python kernel_review_agent.py HEAD --prompts-dir /path/to/custom-prompts

# Default uses installation directory
python kernel_review_agent.py HEAD  # Uses <install-dir>/prompts
```

This is useful for:
- Testing modified review protocols
- Using organization-specific review guidelines
- Maintaining multiple prompt versions

## Prerequisites

- **Python 3.8+**
- **Git** (in PATH)
- **LLM Provider** - one of:
  - **OpenAI-compatible** server (llama.cpp, vLLM, etc.) - uses `openai` package
  - **Ollama** - local LLM server - uses `openai` package
  - **Anthropic Claude API** - requires `anthropic` package and API key
  - **Claude on Google Vertex AI** - requires `anthropic[vertex]` package and GCP project
  - **Google Vertex AI (Gemini)** - requires `google-genai` package and GCP project
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

# Review multiple commits
python kernel_review_agent.py HEAD abc123 def456

# Review multiple ranges
python kernel_review_agent.py HEAD~5..HEAD~3 HEAD~1..HEAD
```

### List Mode

Review commits from a file instead of command-line arguments:

```bash
# Generate commit list from git log
git log --pretty=oneline HEAD~100..HEAD > commits.txt

# Review commits from list
python kernel_review_agent.py --list commits.txt --output-dir ./reviews/

# Combine list with command-line commits
python kernel_review_agent.py abc123 --list commits.txt
```

**List file format:**
- One commit per line
- First column: commit SHA (full or short)
- Remaining columns: ignored (e.g., commit subject from `git log --pretty=oneline`)
- Lines starting with `#`: comments (ignored)
- Empty lines: ignored

**Example list file:**
```
# Important security fixes
abc123def456789abcdef012345678901234567 Fix CVE-2024-1234 in network stack
def456789abc123def456789abc123def456789 Fix memory leak in driver

# Performance improvements  
789abc123def456789abc123def456789abc123 Optimize buffer allocation
```

**Use cases:**
- Process large numbers of commits efficiently
- Share commit lists between team members
- Automate reviews with generated lists
- Resume failed batches by removing processed commits from list

### Patch Mode

Review patch files instead of commits:

```bash
# Review single patch file
python kernel_review_agent.py --patch my-changes.patch

# Review multiple patches
python kernel_review_agent.py --patch *.patch --output-dir ./reviews/
```

**Patch mode behavior:**
- Arguments are treated as patch file paths (not commit SHAs)
- Patch is analyzed as if applied on top of current HEAD
- Output files are flat: `review-inline.txt` and `review-metadata.json` in output directory
- SUSE kernel-source verification is skipped
- If patch contains `Git-commit:` tag, upstream commit is checked
- Commit SHA and SUSE-commit fields are omitted from output

**Supported patch formats:**
- Git format-patch output (with headers)
- Plain unified diff files
- Patches with `Git-commit:` tag for upstream reference

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

#### Anthropic Claude API (Direct)
```bash
# Set API key via environment variable
export ANTHROPIC_API_KEY=your-api-key-here
python kernel_review_agent.py HEAD --provider anthropic --model claude-3-5-sonnet-20241022

# Or pass API key directly
python kernel_review_agent.py HEAD --provider anthropic --anthropic-api-key your-key --model claude-3-5-sonnet-20241022
```

#### Claude on Google Vertex AI
```bash
# Method 1: Using gcloud authentication (recommended for development)
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project-id
python kernel_review_agent.py HEAD --provider anthropic-vertex --model claude-3-5-sonnet@20241022

# Method 2: Using service account key file (recommended for production/CI)
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
export GOOGLE_CLOUD_PROJECT=your-project-id
python kernel_review_agent.py HEAD --provider anthropic-vertex --model claude-3-5-sonnet@20241022

# Method 3: Pass credentials file via command line
python kernel_review_agent.py HEAD --provider anthropic-vertex \
    --google-project your-project-id \
    --google-location us-east5 \
    --google-credentials /path/to/service-account-key.json \
    --model claude-3-5-sonnet@20241022
```

**Note**: Claude on Vertex AI uses `@` notation for model versions (e.g., `claude-3-5-sonnet@20241022`) and is available in specific regions like `us-east5` and `europe-west1`.

#### Google Vertex AI (Gemini)
```bash
# Method 1: Using gcloud authentication (recommended for development)
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project-id
python kernel_review_agent.py HEAD --provider google --model gemini-1.5-pro

# Method 2: Using service account key file (recommended for production/CI)
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
export GOOGLE_CLOUD_PROJECT=your-project-id
python kernel_review_agent.py HEAD --provider google --model gemini-1.5-pro

# Method 3: Pass credentials file via command line
python kernel_review_agent.py HEAD --provider google \
    --google-project your-project-id \
    --google-credentials /path/to/service-account-key.json \
    --model gemini-1.5-pro

# Or specify all parameters explicitly
python kernel_review_agent.py HEAD --provider google \
    --google-project your-project-id \
    --google-location us-central1 \
    --google-credentials /path/to/key.json
```

### Output Options

```bash
# Save to custom directory
python kernel_review_agent.py HEAD --output-dir ./reviews/

# Enable verbose output
python kernel_review_agent.py HEAD --verbose

# Write progress output to a log file instead of stdout
python kernel_review_agent.py HEAD~10..HEAD --log-file review.log

# Prefix every output line with a timestamp
python kernel_review_agent.py HEAD --timestamps

# Combine both for a timestamped log file
python kernel_review_agent.py HEAD~10..HEAD --log-file review.log --timestamps
```

`--log-file` redirects all output — including warnings and errors — to the specified file. Useful for batch runs where you want to capture the complete output without redirecting the shell.

`--timestamps` prepends `[HH:MM:SS]` to every output line, making it easy to see how long each analysis step takes. Can be combined with `--log-file`.

Can also be enabled persistently in the config file:
```json
{ "TIMESTAMPS": true }
```

### SUSE Kernel Integration

For SUSE downstream kernel repositories, the agent can enhance commit messages by automatically extracting detailed patch descriptions from the kernel-source repository:

```bash
# Enable commit message enhancement from kernel-source
python kernel_review_agent.py HEAD --suse-kernel-source /path/to/kernel-source

# Or configure in ~/.config/kernel-review-agent/config.json
{
  "SUSE_KERNEL_SOURCE_REPO": "/path/to/kernel-source"
}
```

**How it works:**
- When reviewing a downstream kernel commit with a `suse-commit:` tag and short message (< 10 lines)
- The agent looks up the corresponding kernel-source commit
- If that commit creates a patch in `patches.suse/` or `patches.kabi/`
- The detailed patch description is extracted and included in all LLM prompts
- This provides much richer context than the minimal downstream commit message

**Benefits:**
- **Better LLM understanding**: Patch description (problem explanation, fix rationale, Fixes: tags) is passed to the LLM for all review stages
- More accurate analysis with complete problem description
- Upstream commit references automatically extracted
- Better distinction between intentional fixes and potential regressions
- No manual lookup of patch files needed

**Example:**
- Downstream commit: "Fix use after free (bsc#1259701)"
- Enhanced with patch description: Full explanation of the UAF issue, root cause, fix rationale, and upstream commit reference

### Hybrid Mode with Tool Calling (Enhanced Verification)

**DEFAULT**: The agent now uses hybrid mode by default, combining pre-loaded context with on-demand tool calling for enhanced verification:

```bash
# Hybrid mode is enabled by default for OpenAI-compatible providers
python kernel_review_agent.py HEAD --host localhost --port 8080

# Disable tool calling and use standard mode only
python kernel_review_agent.py HEAD --disable-tools

# Explicitly enable (redundant, but supported)
python kernel_review_agent.py HEAD --enable-tools
```

**How it works:**
1. **Phase 1**: Standard review with pre-loaded context (categorize, analyze, verify)
2. **Phase 2**: Tool calling for deep-dive verification of specific findings
   - LLM uses `git_show` to read complete file contents
   - LLM uses `git_grep` to find function definitions and callers
   - Confirms bugs by inspecting actual code (not just diffs)

**Benefits:**
- **More accurate**: Catches bugs that static pattern matching might miss
- **Better verification**: Confirms timer callback signatures, error handling, etc. with actual code inspection
- **Same performance**: ~90s average (essentially identical to standard mode)
- **More thorough**: Found 2 issues vs 1 in standard mode on benchmark test

**Example verification:**
```
Standard mode: "Possible timer API conversion issue detected (pattern match)"
Hybrid mode:   "Timer callback signature mismatch CONFIRMED:
                - Found: void callback(unsigned long data)  
                - Required: void callback(struct timer_list *t)
                - Tool verified with git_grep inspection"
```

**Benchmark results** (commit 7172c6b1, qwen3.6:q4, 3 runs):
- Standard: 92.01s average, 1 finding
- Hybrid: 90.76s average, 2 findings ✅ **WINNER**

**Requirements:**
- Only works with OpenAI-compatible providers (`--provider openai` or `--provider ollama`)
- Other providers fall back to standard mode automatically

### Fix Patch Proposals

```bash
# Ask the LLM to propose fix patches for each identified issue
python kernel_review_agent.py HEAD --propose-fixes
```

When `--propose-fixes` is set and the review finds verified issues, the agent makes an additional LLM call to generate unified diff patches addressing each finding. The patches are written to `review-fix-patches.diff` in the same output directory as the other review files.

**Important caveats:**
- Patches are LLM-generated and **must be reviewed by a human** before applying
- Line numbers may be approximate; always verify with `git apply --check` before use
- Some issues (design problems, ABI changes) cannot be expressed as a simple diff; those are noted with `# No patch: <reason>`
- This adds one extra LLM call per commit with findings, increasing review time

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

```bash
# Force re-review even if output already exists
python kernel_review_agent.py HEAD --force

# Useful when:
# - Re-running with updated prompts or configuration
# - Testing changes to the review workflow
# - Overwriting previous results
```

**About output directory checking:**
- By default, commits with existing output directories are skipped (for resumability)
- Use `--force` to re-review and overwrite existing results
- Allows updating reviews after prompt improvements or configuration changes

```bash
# Override maximum output tokens for all LLM calls
python kernel_review_agent.py HEAD --max-tokens 32000

# Useful when:
# - Using models with different token limits (8k vs 32k vs 128k)
# - Getting truncated responses (increase limit)
# - Wanting faster responses (decrease limit)
```

**Default token limits:**
- Categorize changes: 8,000 tokens
- Analyze regressions: 16,000 tokens
- Verify findings: 16,000 tokens

When `--max-tokens` is specified, all tasks use the same limit.

```bash
# Override LLM request timeout
python kernel_review_agent.py HEAD --timeout 600

# Disable timeout completely (useful for very slow models or complex commits)
python kernel_review_agent.py HEAD --timeout 0
```

**Default timeout:** 300 seconds (5 minutes)

When `--timeout 0` is specified, timeout checks are completely disabled, allowing the LLM to take as long as needed to respond.

```bash
# Set reasoning effort for models that support it (e.g. gpt-oss)
python kernel_review_agent.py HEAD --reasoning-effort high
python kernel_review_agent.py HEAD --reasoning-effort medium
python kernel_review_agent.py HEAD --reasoning-effort low
```

Some models (e.g. gpt-oss) accept a `reasoning_effort` parameter controlling how much thinking the model applies before responding. Higher effort produces more thorough analysis at the cost of slower responses. Models that don't support this parameter silently ignore it.

```bash
# Re-run review if no issues found and it completed within 60 seconds
python kernel_review_agent.py HEAD --reevaluate-threshold 60
```

Low-parameter models can be inconsistent — a fast review that reports no issues may have missed something. With `--reevaluate-threshold N`, if the review completes in under N seconds with zero findings, the agent runs the review a second time. If the second run finds issues, those results are used instead; otherwise the original (no-issue) result is kept.

**Default:** disabled (threshold = 0)

This is most useful when:
- Using small/fast models (e.g., 7B–20B parameter models)
- Reviews complete suspiciously quickly (under a minute)
- You want a second opinion before concluding a commit is clean

Can also be set persistently in the config file:
```json
{ "REEVALUATION_TIME_THRESHOLD": 60 }
```

```bash
# Increase the maximum tool-call iterations per step
python kernel_review_agent.py HEAD --max-tool-iterations 20
```

When using tool-calling mode (`--enable-tools`), each analysis step runs up to N tool-call iterations before producing a final answer. The default is 10. For complex commits with many changed files, increasing this limit gives the LLM more rounds to gather context before concluding.

**Default:** 10 (configurable via `MAX_TOOL_ITERATIONS` in config file)

Can also be set persistently in the config file:
```json
{ "MAX_TOOL_ITERATIONS": 20 }
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

### Commit Mode (default)

For each commit reviewed, files are organized in a git-like directory structure:

```
output_dir/
├── ab/
│   └── abc123def456789.../
│       ├── review-inline.txt
│       ├── review-metadata.json
│       └── review-pre-verification.json  (optional, for SUSE verification)
└── cd/
    └── cdef456789abc123.../
        ├── review-inline.txt
        └── review-metadata.json
```

The directory path is `$OUTPUT_DIR/$ID1/$ID2/` where:
- `$ID1` = first 2 characters of commit SHA (e.g., "ab")
- `$ID2` = full commit SHA (e.g., "abc123def456789...")

**Resumability**: If a commit directory already exists, the review is skipped (allows resuming interrupted batch reviews). Use `--force` to override and re-review existing commits.

### Patch Mode (`--patch`)

For patch files, output is flat (no subdirectories):

```
output_dir/
├── review-inline.txt
└── review-metadata.json
```

**Differences from commit mode:**
- No commit SHA field in metadata (since there's no actual commit)
- No SUSE-commit field (SUSE verification skipped in patch mode)
- `upstream-commit` field included if `Git-commit:` tag found in patch
- Files written directly to output directory

### 1. `review-inline.txt`

LKML-compliant plain text report with:
- Commit metadata (SHA, author, subject)
- Summary of findings
- Review metadata (time, model)
- Quoted diff with inline comments
- Detailed analysis of each issue

Example:
```
commit abc123def456789
Author: Jane Developer <jane@example.com>

mm: fix use-after-free in page reclaim

This commit has a potential memory-leak that should be reviewed.

Review-time: 45.32 seconds

Review-model: gpt-4

> diff --git a/mm/vmscan.c b/mm/vmscan.c
> --- a/mm/vmscan.c
> +++ b/mm/vmscan.c
> @@ -1234,5 +1234,8 @@ static int shrink_page_list(...)
> +    folio = folio_alloc();
         ^
Can this leak the folio? The allocation is not freed in the error path
when the function returns early...
```

### 2. `review-metadata.json`

Structured JSON metadata:
```json
{
  "author": "Jane Developer <jane@example.com>",
  "sha": "abc123def456789",
  "subject": "mm: fix use-after-free in page reclaim",
  "issues-found": 1,
  "issue-severity-score": "medium",
  "issue-severity-explanation": "1 issue found that should be fixed",
  "review-time-seconds": 45.32,
  "model": "gpt-4"
}
```

**Fields:**
- `author`, `sha`, `subject`: Commit metadata
- `issues-found`: Number of potential issues found
- `issue-severity-score`: Severity level (`none`, `low`, `medium`, `high`, `urgent`)
- `issue-severity-explanation`: Human-readable severity description
- `review-time-seconds`: Time taken to complete the review (optional)
- `model`: LLM model name used for the review (optional)
- `suse-commit`: SUSE kernel-source commit SHA (optional, SUSE downstream only)
- `upstream-commit`: Upstream commit SHA (optional, if available)

### 3. `review-pre-verification.json` (optional)

Generated only when SUSE upstream verification is enabled and finds issues in both upstream and downstream code. Contains all findings before the false-positive verification step, with classification of which findings are present in upstream vs. downstream-only.

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

# Review multiple specific commits
python kernel_review_agent.py HEAD abc123 def456 --output-dir ./reviews/

# Review multiple ranges
python kernel_review_agent.py HEAD~5..HEAD~3 HEAD~1..HEAD --output-dir ./reviews/

# Review commits from a file
git log --pretty=oneline HEAD~50..HEAD > commits.txt
python kernel_review_agent.py --list commits.txt --output-dir ./reviews/

# Count issues found
grep -c "issues-found" ./reviews/*/*.json
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
    --output-dir "./reviews/$BRANCH"

# Check for high-severity issues
jq -r 'select(."issue-severity-score" == "high") | .sha' \
    "./reviews/$BRANCH"/*.json
```

**Using --list for large batches:**

```bash
#!/bin/bash
# review-batch.sh - Review large batches with resumability

BRANCH="downstream-6.8"
BASE="upstream"
REVIEWS_DIR="./reviews/$BRANCH"

# Generate commit list
git log --pretty=oneline "$BASE..$BRANCH" > commits.txt

# Review with --force to allow re-processing
python kernel_review_agent.py --list commits.txt \
    --host localhost \
    --port 11434 \
    --output-dir "$REVIEWS_DIR" \
    --force

# Generate report
echo "Review complete. Summary:"
echo "Total commits: $(wc -l < commits.txt)"
echo "High-severity: $(jq -r 'select(."issue-severity-score" == "high") | .sha' "$REVIEWS_DIR"/*/*.json | wc -l)"
echo "Medium-severity: $(jq -r 'select(."issue-severity-score" == "medium") | .sha' "$REVIEWS_DIR"/*/*.json | wc -l)"
```

## Configuration

The agent can be configured using JSON configuration files. Configuration is loaded in this order (later values override earlier ones):

1. **Hardcoded defaults** (in `config.py`)
2. **System-wide config**: `/etc/kernel-review-agent/config.json`
3. **User config**: `~/.config/kernel-review-agent/config.json`
4. **Command-line arguments** (highest priority)

### Quick Start - User Configuration

Create a user config file:

```bash
mkdir -p ~/.config/kernel-review-agent
cat > ~/.config/kernel-review-agent/config.json <<'EOF'
{
  "DEFAULT_HOST": "localhost",
  "DEFAULT_PORT": 11434,
  "DEFAULT_MODEL": "llama3.1",
  "LLM_TIMEOUT": 600
}
EOF
```

### Quick Start - System-Wide Configuration

Set defaults for all users:

```bash
sudo mkdir -p /etc/kernel-review-agent
sudo tee /etc/kernel-review-agent/config.json <<'EOF'
{
  "DEFAULT_HOST": "llm-server.company.local",
  "DEFAULT_PORT": 8080,
  "DEFAULT_MODEL": "gpt-4",
  "LLM_TIMEOUT": 300
}
EOF
```

### Available Configuration Options

All options are optional. See `config.json.example` for a complete template.

**LLM Settings:**
- `DEFAULT_HOST`: LLM server hostname (default: `"localhost"`)
- `DEFAULT_PORT`: LLM server port (default: `8080`)
- `DEFAULT_MODEL`: Model name (default: `"gpt-4"`)
- `DEFAULT_API_KEY`: API key (default: `"dummy"`)

**Token Limits:**
- `DEFAULT_MAX_TOKENS`: General token limit (default: `16000`)
- `CATEGORIZE_MAX_TOKENS`: Categorization tokens (default: `8000`)
- `ANALYZE_MAX_TOKENS`: Analysis tokens (default: `16000`)
- `VERIFY_MAX_TOKENS`: Verification tokens (default: `16000`)

**Timeouts:**
- `LLM_TIMEOUT`: Request timeout in seconds (default: `300`)
- `CONNECT_TIMEOUT`: Connection timeout in seconds (default: `10`)
- `REEVALUATION_TIME_THRESHOLD`: Re-run review if no issues found within this many seconds; `0` disables (default: `0`)

**Other:**
- `MAX_RETRIES`: Number of retries (default: `1`)
- `RETRY_DELAY`: Initial retry delay in seconds (default: `1.0`)
- `RETRY_BACKOFF`: Exponential backoff multiplier (default: `2.0`)

See [CONFIGURATION.md](CONFIGURATION.md) for complete documentation.

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

This project contains two separate MIT-licensed components:

**Agent Code** (Python modules and scripts):
- Licensed under the MIT License
- Copyright (c) 2026 Takashi Iwai
- See `LICENSE` file for full license text

**Review Prompts** (`prompts/` directory):
- Licensed under the MIT License
- Copyright (c) 2024 Chris Mason
- Maintained in the [review-prompts](https://github.com/masoncl/review-prompts) repository
- See `LICENSE-PROMPTS` file for full license text

## Credits

**Review Prompts**: The systematic kernel review protocols and subsystem guides used by this
agent are from the [review-prompts](https://github.com/masoncl/review-prompts) project
by [Chris Mason](https://github.com/masoncl), licensed under the MIT License.

**Agent Implementation**: Based on Linux kernel review best practices from the kernel community.
