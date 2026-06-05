#!/bin/bash
set -e

AGENT_DIR="/home/tiwai/tmp/claude-test9"
KERNEL_DIR="$HOME/kernel/suse/expand/kernel"
KERNEL_SOURCE="$HOME/kernel/suse/kernel-source"
UPSTREAM="$HOME/git/linus"

HOST="gpuserver"
PORT="8080"

# Test commit - blk-rq-qos race condition fix
COMMIT="ff4bb95376b3"

cd "$KERNEL_DIR"

echo "============================================================"
echo "Test 1: Small model (qwen3) with auto-selected prompt set"
echo "============================================================"
"$AGENT_DIR/kernel_review_agent.py" "$COMMIT" \
    --host "$HOST" --port "$PORT" \
    --model qwen3 \
    --provider ollama \
    --suse-kernel-source "$KERNEL_SOURCE" \
    --upstream-linux "$UPSTREAM" \
    --output-dir "$AGENT_DIR/test-results/small-auto" \
    --verbose \
    --force

echo ""
echo "============================================================"
echo "Test 2: Larger model (qwen3.6:q4) with auto-selected prompt set"
echo "============================================================"
"$AGENT_DIR/kernel_review_agent.py" "$COMMIT" \
    --host "$HOST" --port "$PORT" \
    --model "qwen3.6:q4" \
    --provider ollama \
    --suse-kernel-source "$KERNEL_SOURCE" \
    --upstream-linux "$UPSTREAM" \
    --output-dir "$AGENT_DIR/test-results/large-auto" \
    --verbose \
    --force

echo ""
echo "============================================================"
echo "Test 3: Small model (qwen3) with FORCED default prompt set"
echo "============================================================"
"$AGENT_DIR/kernel_review_agent.py" "$COMMIT" \
    --host "$HOST" --port "$PORT" \
    --model qwen3 \
    --provider ollama \
    --prompt-set default \
    --suse-kernel-source "$KERNEL_SOURCE" \
    --upstream-linux "$UPSTREAM" \
    --output-dir "$AGENT_DIR/test-results/small-default" \
    --verbose \
    --force

echo ""
echo "============================================================"
echo "Comparison Summary"
echo "============================================================"

# Compare findings
echo "Test 1 (qwen3 + small):    $(grep -c '"type"' "$AGENT_DIR/test-results/small-auto/review.json" 2>/dev/null || echo 0) findings"
echo "Test 2 (qwen3.6 + default): $(grep -c '"type"' "$AGENT_DIR/test-results/large-auto/review.json" 2>/dev/null || echo 0) findings"
echo "Test 3 (qwen3 + default):   $(grep -c '"type"' "$AGENT_DIR/test-results/small-default/review.json" 2>/dev/null || echo 0) findings"

echo ""
echo "Detailed results in:"
echo "  - test-results/small-auto/"
echo "  - test-results/large-auto/"
echo "  - test-results/small-default/"
