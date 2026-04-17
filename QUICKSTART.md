# Quick Start Guide

## Prerequisites

1. **Python 3.8+** installed
2. **OpenAI-compatible LLM server** running (e.g., llama.cpp, vLLM, Ollama)
3. **Linux kernel git repository** 

## Installation

```bash
cd /home/tiwai/tmp/claude-test9
pip install -r requirements.txt
```

## Start Your LLM Server

Example with llama.cpp:
```bash
# Terminal 1: Start LLM server on port 8080
./llama-server --model /path/to/model.gguf --port 8080 --host localhost
```

Example with Ollama:
```bash
# Terminal 1: Start Ollama (default port 11434)
ollama serve
ollama run llama3
```

## Run Your First Review

```bash
# Navigate to a Linux kernel git tree
cd /path/to/linux-kernel

# Review the most recent commit
python /home/tiwai/tmp/claude-test9/kernel_review_agent.py HEAD --host localhost --port 8080 --verbose
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
python kernel_review_agent.py HEAD~5..HEAD --output-dir ./reviews/ --verbose
```

### Compare with Upstream
```bash
python kernel_review_agent.py HEAD --upstream-branch upstream --verbose
```

### Review Specific Commit Range
```bash
python kernel_review_agent.py v6.8..v6.9 --output-dir ./v6.9-reviews/
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

Edit `config.py` to change defaults:
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
- Review `prompts/` directory to understand the review protocols
- Customize subsystem matching in `prompt_management/subsystem_matcher.py`

## Tips for Best Results

1. **Use a capable model**: Larger models (7B+ parameters) work better
2. **Enable verbose mode**: See what the agent is doing with `--verbose`
3. **Review recent commits**: The agent works best on fresh, focused changes
4. **Check subsystem matching**: Verify relevant guides are loaded
5. **Iterate on findings**: Use the reports to improve code quality

## Support

- Check the code in `/home/tiwai/tmp/claude-test9/`
- Review the kernel prompts in `prompts/` directory
- Examine example outputs to understand the format
