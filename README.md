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
- The detailed patch description (with full explanation, upstream commit reference, etc.) is used for review
- This provides much richer context than the minimal downstream commit message

**Benefits:**
- More accurate analysis with complete problem description
- Upstream commit references automatically extracted
- Better understanding of the fix rationale
- No manual lookup of patch files needed

**Example:**
- Downstream commit: "Fix use after free (bsc#1259701)"
- Enhanced with patch description: Full explanation of the UAF issue, root cause, fix rationale, and upstream commit reference

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

### 2. `review-metadata.json`

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
