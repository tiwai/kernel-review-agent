# LLM Provider Guide

The kernel-review-agent supports multiple LLM providers, allowing you to choose the best option for your use case.

## Supported Providers

### 1. OpenAI-Compatible Servers (Default)

**Use case**: Local LLM servers with OpenAI-compatible API

**Examples**: llama.cpp, vLLM, FastChat, LocalAI

**Installation**:
```bash
pip install -r requirements.txt  # Already includes openai package
```

**Usage**:
```bash
# Auto-detected when using custom host/port
kernel_review_agent.py HEAD --host localhost --port 8080 --model your-model

# Explicit provider selection
kernel_review_agent.py HEAD --provider openai --host localhost --port 8080
```

**Configuration**:
- `--host`: Server hostname (default: localhost)
- `--port`: Server port (default: 8080)
- `--api-key`: API key if required (default: "dummy")
- `--model`: Model name

---

### 2. Ollama

**Use case**: Easy local LLM deployment with simple setup

**Installation**:
```bash
# Install Ollama from https://ollama.com
# Python dependencies already included in requirements.txt
```

**Setup**:
```bash
# Start Ollama server (runs on port 11434 by default)
ollama serve

# Pull models
ollama pull llama3.1
ollama pull codellama
ollama pull mistral
```

**Usage**:
```bash
# Auto-detected when using port 11434
kernel_review_agent.py HEAD --port 11434 --model llama3.1

# Explicit provider selection
kernel_review_agent.py HEAD --provider ollama --model llama3.1
```

**Configuration**:
- `--host`: Ollama server host (default: localhost)
- `--port`: Ollama server port (default: 11434)
- `--model`: Model name (e.g., llama3.1, codellama, mistral)

**Recommended models**:
- `llama3.1:70b` - Best quality, requires significant resources
- `llama3.1:8b` - Good balance of quality and speed
- `codellama:13b` - Optimized for code understanding
- `mistral:7b` - Fast, good for quick scans

---

### 3. Anthropic Claude API

**Use case**: Cloud-based API with high-quality analysis, no local infrastructure needed

**Installation**:
```bash
pip install anthropic
```

**Setup**:
```bash
# Get API key from https://console.anthropic.com/
export ANTHROPIC_API_KEY=your-api-key-here
```

**Usage**:
```bash
# Using environment variable for API key
kernel_review_agent.py HEAD --provider anthropic --model claude-3-5-sonnet-20241022

# Passing API key directly
kernel_review_agent.py HEAD --provider anthropic --anthropic-api-key your-key
```

**Configuration**:
- `--anthropic-api-key`: API key (or set `ANTHROPIC_API_KEY` env var)
- `--model`: Model name

**Available models**:
- `claude-3-5-sonnet-20241022` - Latest, most capable (recommended)
- `claude-3-opus-20240229` - Most powerful, slower and more expensive
- `claude-3-sonnet-20240229` - Good balance
- `claude-3-haiku-20240307` - Fastest, most economical

**Note**: API calls are not free. See Anthropic pricing at https://anthropic.com/pricing

---

### 4. Google Vertex AI

**Use case**: Enterprise Google Cloud deployment with Gemini models

**Installation**:
```bash
pip install google-cloud-aiplatform
```

**Setup**:
```bash
# Authenticate with Google Cloud
gcloud auth application-default login

# Set your project ID
export GOOGLE_CLOUD_PROJECT=your-project-id

# Ensure Vertex AI API is enabled in your GCP project
gcloud services enable aiplatform.googleapis.com
```

**Usage**:
```bash
# Using environment variable for project ID
kernel_review_agent.py HEAD --provider google --model gemini-1.5-pro

# Passing project ID and location directly
kernel_review_agent.py HEAD --provider google \
    --google-project your-project-id \
    --google-location us-central1 \
    --model gemini-1.5-pro
```

**Configuration**:
- `--google-project`: GCP project ID (or set `GOOGLE_CLOUD_PROJECT` env var)
- `--google-location`: GCP region (default: us-central1)
- `--model`: Model name

