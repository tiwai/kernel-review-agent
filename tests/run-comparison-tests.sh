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
echo "Test 1: Small model (qwen3) with auto prompt set (should select 'small')"
echo "=========================================="
mkdir -p /home/tiwai/tmp/claude-test9/test-comparison/test1-small-auto
cd /home/tiwai/tmp/claude-test9
python3 kernel_review_agent.py "$TEST_COMMIT" \
    --host "$HOST" --port "$PORT" \
    --model qwen3 \
    --output-dir test-comparison/test1-small-auto \
    --verbose \
    --skip-verification \
    --suse-kernel-source "$KERNEL_SOURCE" \
    --upstream-linux "$UPSTREAM" \
    2>&1 | tee test-comparison/test1-small-auto.log || true

echo ""
echo "=========================================="
echo "Test 2: Larger model (qwen3.6:q4) with auto prompt set (should select 'default')"
echo "=========================================="
mkdir -p /home/tiwai/tmp/claude-test9/test-comparison/test2-large-auto
cd /home/tiwai/tmp/claude-test9
python3 kernel_review_agent.py "$TEST_COMMIT" \
    --host "$HOST" --port "$PORT" \
    --model "qwen3.6:q4" \
    --output-dir test-comparison/test2-large-auto \
    --verbose \
    --skip-verification \
    --suse-kernel-source "$KERNEL_SOURCE" \
    --upstream-linux "$UPSTREAM" \
    2>&1 | tee test-comparison/test2-large-auto.log || true

echo ""
echo "=========================================="
echo "Test 3: Small model (qwen3) with forced 'default' prompt set"
echo "=========================================="
mkdir -p /home/tiwai/tmp/claude-test9/test-comparison/test3-small-default
cd /home/tiwai/tmp/claude-test9
python3 kernel_review_agent.py "$TEST_COMMIT" \
    --host "$HOST" --port "$PORT" \
    --model qwen3 \
    --prompt-set default \
    --output-dir test-comparison/test3-small-default \
    --verbose \
    --skip-verification \
    --suse-kernel-source "$KERNEL_SOURCE" \
    --upstream-linux "$UPSTREAM" \
    2>&1 | tee test-comparison/test3-small-default.log || true

echo ""
echo "=========================================="
echo "Test 4: Larger model (qwen3.6:q4) with forced 'small' prompt set"
echo "=========================================="
mkdir -p /home/tiwai/tmp/claude-test9/test-comparison/test4-large-small
cd /home/tiwai/tmp/claude-test9
python3 kernel_review_agent.py "$TEST_COMMIT" \
    --host "$HOST" --port "$PORT" \
    --model "qwen3.6:q4" \
    --prompt-set small \
    --output-dir test-comparison/test4-large-small \
    --verbose \
    --skip-verification \
    --suse-kernel-source "$KERNEL_SOURCE" \
    --upstream-linux "$UPSTREAM" \
    2>&1 | tee test-comparison/test4-large-small.log || true

echo ""
echo "=========================================="
echo "All tests complete!"
echo "=========================================="
