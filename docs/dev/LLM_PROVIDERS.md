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

**Option 1: User authentication (development)**
```bash
# Authenticate with your Google account
gcloud auth application-default login

# Set your project ID
export GOOGLE_CLOUD_PROJECT=your-project-id

# Ensure Vertex AI API is enabled
gcloud services enable aiplatform.googleapis.com
```

**Option 2: Service account (production/CI)**
```bash
# Create service account and download key
gcloud iam service-accounts create kernel-review-agent
gcloud iam service-accounts keys create key.json \
    --iam-account=kernel-review-agent@PROJECT_ID.iam.gserviceaccount.com

# Grant necessary permissions
gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="serviceAccount:kernel-review-agent@PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/aiplatform.user"

# Set credentials file
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
export GOOGLE_CLOUD_PROJECT=your-project-id
```

**Usage**:
```bash
# Method 1: Using environment variables
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json  # Optional
kernel_review_agent.py HEAD --provider google --model gemini-1.5-pro

# Method 2: Passing credentials via command line
kernel_review_agent.py HEAD --provider google \
    --google-project your-project-id \
    --google-credentials /path/to/key.json \
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

### 5. Claude on Google Vertex AI

**Use case**: Claude models deployed through Google Cloud infrastructure

**Why use this**: Get Claude's excellent code analysis with Google Cloud's enterprise features, unified billing with GCP, and potentially better latency if you're already in GCP.

**Installation**:
```bash
pip install 'anthropic[vertex]'
```

**Setup**:

**Option 1: User authentication (development)**
```bash
# Authenticate with your Google account
gcloud auth application-default login

# Set your project ID
export GOOGLE_CLOUD_PROJECT=your-project-id

# Ensure Vertex AI API is enabled and Claude models are accessible
gcloud services enable aiplatform.googleapis.com
```

**Option 2: Service account (production/CI)**
```bash
# Create service account and download key
gcloud iam service-accounts create kernel-review-agent
gcloud iam service-accounts keys create key.json \
    --iam-account=kernel-review-agent@PROJECT_ID.iam.gserviceaccount.com

# Grant necessary permissions for Claude on Vertex
gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="serviceAccount:kernel-review-agent@PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/aiplatform.user"

# Set credentials file
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
export GOOGLE_CLOUD_PROJECT=your-project-id
```

**Usage**:
```bash
# Method 1: Using environment variables
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json  # Optional
kernel_review_agent.py HEAD --provider anthropic-vertex --model claude-3-5-sonnet@20241022

# Method 2: Passing credentials via command line
kernel_review_agent.py HEAD --provider anthropic-vertex \
    --google-project your-project-id \
    --google-credentials /path/to/key.json \
    --google-location us-east5 \
    --model claude-3-5-sonnet@20241022
```

**Configuration**:
- `--google-project`: GCP project ID (or set `GOOGLE_CLOUD_PROJECT` env var)
- `--google-location`: GCP region (default: us-east5 for Claude)
- `--google-credentials`: Path to service account key JSON file (or set `GOOGLE_APPLICATION_CREDENTIALS` env var)
- `--model`: Model name

**Available models**:
- `claude-3-5-sonnet@20241022` - Latest Claude 3.5 Sonnet (recommended)
- `claude-3-opus@20240229` - Most powerful, slower
- `claude-3-sonnet@20240229` - Previous Sonnet version
- `claude-3-haiku@20240307` - Fastest, most economical

**Available regions for Claude on Vertex**:
- `us-east5` (default)
- `europe-west1`

**Note**: 
- Requires active GCP project with billing
- Claude models on Vertex AI may have different pricing than direct Anthropic API
- You must have access enabled for Claude models in your GCP project
- See Google Cloud Vertex AI pricing for Claude

**Benefits over direct Anthropic API**:
- Unified GCP billing and cost management
- VPC-SC (Service Controls) support for enterprise security
- Potentially lower latency if you're already in GCP
- Integration with other Google Cloud services

**Benefits over Gemini on Vertex**:
- Claude's superior code understanding and analysis
- More conversational and detailed responses
- Better at following complex instructions

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

**Best: Anthropic Claude API (direct)**
- Excellent code understanding
- Reliable performance
- No infrastructure management
- Simple API key authentication

**Alternative 1: Claude on Google Vertex AI**
- Same Claude quality with GCP enterprise features
- If already using GCP (unified billing)
- VPC-SC support for security compliance
- Potentially better latency in GCP regions

**Alternative 2: Google Vertex AI (Gemini)**
- If already using GCP
- Fast (Gemini Flash)
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

### Anthropic (Direct API)
- `ANTHROPIC_API_KEY` - Your Anthropic API key

### Claude on Vertex AI
- `GOOGLE_CLOUD_PROJECT` - Your GCP project ID
- `GOOGLE_APPLICATION_CREDENTIALS` - Path to service account key JSON file (optional, required for service account auth)

### Google Vertex AI (Gemini)
- `GOOGLE_CLOUD_PROJECT` - Your GCP project ID
- `GOOGLE_APPLICATION_CREDENTIALS` - Path to service account key JSON file (optional, required for service account auth)

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

**Google (Vertex AI - Gemini or Claude)**:
```bash
# Check authentication
gcloud auth application-default print-access-token

# Verify project
echo $GOOGLE_CLOUD_PROJECT

# If using service account, verify credentials file
echo $GOOGLE_APPLICATION_CREDENTIALS
ls -l $GOOGLE_APPLICATION_CREDENTIALS

# Or pass credentials file via command line
kernel_review_agent.py HEAD --provider google \
    --google-credentials /path/to/key.json \
    --google-project your-project-id
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
| Anthropic Sonnet (direct) | Fast | Excellent | $$ | Easy |
| Anthropic Opus (direct) | Slow | Best | $$$$ | Easy |
| Claude on Vertex Sonnet | Fast | Excellent | $$ | Hard |
| Claude on Vertex Opus | Slow | Best | $$$$ | Hard |
| Google Gemini Flash | Very Fast | Good | $ | Hard |
| Google Gemini Pro | Medium | Excellent | $$ | Hard |

**Notes**:
- Speed assumes adequate hardware for local models
- Quality refers to regression detection accuracy
- Cost is relative ($ = cheapest paid option, $$$$ = most expensive)
- Setup difficulty includes authentication, configuration, etc.
- Claude on Vertex has same quality as direct Anthropic API but requires GCP setup