**Available models**:
- `gemini-1.5-pro` - Most capable, large context window (recommended)
- `gemini-1.5-flash` - Fast, cost-effective
- `gemini-1.0-pro` - Previous generation

**Note**: Requires active GCP project and billing. See Google Cloud pricing.

---

## Choosing a Provider

### For Local Development

**Best: Ollama**
- Easiest to set up
- Good model selection
- No API costs
- Privacy (runs locally)

**Alternative: llama.cpp**
- More control over model selection
- Better performance tuning options
- Wider model format support

### For Production / CI/CD

**Best: Anthropic Claude API**
- Excellent code understanding
- Reliable performance
- No infrastructure management
- Pay-per-use pricing

**Alternative: Google Vertex AI**
- If already using GCP
- Enterprise support
- Good integration with other GCP services

### For Quick Testing

**Best: Ollama with small models**
```bash
ollama pull llama3.1:8b
kernel_review_agent.py HEAD --port 11434 --model llama3.1:8b --skip-verification
```

---

## Provider Auto-Detection

The agent automatically detects the provider based on command-line arguments:

1. If `--provider` is specified, uses that provider
2. If `--anthropic-api-key` is present, uses Anthropic
3. If `--google-project` is present, uses Google
4. If `--port 11434` is used, assumes Ollama
5. Otherwise, defaults to OpenAI-compatible

**Example**:
```bash
# These are equivalent (both auto-detect as Ollama):
kernel_review_agent.py HEAD --port 11434 --model llama3.1
kernel_review_agent.py HEAD --provider ollama --model llama3.1
```

---

## Environment Variables

### OpenAI-Compatible
- None required (uses `--host`, `--port`, `--api-key` arguments)

### Ollama
- None required (uses default localhost:11434)

### Anthropic
- `ANTHROPIC_API_KEY` - Your Anthropic API key

### Google Vertex AI
- `GOOGLE_CLOUD_PROJECT` - Your GCP project ID
- `GOOGLE_APPLICATION_CREDENTIALS` - Path to service account key (optional)

---

## Troubleshooting

### "Package not installed" error

```bash
# For Anthropic
pip install anthropic

# For Google
pip install google-cloud-aiplatform
```

### "Failed to connect" error

**OpenAI-compatible**:
```bash
# Verify server is running
curl http://localhost:8080/v1/models
```

**Ollama**:
```bash
# Start server if not running
ollama serve

# Verify
curl http://localhost:11434/api/tags
```

**Anthropic**:
```bash
# Check API key is set
echo $ANTHROPIC_API_KEY

# Verify key is valid
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01"
```

**Google**:
```bash
# Check authentication
gcloud auth application-default print-access-token

# Verify project
echo $GOOGLE_CLOUD_PROJECT
```

### Timeout errors

Increase timeout in `config.py`:
```python
LLM_TIMEOUT = 600  # Increase from 300 to 600 seconds
```

Or use `--skip-verification` for faster reviews:
```bash
kernel_review_agent.py HEAD --provider ollama --skip-verification
```

---

## Performance Comparison

| Provider | Speed | Quality | Cost | Setup Difficulty |
|----------|-------|---------|------|------------------|
| Ollama (8B) | Fast | Good | Free | Easy |
| Ollama (70B) | Slow | Excellent | Free | Medium |
| llama.cpp | Medium | Good | Free | Medium |
| Anthropic Sonnet | Fast | Excellent | $$ | Easy |
| Anthropic Opus | Slow | Best | $$$$ | Easy |
| Google Gemini Flash | Very Fast | Good | $ | Hard |
| Google Gemini Pro | Medium | Excellent | $$ | Hard |

**Notes**:
- Speed assumes adequate hardware for local models
- Quality refers to regression detection accuracy
- Cost is relative ($ = cheapest paid option, $$$$ = most expensive)
- Setup difficulty includes authentication, configuration, etc.
