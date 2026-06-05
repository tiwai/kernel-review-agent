#!/bin/bash

set -e

KERNEL_DIR="$HOME/kernel/suse/expand/kernel"
KERNEL_SOURCE="$HOME/kernel/suse/kernel-source"
UPSTREAM="$HOME/git/linus"
TEST_COMMIT="e83f70987391"
HOST="gpuserver"
PORT="8080"

cd "$KERNEL_DIR"

echo "=========================================="
echo "Test 1: Small model (qwen3) - should auto-select 'small' prompt set"
echo "=========================================="
cd /home/tiwai/tmp/claude-test9
python3 kernel_review_agent.py "$TEST_COMMIT" \
    --host "$HOST" --port "$PORT" \
    --model qwen3 \
    --output-dir test-comparison/test1-small \
    --verbose \
    --skip-verification \
    --timeout 0 \
    2>&1 | tee test-comparison/test1.log

echo ""
echo "=========================================="
echo "Test 2: Larger model (qwen3.6:q4) - should auto-select 'default' prompt set"
echo "=========================================="
cd /home/tiwai/tmp/claude-test9
python3 kernel_review_agent.py "$TEST_COMMIT" \
    --host "$HOST" --port "$PORT" \
    --model "qwen3.6:q4" \
    --output-dir test-comparison/test2-large \
    --verbose \
    --skip-verification \
    --timeout 0 \
    2>&1 | tee test-comparison/test2.log

echo ""
echo "Tests complete! Results:"
echo "Test 1 (qwen3/small): test-comparison/test1-small/"
echo "Test 2 (qwen3.6:q4/default): test-comparison/test2-large/"
