# Propose-Fixes Configuration

The `--propose-fixes` feature can now be configured via config files with command-line override support.

## Configuration

### User Config (~/.config/kernel-review-agent/config.json)

To enable fix patch proposals by default:

```json
{
  "PROPOSE_FIXES": true
}
```

To disable (default):

```json
{
  "PROPOSE_FIXES": false
}
```

### System-Wide Config (/etc/kernel-review-agent/config.json)

Same format as user config, but applies to all users.

## Command-Line Options

The command-line flags always override the configuration file setting:

### Enable fix proposals
```bash
python kernel_review_agent.py HEAD --propose-fixes
```

### Disable fix proposals (overrides config)
```bash
python kernel_review_agent.py HEAD --no-propose-fixes
```

### Use config default (no flag specified)
```bash
python kernel_review_agent.py HEAD
# Uses the PROPOSE_FIXES setting from config, or False if not configured
```

## Behavior

The priority order is:
1. **Command-line flags** (highest priority)
   - `--propose-fixes` → force enable
   - `--no-propose-fixes` → force disable
2. **Config file setting** (`PROPOSE_FIXES: true/false`)
3. **Hardcoded default** (`False`)

## Examples

### Example 1: Config disabled, no flag
```bash
# ~/.config/kernel-review-agent/config.json
{ "PROPOSE_FIXES": false }

# Command
python kernel_review_agent.py HEAD

# Result: propose_fixes = False
```

### Example 2: Config enabled, no flag
```bash
# ~/.config/kernel-review-agent/config.json
{ "PROPOSE_FIXES": true }

# Command
python kernel_review_agent.py HEAD

# Result: propose_fixes = True (patches will be generated)
```

### Example 3: Config enabled, but disabled via flag
```bash
# ~/.config/kernel-review-agent/config.json
{ "PROPOSE_FIXES": true }

# Command
python kernel_review_agent.py HEAD --no-propose-fixes

# Result: propose_fixes = False (config overridden)
```

### Example 4: Config disabled, but enabled via flag
```bash
# ~/.config/kernel-review-agent/config.json
{ "PROPOSE_FIXES": false }

# Command
python kernel_review_agent.py HEAD --propose-fixes

# Result: propose_fixes = True (config overridden)
```

## Testing

Run the test script to verify the logic:
```bash
python3 test-propose-fixes-config.py
```

All tests should pass with the expected behavior.
