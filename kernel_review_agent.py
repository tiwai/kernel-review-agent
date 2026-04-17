#!/usr/bin/env python3
"""
Linux Kernel Commit Review Agent

AI-powered agent for reviewing Linux kernel commits to detect potential regressions.
Focuses on code changes only, ignoring commit message quality and tags.
"""

import argparse
import sys
import os

import config
from git_integration import CommitExtractor
from llm_integration import OpenAIClient
from prompt_management import PromptLoader, SubsystemMatcher
from analysis import ReviewWorkflow
from output import ReportFormatter, MetadataGenerator


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="AI-powered Linux kernel commit reviewer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Review single commit
  %(prog)s abc123def --host localhost --port 11434

  # Review commit range
  %(prog)s HEAD~5..HEAD --host localhost --port 8080

  # Compare with upstream branch
  %(prog)s abc123def --upstream-branch upstream

  # Save to custom directory
  %(prog)s abc123def --output-dir ./reviews/
        """
    )

    parser.add_argument(
        "commit",
        help="Commit SHA or range (e.g., abc123, HEAD~5..HEAD)"
    )

    parser.add_argument(
        "--host",
        default=config.DEFAULT_HOST,
        help=f"OpenAI API host (default: {config.DEFAULT_HOST})"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=config.DEFAULT_PORT,
        help=f"OpenAI API port (default: {config.DEFAULT_PORT})"
    )

    parser.add_argument(
        "--api-key",
        default=config.DEFAULT_API_KEY,
        help="API key for authentication (default: dummy)"
    )

    parser.add_argument(
        "--model",
        default=config.DEFAULT_MODEL,
        help=f"Model name to use (default: {config.DEFAULT_MODEL})"
    )

    parser.add_argument(
        "--upstream-branch",
        help="Compare with upstream branch (e.g., upstream, origin/master)"
    )

    parser.add_argument(
        "--output-dir",
        default=config.DEFAULT_OUTPUT_DIR,
        help=f"Output directory for reports (default: {config.DEFAULT_OUTPUT_DIR})"
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output"
    )

    args = parser.parse_args()

    # Check if in git repository
    git = CommitExtractor(verbose=args.verbose)
    if not git.is_git_repo():
        print("Error: Must run in a git repository", file=sys.stderr)
        return 1

    # Initialize components
    try:
        llm = OpenAIClient(
            host=args.host,
            port=args.port,
            api_key=args.api_key,
            model=args.model,
            verbose=args.verbose
        )
    except Exception as e:
        print(f"Error: Failed to connect to LLM API at {args.host}:{args.port}", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        return 1

    prompts = PromptLoader()
    matcher = SubsystemMatcher()
    workflow = ReviewWorkflow(llm, prompts, matcher, verbose=args.verbose)
    formatter = ReportFormatter()
    metadata_gen = MetadataGenerator()

    # Expand commit range
    try:
        commits = git.expand_range(args.commit)
    except Exception as e:
        print(f"Error: Invalid commit or range: {args.commit}", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"Processing {len(commits)} commit(s)...\n")

    # Process each commit
    for commit_ref in commits:
        try:
            # Extract commit
            commit = git.get_commit(commit_ref, upstream_branch=args.upstream_branch)

            # Skip merge commits (too complex)
            if len(commit.diff.split('\n')) < 5 or "Merge:" in commit.message:
                if args.verbose:
                    print(f"Skipping merge commit {commit.sha[:12]}")
                continue

            # Execute review
            result = workflow.execute_review(commit)

            # Generate outputs
            report_text = formatter.format_report(
                commit,
                result.findings,
                summary=result.summary
            )
            metadata = metadata_gen.generate(commit, result.findings)

            # Save outputs with commit SHA suffix to avoid overwriting
            sha_short = commit.sha[:12]
            output_dir = args.output_dir

            # Create output directory if it doesn't exist
            if output_dir != "." and not os.path.exists(output_dir):
                os.makedirs(output_dir)

            report_path = os.path.join(output_dir, f"review-inline-{sha_short}.txt")
            metadata_path = os.path.join(output_dir, f"review-metadata-{sha_short}.json")

            with open(report_path, 'w') as f:
                f.write(report_text)

            metadata_gen.save_json(metadata, metadata_path)

            # Print summary
            print(f"Commit {sha_short}: {commit.subject}")
            print(f"  Issues found: {len(result.findings)}")
            print(f"  Severity: {metadata['issue-severity-score']}")
            print(f"  Report: {report_path}")
            print(f"  Metadata: {metadata_path}")
            print()

        except Exception as e:
            print(f"Error processing commit {commit_ref}: {e}", file=sys.stderr)
            if args.verbose:
                import traceback
                traceback.print_exc()
            continue

    return 0


if __name__ == "__main__":
    sys.exit(main())
