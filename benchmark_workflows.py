#!/usr/bin/env python3
"""Benchmark hybrid vs full tool-calling workflows."""

import sys
import time
import json
import os
from typing import Dict, List

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from git_integration import CommitExtractor
from llm_integration import OpenAIClient, ToolEnabledClient
from prompt_management import PromptLoader, SubsystemMatcher
from analysis.workflow import ReviewWorkflow
from analysis.hybrid_workflow import HybridReviewWorkflow
from analysis.tool_workflow import ToolCallReviewWorkflow
import config


def benchmark_workflow(workflow, commit, label: str) -> Dict:
    """
    Benchmark a single workflow run.

    Returns:
        {
            'label': str,
            'duration': float (seconds),
            'findings_count': int,
            'summary': str
        }
    """
    start_time = time.time()

    try:
        result = workflow.execute_review(commit)
        end_time = time.time()

        duration = end_time - start_time

        return {
            'label': label,
            'duration': duration,
            'findings_count': len(result.findings),
            'summary': result.summary,
            'success': True
        }

    except Exception as e:
        end_time = time.time()
        duration = end_time - start_time

        return {
            'label': label,
            'duration': duration,
            'findings_count': 0,
            'summary': f"Error: {e}",
            'success': False
        }


def run_benchmark(commit_sha: str, runs: int = 3, host: str = None, port: int = None, model: str = None):
    """
    Run benchmark comparing workflows.

    Args:
        commit_sha: Commit to analyze
        runs: Number of runs per workflow
        host: LLM host (default: from config)
        port: LLM port (default: from config)
        model: Model name (default: from config)
    """
    # Use provided values or fall back to config
    llm_host = host or config.DEFAULT_HOST
    llm_port = port or config.DEFAULT_PORT
    llm_model = model or config.DEFAULT_MODEL

    print("="*70)
    print("Workflow Benchmark")
    print("="*70)
    print(f"Commit: {commit_sha}")
    print(f"Runs per workflow: {runs}")
    print(f"LLM: {llm_host}:{llm_port} / {llm_model}")
    print()

    # Get git directory
    git_dir = os.getcwd()
    if not os.path.exists(os.path.join(git_dir, '.git')):
        print("Error: Not in a git repository")
        sys.exit(1)

    # Extract commit
    print("Extracting commit...")
    extractor = CommitExtractor(verbose=False, debug=False)
    commit = extractor.get_commit(commit_sha)

    print(f"Subject: {commit.subject}")
    print(f"Files: {len(commit.files)}")
    print(f"Diff size: {len(commit.diff)} bytes")
    print()

    # Initialize components
    prompts = PromptLoader()
    matcher = SubsystemMatcher(prompts)

    # Results storage
    results = {
        'commit': commit_sha,
        'subject': commit.subject,
        'runs': runs,
        'standard': [],
        'hybrid': [],
        'tool_only': []
    }

    # ========================================================================
    # Benchmark 1: Standard workflow (pre-loaded context, no tools)
    # ========================================================================
    print("="*70)
    print("Benchmark 1: STANDARD WORKFLOW (Pre-loaded context)")
    print("="*70)

    standard_client = OpenAIClient(
        host=llm_host,
        port=llm_port,
        model=llm_model,
        verbose=False,
        debug=False
    )

    standard_workflow = ReviewWorkflow(
        standard_client,
        prompts,
        matcher,
        verbose=True,
        debug=False,
        skip_verification=False
    )

    for run in range(1, runs + 1):
        print(f"\n--- Run {run}/{runs} ---")
        result = benchmark_workflow(standard_workflow, commit, f"Standard-{run}")
        results['standard'].append(result)

        print(f"Duration: {result['duration']:.2f}s")
        print(f"Findings: {result['findings_count']}")

    # ========================================================================
    # Benchmark 2: Hybrid workflow (pre-loaded + tools)
    # ========================================================================
    print("\n" + "="*70)
    print("Benchmark 2: HYBRID WORKFLOW (Pre-loaded + Tools)")
    print("="*70)

    hybrid_client = ToolEnabledClient(
        git_dir=git_dir,
        host=llm_host,
        port=llm_port,
        model=llm_model,
        verbose=False,
        debug=False
    )

    hybrid_workflow = HybridReviewWorkflow(
        hybrid_client,
        prompts,
        matcher,
        verbose=True,
        debug=False,
        skip_verification=False,
        enable_tools=True
    )

    for run in range(1, runs + 1):
        print(f"\n--- Run {run}/{runs} ---")
        result = benchmark_workflow(hybrid_workflow, commit, f"Hybrid-{run}")
        results['hybrid'].append(result)

        print(f"Duration: {result['duration']:.2f}s")
        print(f"Findings: {result['findings_count']}")

    # ========================================================================
    # Benchmark 3: Tool-only workflow
    # ========================================================================
    print("\n" + "="*70)
    print("Benchmark 3: TOOL-ONLY WORKFLOW (No pre-loading)")
    print("="*70)

    tool_client = ToolEnabledClient(
        git_dir=git_dir,
        host=llm_host,
        port=llm_port,
        model=llm_model,
        verbose=False,
        debug=False
    )

    tool_workflow = ToolCallReviewWorkflow(
        tool_client,
        prompts,
        matcher,
        verbose=True,
        debug=False
    )

    for run in range(1, runs + 1):
        print(f"\n--- Run {run}/{runs} ---")
        result = benchmark_workflow(tool_workflow, commit, f"ToolOnly-{run}")
        results['tool_only'].append(result)

        print(f"Duration: {result['duration']:.2f}s")
        print(f"Findings: {result['findings_count']}")

    # ========================================================================
    # Summary
    # ========================================================================
    print("\n" + "="*70)
    print("BENCHMARK RESULTS")
    print("="*70)

    def calc_stats(runs: List[Dict]) -> Dict:
        """Calculate average, min, max."""
        durations = [r['duration'] for r in runs if r['success']]
        if not durations:
            return {'avg': 0, 'min': 0, 'max': 0, 'success_rate': 0}

        return {
            'avg': sum(durations) / len(durations),
            'min': min(durations),
            'max': max(durations),
            'success_rate': len(durations) / len(runs) * 100
        }

    standard_stats = calc_stats(results['standard'])
    hybrid_stats = calc_stats(results['hybrid'])
    tool_stats = calc_stats(results['tool_only'])

    print(f"\n{'Workflow':<20} {'Avg Time':<12} {'Min':<10} {'Max':<10} {'Success':<10}")
    print("-" * 70)
    print(f"{'Standard':<20} {standard_stats['avg']:>8.2f}s   {standard_stats['min']:>6.2f}s  {standard_stats['max']:>6.2f}s  {standard_stats['success_rate']:>6.1f}%")
    print(f"{'Hybrid':<20} {hybrid_stats['avg']:>8.2f}s   {hybrid_stats['min']:>6.2f}s  {hybrid_stats['max']:>6.2f}s  {hybrid_stats['success_rate']:>6.1f}%")
    print(f"{'Tool-Only':<20} {tool_stats['avg']:>8.2f}s   {tool_stats['min']:>6.2f}s  {tool_stats['max']:>6.2f}s  {tool_stats['success_rate']:>6.1f}%")

    print("\nComparison:")
    if hybrid_stats['avg'] > 0 and standard_stats['avg'] > 0:
        ratio = hybrid_stats['avg'] / standard_stats['avg']
        print(f"  Hybrid vs Standard: {ratio:.2f}x")
        if ratio > 2:
            print(f"    → Hybrid is {ratio:.1f}x SLOWER")
        elif ratio > 1.5:
            print(f"    → Hybrid is moderately slower")
        elif ratio < 0.9:
            print(f"    → Hybrid is FASTER")
        else:
            print(f"    → Similar performance")

    if tool_stats['avg'] > 0 and standard_stats['avg'] > 0:
        ratio = tool_stats['avg'] / standard_stats['avg']
        print(f"  Tool-Only vs Standard: {ratio:.2f}x")
        if ratio > 2:
            print(f"    → Tool-Only is {ratio:.1f}x SLOWER")
        elif ratio > 1.5:
            print(f"    → Tool-Only is moderately slower")
        elif ratio < 0.9:
            print(f"    → Tool-Only is FASTER")
        else:
            print(f"    → Similar performance")

    print("\nWinner:")
    times = [
        ('Standard', standard_stats['avg']),
        ('Hybrid', hybrid_stats['avg']),
        ('Tool-Only', tool_stats['avg'])
    ]
    times = [(name, t) for name, t in times if t > 0]
    times.sort(key=lambda x: x[1])

    if times:
        winner = times[0][0]
        winner_time = times[0][1]
        print(f"  🏆 {winner} ({winner_time:.2f}s average)")

    # Save results
    output_file = f"benchmark_results_{commit_sha[:12]}.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {output_file}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Benchmark workflow approaches")
    parser.add_argument("commit", help="Commit SHA to analyze")
    parser.add_argument("--runs", type=int, default=3, help="Number of runs per workflow (default: 3)")
    parser.add_argument("--host", help="LLM host (default: from config)")
    parser.add_argument("--port", type=int, help="LLM port (default: from config)")
    parser.add_argument("--model", help="Model name (default: from config)")

    args = parser.parse_args()

    run_benchmark(
        args.commit,
        runs=args.runs,
        host=args.host,
        port=args.port,
        model=args.model
    )


if __name__ == "__main__":
    main()
