# Quick Start Guide

## Prerequisites

1. **Python 3.8+** installed
2. **LLM Provider** - choose one:
   - **OpenAI-compatible server** (llama.cpp, vLLM, etc.)
   - **Ollama** - easiest for local use
   - **Anthropic Claude API** - requires API key
   - **Google Vertex AI** - requires GCP project
3. **Linux kernel git repository** 

## Installation

```bash
# Clone or extract to your preferred location
cd /path/to/kernel-review-agent

# Install core dependencies
pip install -r requirements.txt

# Optional: Install provider-specific dependencies
pip install anthropic                  # For Anthropic Claude API
pip install google-cloud-aiplatform    # For Google Vertex AI

# Optional: Add to PATH for convenience
export PATH="/path/to/kernel-review-agent:$PATH"
```

## Set Up Your LLM Provider

### Option 1: Ollama (Easiest for local use)
```bash
# Install Ollama from https://ollama.com
# Start Ollama server
ollama serve

# In another terminal, pull a model
ollama pull llama3.1
```

### Option 2: llama.cpp (OpenAI-compatible)
```bash
# Start llama.cpp server on port 8080
./llama-server --model /path/to/model.gguf --port 8080 --host localhost
```

### Option 3: Anthropic Claude API
```bash
# Set your API key
export ANTHROPIC_API_KEY=your-api-key-here
# Get your key from https://console.anthropic.com/
```

### Option 4: Google Vertex AI
```bash
# Set your project ID
export GOOGLE_CLOUD_PROJECT=your-project-id
# Authenticate
gcloud auth application-default login
```

## Run Your First Review

```bash
# Navigate to a Linux kernel git tree
cd /path/to/linux-kernel

# With Ollama (auto-detected on port 11434)
kernel_review_agent.py HEAD --port 11434 --model llama3.1 --verbose

# With llama.cpp / OpenAI-compatible server
kernel_review_agent.py HEAD --host localhost --port 8080 --model gpt-4 --verbose

# With Anthropic Claude API
kernel_review_agent.py HEAD --provider anthropic --model claude-3-5-sonnet-20241022 --verbose

# With Google Vertex AI
kernel_review_agent.py HEAD --provider google --model gemini-1.5-pro --verbose

# Or use full path if not in PATH
python /path/to/kernel-review-agent/kernel_review_agent.py HEAD --provider ollama --verbose
```

Expected output:
```
[1/5] Gathering context...
      Matched subsystems: mm-vma.md, locking.md

[2/5] Categorizing changes...
      Found 3 change categories

[3/5] Analyzing for regressions...
      Found 2 potential issues

[4/5] Verifying findings...
      1 issues after verification

[5/5] Generating summary...

Review complete: 1 issue(s) found

Commit abc123def456: mm: fix use-after-free in page reclaim
  Issues found: 1
  Severity: medium
  Report: review-inline-abc123def456.txt
  Metadata: review-metadata-abc123def456.json
```

## Check the Results

```bash
# View the plain text report
cat review-inline-abc123def456.txt

# View the JSON metadata
cat review-metadata-abc123def456.json
```

## Common Use Cases

### Review Last 5 Commits
```bash
kernel_review_agent.py HEAD~5..HEAD --output-dir ./reviews/ --verbose
```

### Review Specific Commit Range
```bash
kernel_review_agent.py v6.8..v6.9 --output-dir ./v6.9-reviews/
```

### Quick Scan (Skip Verification)
```bash
# Faster review by skipping false-positive verification
kernel_review_agent.py HEAD~10..HEAD --skip-verification
```

**Note**: If the agent is not in your PATH, use the full path:
```bash
/path/to/kernel-review-agent/kernel_review_agent.py HEAD --verbose
```

## Troubleshooting

### Error: "Must run in a git repository"
**Solution**: Navigate to a Linux kernel git tree before running

### Error: "Cannot connect to LLM API"
**Solution**: Ensure your LLM server is running:
```bash
# Test the connection
curl http://localhost:8080/v1/models
```

### No Issues Found on Obvious Bug
**Solution**: 
- Try a more capable model
- Increase `DEFAULT_MAX_TOKENS` in `config.py`
- Use `--verbose` to see what the LLM is analyzing

## Configuration

Edit `/path/to/kernel-review-agent/config.py` to change defaults:
```python
DEFAULT_HOST = "localhost"     # Your LLM server host
DEFAULT_PORT = 8080            # Your LLM server port
DEFAULT_MODEL = "gpt-4"        # Model name
DEFAULT_MAX_TOKENS = 8000      # Increase for longer responses
```

## Output Files

Each commit review produces:

1. **review-inline-<sha>.txt** - LKML-compliant plain text report
2. **review-metadata-<sha>.json** - Structured metadata with severity

The `<sha>` suffix (first 12 chars of commit SHA) prevents overwriting.

## Next Steps

- Read `README.md` for comprehensive documentation
- Check `IMPLEMENTATION_SUMMARY.md` for architecture details
- Review the `prompts/` directory to understand the review protocols
- Customize subsystem matching in `prompt_management/subsystem_matcher.py`
- Use custom prompts with `--prompts-dir /path/to/custom-prompts` if needed

## Tips for Best Results

1. **Use a capable model**: Larger models (7B+ parameters) work better
2. **Enable verbose mode**: See what the agent is doing with `--verbose`
3. **Review recent commits**: The agent works best on fresh, focused changes
4. **Check subsystem matching**: Verify relevant guides are loaded
5. **Iterate on findings**: Use the reports to improve code quality

## Support

- Check the code in the installation directory (`/path/to/kernel-review-agent/`)
- Review the kernel prompts in the `prompts/` directory
- Examine example outputs to understand the format
- Use `--debug` to see installation paths: `kernel_review_agent.py HEAD --debug`

## License and Credits

The kernel review prompts in `prompts/` are from the [review-prompts](https://github.com/masoncl/review-prompts) 
project by Chris Mason, licensed under the MIT License. See the LICENSE file for details.
