#!/usr/bin/env python3
"""
Simple test to verify parallel processing infrastructure.
This test checks that:
1. Worker processes can be spawned
2. Queue communication works
3. Instance numbering works correctly
"""

import multiprocessing
import time
import sys
from datetime import datetime


def simple_worker(instance_id, work_queue, results_queue):
    """Simplified worker for testing."""
    print(f"[{instance_id}][{datetime.now().strftime('%H:%M:%S')}] Worker started")

    while True:
        try:
            item = work_queue.get(timeout=0.5)
            if item is None:  # Sentinel
                break

            # Simulate work
            time.sleep(0.1)

            results_queue.put({
                'instance': instance_id,
                'item': item,
                'status': 'done'
            })

        except:
            continue

    print(f"[{instance_id}][{datetime.now().strftime('%H:%M:%S')}] Worker finished")


def test_parallel():
    """Test parallel processing."""
    num_workers = 2
    num_items = 5

    print(f"Testing parallel processing with {num_workers} workers and {num_items} items\n")

    # Create queues
    work_queue = multiprocessing.Queue()
    results_queue = multiprocessing.Queue()

    # Populate work queue
    for i in range(num_items):
        work_queue.put(f"item-{i}")

    # Add sentinels
    for _ in range(num_workers):
        work_queue.put(None)

    # Start workers
    workers = []
    for i in range(num_workers):
        worker = multiprocessing.Process(
            target=simple_worker,
            args=(i + 1, work_queue, results_queue)
        )
        worker.start()
        workers.append(worker)

    # Collect results
    results = []
    while len(results) < num_items:
        try:
            result = results_queue.get(timeout=2.0)
            results.append(result)
            print(f"Got result from instance {result['instance']}: {result['item']}")
        except:
            break

    # Wait for workers
    for worker in workers:
        worker.join(timeout=2)

    print(f"\nCompleted: {len(results)}/{num_items} items")

    # Verify
    if len(results) == num_items:
        print("✓ Test passed!")
        return 0
    else:
        print("✗ Test failed!")
        return 1


if __name__ == '__main__':
    sys.exit(test_parallel())
