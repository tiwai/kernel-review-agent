# Configuration Guide

kernel-review-agent can be configured using JSON configuration files at the system or user level.

## Configuration Files

Configuration files are loaded in this order (later values override earlier ones):

1. **Hardcoded defaults** (in `config.py`)
2. **System-wide config**: `/etc/kernel-review-agent/config.json`
3. **User config**: `~/.config/kernel-review-agent/config.json`

All configuration files are **optional**. If a file doesn't exist, it's simply skipped.

## Configuration Locations

### System-Wide Configuration

Affects all users on the system:

```bash
/etc/kernel-review-agent/config.json
```

Or for non-root system installation:

```bash
/usr/local/etc/kernel-review-agent/config.json
```

**Use case:** Set organization-wide defaults (LLM server, model, timeouts)

### User Configuration

Affects only the current user (overrides system config):

```bash
~/.config/kernel-review-agent/config.json
```

**Use case:** Personal preferences, different API keys, custom timeouts

## Creating Configuration Files

### System-Wide Setup

```bash
# Copy example config
sudo mkdir -p /etc/kernel-review-agent
sudo cp config.json.example /etc/kernel-review-agent/config.json

# Edit with your settings
sudo vi /etc/kernel-review-agent/config.json
```

### User Setup

```bash
# Create user config directory
mkdir -p ~/.config/kernel-review-agent

# Copy and customize
cp config.json.example ~/.config/kernel-review-agent/config.json
vi ~/.config/kernel-review-agent/config.json
```

## Configuration Options

All values are optional. If not specified, hardcoded defaults are used.

### LLM API Settings

```json
{
  "DEFAULT_HOST": "localhost",
  "DEFAULT_PORT": 8080,
  "DEFAULT_API_KEY": "dummy",
  "DEFAULT_MODEL": "gpt-4"
}
```

- `DEFAULT_HOST`: LLM server hostname (default: `"localhost"`)
- `DEFAULT_PORT`: LLM server port (default: `8080`)
- `DEFAULT_API_KEY`: API key for authentication (default: `"dummy"`)
- `DEFAULT_MODEL`: Default model name (default: `"gpt-4"`)

### Token Limits

```json
{
  "DEFAULT_MAX_TOKENS": 16000,
  "CATEGORIZE_MAX_TOKENS": 8000,
  "ANALYZE_MAX_TOKENS": 16000,
  "VERIFY_MAX_TOKENS": 16000
}
```

- `DEFAULT_MAX_TOKENS`: General token limit (default: `16000`)
- `CATEGORIZE_MAX_TOKENS`: Tokens for categorization task (default: `8000`)
- `ANALYZE_MAX_TOKENS`: Tokens for analysis task (default: `16000`)
- `VERIFY_MAX_TOKENS`: Tokens for verification task (default: `16000`)

**Increase these if you get truncation warnings with large commits.**

### Temperature

```json
{
  "DEFAULT_TEMPERATURE": 0.1
}
```

- `DEFAULT_TEMPERATURE`: Sampling temperature (default: `0.1`)
  - Lower (0.0-0.3): More deterministic, consistent
  - Higher (0.5-1.0): More creative, varied

### Retry Configuration

```json
{
  "MAX_RETRIES": 3,
  "RETRY_DELAY": 1.0,
  "RETRY_BACKOFF": 2.0
}
```

- `MAX_RETRIES`: Number of retry attempts (default: `3`)
- `RETRY_DELAY`: Initial delay in seconds (default: `1.0`)
- `RETRY_BACKOFF`: Exponential backoff multiplier (default: `2.0`)

### Timeout Configuration

```json
{
  "LLM_TIMEOUT": 300,
  "CONNECT_TIMEOUT": 10
}
```

- `LLM_TIMEOUT`: LLM request timeout in seconds (default: `300` / 5 minutes)
- `CONNECT_TIMEOUT`: Connection timeout in seconds (default: `10`)

**Increase LLM_TIMEOUT if you get timeout errors with large commits.**

### Truncation Detection

```json
{
  "TRUNCATION_WARNING_THRESHOLD": 0.95
}
```

- `TRUNCATION_WARNING_THRESHOLD`: Warn when response uses this % of tokens (default: `0.95` / 95%)

### Output and Debug

```json
{
  "DEFAULT_OUTPUT_DIR": ".",
  "DEBUG_DUMP_DIR": "debug_dumps"
}
```

- `DEFAULT_OUTPUT_DIR`: Default output directory (default: `"."`)
- `DEBUG_DUMP_DIR`: Directory for debug dumps (default: `"debug_dumps"`)

## Example Configurations

### Example 1: Organization with Local LLM Server

