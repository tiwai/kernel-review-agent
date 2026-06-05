#!/bin/bash
# Quick test on ALSA commit with actual findings
set -e

AGENT_DIR="/home/tiwai/tmp/claude-test9"
KERNEL_DIR="$HOME/kernel/suse/expand/kernel"
KERNEL_SOURCE="$HOME/kernel/suse/kernel-source"
UPSTREAM="$HOME/git/linus"

HOST="gpuserver"
PORT="8080"

# ALSA use-after-free commit (should have findings)
COMMIT="e83f70987391"

cd "$KERNEL_DIR"

echo "Testing commit: $COMMIT"
git show "$COMMIT" --stat | head -20
echo ""

mkdir -p "$AGENT_DIR/test-results"

echo "============================================================"
echo "Quick Test A: qwen3.5-9b with AUTO-SELECTED prompt set (small)"
echo "============================================================"
"$AGENT_DIR/kernel_review_agent.py" "$COMMIT" \
    --host "$HOST" --port "$PORT" \
    --model qwen3.5-9b \
    --suse-kernel-source "$KERNEL_SOURCE" \
    --upstream-linux "$UPSTREAM" \
    --output-dir "$AGENT_DIR/test-results/quick-a-small" \
    --verbose \
    --disable-tools \
    --force

echo ""
echo "============================================================"
echo "Quick Test B: qwen3.5-9b with FORCED default prompt set"
echo "============================================================"
"$AGENT_DIR/kernel_review_agent.py" "$COMMIT" \
    --host "$HOST" --port "$PORT" \
    --model qwen3.5-9b \
    --prompt-set default \
    --suse-kernel-source "$KERNEL_SOURCE" \
    --upstream-linux "$UPSTREAM" \
    --output-dir "$AGENT_DIR/test-results/quick-b-default" \
    --verbose \
    --disable-tools \
    --force

echo ""
echo "============================================================"
echo "Comparison"
echo "============================================================"
echo "Test A (small prompts):   $(find "$AGENT_DIR/test-results/quick-a-small" -name review-metadata.json -exec jq -r '.findings | length' {} \; 2>/dev/null || echo '?') findings"
echo "Test B (default prompts): $(find "$AGENT_DIR/test-results/quick-b-default" -name review-metadata.json -exec jq -r '.findings | length' {} \; 2>/dev/null || echo '?') findings"

echo ""
echo "Results in:"
echo "  test-results/quick-a-small/"
echo "  test-results/quick-b-default/"
