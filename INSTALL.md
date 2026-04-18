# Installation Guide

kernel-review-agent can be installed in several ways depending on your needs.

## Quick Summary

| Method | Best For | Script Location | Prompts Location |
|--------|----------|-----------------|------------------|
| Development | Testing/development | Current directory | `./prompts/` |
| System-wide | All users | `/usr/bin/` | `/usr/share/kernel-review-agent/prompts/` |
| User install | Single user | `~/.local/bin/` | `~/.local/share/kernel-review-agent/prompts/` |
| pip install | Python users | Python scripts dir | Python package data |

## Method 1: Development / Local Use

Run directly from the source directory without installation:

```bash
cd /path/to/kernel-review-agent
pip install -r requirements.txt
python kernel_review_agent.py --help
```

**Pros:**
- No installation needed
- Easy to modify and test
- Works immediately

**Cons:**
- Must use full path or be in the directory
- Not available system-wide

## Method 2: System-Wide Installation (Recommended)

Install for all users using make:

```bash
cd /path/to/kernel-review-agent
pip install -r requirements.txt  # Install Python dependencies
sudo make install PREFIX=/usr
```

This installs:
- Script: `/usr/bin/kernel-review-agent`
- Modules: `/usr/share/kernel-review-agent/`
- Prompts: `/usr/share/kernel-review-agent/prompts/`
- Docs: `/usr/share/doc/kernel-review-agent/`

**Usage after installation:**
```bash
kernel-review-agent HEAD --verbose
# Works from any directory!
```

**Uninstall:**
```bash
sudo make uninstall PREFIX=/usr
```

## Method 3: User Installation (No Root Required)

Install for a single user:

```bash
cd /path/to/kernel-review-agent
pip install -r requirements.txt
make install PREFIX=~/.local
```

This installs:
- Script: `~/.local/bin/kernel-review-agent`
- Modules: `~/.local/share/kernel-review-agent/`
- Prompts: `~/.local/share/kernel-review-agent/prompts/`
- Docs: `~/.local/share/doc/kernel-review-agent/`

**Add to PATH:**
```bash
export PATH="$HOME/.local/bin:$PATH"
# Add to ~/.bashrc or ~/.zshrc to make permanent
```

**Uninstall:**
```bash
make uninstall PREFIX=~/.local
```

## Method 4: Python pip Installation

Install as a Python package:

```bash
cd /path/to/kernel-review-agent
pip install .

# Or for development (editable install):
pip install -e .
```

**Usage:**
```bash
kernel-review-agent --help
```

**Uninstall:**
```bash
pip uninstall kernel-review-agent
```

## Installation Paths

The agent automatically finds prompts in these locations (in order):

1. **Local development:** `./prompts/` (same directory as script)
2. **System-wide:** `/usr/share/kernel-review-agent/prompts/`
3. **User install:** `~/.local/share/kernel-review-agent/prompts/`
4. **Custom:** Use `--prompts-dir /path/to/prompts`

## Dependencies

### Required
- Python 3.8 or newer
- `openai` package (for OpenAI-compatible APIs and Ollama)

### Optional (for specific providers)
```bash
pip install anthropic                  # For Anthropic Claude API
pip install 'anthropic[vertex]'        # For Claude on Google Vertex AI
pip install google-cloud-aiplatform    # For Google Vertex AI (Gemini)
```

## Distribution Package Installation

For packaged distributions (RPM, DEB, etc.):

### RPM-based (Fedora, RHEL, openSUSE)
```bash
# Create RPM from tarball
sudo rpmbuild -ta kernel-review-agent-0.1.tar.gz
sudo rpm -ivh kernel-review-agent-0.1.rpm
```

### DEB-based (Debian, Ubuntu)
```bash
# Using alien to convert RPM, or create native DEB
sudo dpkg -i kernel-review-agent_0.1_all.deb
```

## Verification

After installation, verify it works:

```bash
# Check the script is found
which kernel-review-agent

# Check help works
kernel-review-agent --help

# Check prompts are found (with --debug)
cd /tmp
kernel-review-agent --help 2>&1 | grep -q "usage:"
```

## Troubleshooting

### "command not found: kernel-review-agent"

**System-wide install:**
- Check `/usr/bin/kernel-review-agent` exists
- May need to log out and back in

**User install:**
- Check `~/.local/bin/kernel-review-agent` exists
- Add to PATH: `export PATH="$HOME/.local/bin:$PATH"`

### "ModuleNotFoundError: No module named 'config'"

The Python modules aren't in the search path.

**Check installation:**
```bash
# System-wide
ls -la /usr/share/kernel-review-agent/config.py

# User install
ls -la ~/.local/share/kernel-review-agent/config.py
```

**If missing, reinstall:**
```bash
sudo make install PREFIX=/usr
# or
make install PREFIX=~/.local
```

### "Error: Prompts directory not found"

The prompts aren't installed correctly.

**Check prompts:**
```bash
# System-wide
ls -la /usr/share/kernel-review-agent/prompts/

# User install
ls -la ~/.local/share/kernel-review-agent/prompts/
```

**If missing, reinstall:**
```bash
sudo make install-prompts PREFIX=/usr
# or
make install-prompts PREFIX=~/.local
```

**Or specify manually:**
```bash
kernel-review-agent HEAD --prompts-dir /path/to/prompts
```

## Upgrading

### From previous version

**System-wide:**
```bash
sudo make uninstall PREFIX=/usr
cd /path/to/new-version
sudo make install PREFIX=/usr
```

**User install:**
```bash
make uninstall PREFIX=~/.local
cd /path/to/new-version
make install PREFIX=~/.local
```

**pip install:**
```bash
pip install --upgrade .
```

## Custom Prefix

Install to a custom location:

```bash
make install PREFIX=/opt/kernel-review-agent
export PATH="/opt/kernel-review-agent/bin:$PATH"
```

Files will be in:
- Script: `/opt/kernel-review-agent/bin/kernel-review-agent`
- Modules: `/opt/kernel-review-agent/share/kernel-review-agent/`
- Prompts: `/opt/kernel-review-agent/share/kernel-review-agent/prompts/`

## Next Steps

After installation, see:
- [QUICKSTART.md](QUICKSTART.md) - Quick start guide
- [README.md](README.md) - Full documentation
- [LLM_PROVIDERS.md](LLM_PROVIDERS.md) - LLM provider setup

## Getting Help

```bash
# Show help
kernel-review-agent --help

# Show installation paths with debug
kernel-review-agent --help --debug
```
