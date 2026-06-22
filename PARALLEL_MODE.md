# Parallel Processing Mode

The kernel review agent now supports parallel processing to speed up reviews of multiple commits by running multiple instances concurrently.

## Usage

```bash
# Run with 2 parallel instances (2x speed)
kernel_review_agent.py --list commits.txt --parallel 2 --output-dir ./reviews/

# Run with 4 parallel instances (4x speed)
kernel_review_agent.py HEAD~100..HEAD --parallel 4 --output-dir ./reviews/
```

## How It Works

With `--parallel NUM`:
- The agent spawns NUM worker processes
- Each worker processes commits independently from a shared queue
- Workers run concurrently on different commits
- Output is synchronized and reported as each commit completes

## Instance Identification

When using `--timestamps`, each log line is prefixed with both the instance number and timestamp:

```
[1][15:30:45] Processing commit abc123...
[2][15:30:46] Processing commit def456...
[1][15:31:02] ✓ [1/10] Commit abc123: Fix memory leak (ETA: 2m 15s)
[2][15:31:05] ✓ [2/10] Commit def456: Add new feature (ETA: 2m 10s)
```

This helps track which instance is processing which commit.

## Progress and ETA

In parallel mode with `--verbose`:
- Progress is shown as `[completed/total]` for each result
- ETA is calculated based on average review time divided by number of workers
- ETA accounts for parallelism (e.g., with 2 workers, ETA is half the sequential time)

Example output:
```
✓ [5/20] abc123def: Fix memory leak (ETA: 1m 30s)
  Issues found: 2
  Severity: low
  Report: ./reviews/ab/abc123.../review-inline.txt
```

## Host Reset Synchronization

When `--enable-host-reset` is used with parallel mode:

1. If any worker detects a fatal host error (connection failure, etc.), it signals all other workers
2. All workers are synchronized (wait for completion or timeout)
3. The host reset is performed once
4. All workers are restarted together
5. Failed commits are re-queued for processing

This ensures:
- No duplicate or conflicting reset attempts
- Clean state after reset
- No lost work during the reset process

## Performance Considerations

- **Small models**: Running 2-4 instances in parallel can utilize a GPU more efficiently
- **CPU-bound**: More instances may help if the bottleneck is CPU preprocessing
- **Memory**: Each instance requires its own memory for model inference
- **Disk I/O**: Output writing is synchronized, so many parallel writers may cause contention

## Recommended Settings

For small models (< 8B parameters) on a single GPU:
```bash
--parallel 2  # or --parallel 3 for very small models
```

For CPU-only inference:
```bash
--parallel <number of cores / 2>  # Leave headroom for system
```

## Limitations

- All instances use the same model (same --model, --host, --port)
- Progress reporting shows combined progress, not per-instance progress
- Some output may be interleaved if instances complete at similar times
- Host reset synchronization adds a small overhead if host errors occur

## Examples

### Review 100 commits in parallel
```bash
# Generate commit list
git log --pretty=oneline HEAD~100..HEAD > commits.txt

# Review with 3 parallel instances
kernel_review_agent.py --list commits.txt --parallel 3 \
  --host localhost --port 11434 \
  --model llama3.2:3b \
  --output-dir ./batch-review/ \
  --timestamps
```

### Review patch files in parallel
```bash
# Review multiple patch files with 2 instances
kernel_review_agent.py --patch *.patch --parallel 2 \
  --output-dir ./patch-reviews/
```

### With host reset enabled
```bash
# Parallel with automatic host reset on errors
kernel_review_agent.py --list commits.txt --parallel 2 \
  --enable-host-reset \
  --host-reset-max-attempts 3 \
  --output-dir ./reviews/
```