**System config** (`/etc/kernel-review-agent/config.json`):
```json
{
  "DEFAULT_HOST": "llm-server.company.com",
  "DEFAULT_PORT": 8080,
  "DEFAULT_MODEL": "codellama-34b",
  "LLM_TIMEOUT": 600,
  "ANALYZE_MAX_TOKENS": 32000
}
```

All users will use the company LLM server by default.

### Example 2: User with Ollama

**User config** (`~/.config/kernel-review-agent/config.json`):
```json
{
  "DEFAULT_PORT": 11434,
  "DEFAULT_MODEL": "llama3.1:70b"
}
```

This user prefers Ollama on port 11434 instead of the system default.

### Example 3: User with Claude API

**User config**:
```json
{
  "DEFAULT_MODEL": "claude-3-5-sonnet-20241022"
}
```

Use with `--provider anthropic --anthropic-api-key $KEY`

### Example 4: High-Capacity Setup

**User config** (for reviewing very large commits):
```json
{
  "DEFAULT_MAX_TOKENS": 32000,
  "CATEGORIZE_MAX_TOKENS": 16000,
  "ANALYZE_MAX_TOKENS": 32000,
  "VERIFY_MAX_TOKENS": 32000,
  "LLM_TIMEOUT": 900
}
```

## Precedence and Overrides

Configuration values are applied in this order:

1. **Hardcoded defaults** (config.py)
2. **System config** (if exists)
3. **User config** (if exists) - **overrides system**
4. **Command-line arguments** - **overrides all**

### Example Precedence

**Hardcoded default:**
```python
DEFAULT_PORT = 8080
```

**System config:**
```json
{"DEFAULT_PORT": 11434}
```
→ Port is now `11434`

**User config:**
```json
{"DEFAULT_PORT": 9000}
```
→ Port is now `9000` (user overrides system)

**Command line:**
```bash
kernel-review-agent HEAD --port 8080
```
→ Port is `8080` (command-line overrides all)

## Validation

The agent will print a warning if a config file is found but can't be parsed:

```
Warning: Failed to load config file /etc/kernel-review-agent/config.json: Expecting value: line 5 column 1 (char 120)
```

Invalid config files are ignored and defaults are used.

## Checking Current Configuration

Use `--debug` to see which values are active:

```bash
kernel-review-agent HEAD --debug
```

Output shows:
```
[DEBUG] Configuration:
[DEBUG]   LLM: localhost:11434
[DEBUG]   Model: llama3.1:70b
...
```

## Best Practices

### System Configuration

Use for:
- Organization-wide LLM server settings
- Standard model selection
- Conservative timeout values
- Shared infrastructure defaults

### User Configuration

Use for:
- Personal API keys
- Preferred models
- Higher resource limits
- Development settings

### When to Use What

| Setting | System Config | User Config | Command-line |
|---------|---------------|-------------|--------------|
| Organization LLM server | ✓ | | |
| Personal API endpoints | | ✓ | |
| One-time test | | | ✓ |
| Department standard | ✓ | | |
| Your preferred model | | ✓ | |
| Quick experiment | | | ✓ |

## Troubleshooting

### Config file not loaded

Check file location:
```bash
ls -la /etc/kernel-review-agent/config.json
ls -la ~/.config/kernel-review-agent/config.json
```

### Invalid JSON syntax

Validate your JSON:
```bash
python3 -m json.tool ~/.config/kernel-review-agent/config.json
```

If valid, it will pretty-print the JSON. If invalid, it shows the error.

### Values not taking effect

Check precedence:
1. Command-line arguments override everything
2. User config overrides system config
3. System config overrides defaults

Use `--debug` to see active values.

### Permission denied

System config requires root:
```bash
sudo vi /etc/kernel-review-agent/config.json
```

User config is in your home directory (no root needed):
```bash
vi ~/.config/kernel-review-agent/config.json
```

## Example: Complete Setup

### 1. System Admin Sets Defaults

```bash
# Create system config
sudo mkdir -p /etc/kernel-review-agent
sudo tee /etc/kernel-review-agent/config.json <<EOF
{
  "DEFAULT_HOST": "llm.company.local",
  "DEFAULT_PORT": 8080,
  "DEFAULT_MODEL": "gpt-4",
  "LLM_TIMEOUT": 600
}
EOF
```

### 2. User Customizes

```bash
# Create user config
mkdir -p ~/.config/kernel-review-agent
cat > ~/.config/kernel-review-agent/config.json <<EOF
{
  "DEFAULT_PORT": 11434,
  "DEFAULT_MODEL": "llama3.1"
}
EOF
```

### 3. User Runs Agent

```bash
kernel-review-agent HEAD --verbose
```

**Result:**
- Host: `llm.company.local` (from system)
- Port: `11434` (user override)
- Model: `llama3.1` (user override)
- Timeout: `600` (from system)

Perfect! The configuration is flexible and hierarchical.
