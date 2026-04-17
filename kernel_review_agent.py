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

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output with detailed step information"
    )

    parser.add_argument(
        "--dump-prompts",
        action="store_true",
        help="Dump LLM prompts and responses to files for debugging"
    )

    parser.add_argument(
        "--dump-dir",
        default=config.DEBUG_DUMP_DIR,
        help=f"Directory for prompt/response dumps (default: {config.DEBUG_DUMP_DIR})"
    )

    args = parser.parse_args()

    # Check if in git repository
    git = CommitExtractor(verbose=args.verbose)
    if not git.is_git_repo():
        print("Error: Must run in a git repository", file=sys.stderr)
        return 1

    # Show debug info if enabled
    if args.debug:
        print(f"[DEBUG] Configuration:")
        print(f"[DEBUG]   Install directory: {config.INSTALL_DIR}")
        print(f"[DEBUG]   LLM: {args.host}:{args.port}")
        print(f"[DEBUG]   Model: {args.model}")
        print(f"[DEBUG]   Verbose: {args.verbose}")
        print(f"[DEBUG]   Debug: {args.debug}")
        print(f"[DEBUG]   Dump prompts: {args.dump_prompts}")
        if args.dump_prompts:
            print(f"[DEBUG]   Dump directory: {args.dump_dir}")
        print(f"[DEBUG]   Output directory: {args.output_dir}")
        if args.upstream_branch:
            print(f"[DEBUG]   Upstream branch: {args.upstream_branch}")
        print()

    # Initialize components
    try:
        llm = OpenAIClient(
            host=args.host,
            port=args.port,
            api_key=args.api_key,
            model=args.model,
            verbose=args.verbose,
            debug=args.debug,
            dump_prompts=args.dump_prompts,
            dump_dir=args.dump_dir
        )
    except Exception as e:
        print(f"Error: Failed to connect to LLM API at {args.host}:{args.port}", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        return 1

    prompts = PromptLoader()
    if args.debug:
        print(f"[DEBUG]   Prompts directory: {prompts.prompts_dir}")
        print()

    matcher = SubsystemMatcher()
    workflow = ReviewWorkflow(
        llm,
        prompts,
        matcher,
        verbose=args.verbose,
        debug=args.debug
    )
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

    # Track results
    successful = 0
    failed = 0
    skipped = 0

    # Process each commit
    for i, commit_ref in enumerate(commits, 1):
        try:
            # Extract commit
            commit = git.get_commit(commit_ref, upstream_branch=args.upstream_branch)

            # Skip merge commits (too complex)
            if len(commit.diff.split('\n')) < 5 or "Merge:" in commit.message:
                if args.verbose:
                    print(f"Skipping merge commit {commit.sha[:12]}")
                skipped += 1
                continue

            # Show progress for multiple commits
            if len(commits) > 1 and args.verbose:
                print(f"[{i}/{len(commits)}] Processing commit {commit.sha[:12]}...")

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
            print(f"✓ Commit {sha_short}: {commit.subject}")
            print(f"  Issues found: {len(result.findings)}")
            print(f"  Severity: {metadata['issue-severity-score']}")
            print(f"  Report: {report_path}")
            print(f"  Metadata: {metadata_path}")
            print()

            successful += 1

        except RuntimeError as e:
            # RuntimeError includes our timeout and connection errors
            error_msg = str(e)
            print(f"✗ Error processing commit {commit_ref}:", file=sys.stderr)
            print(f"  {error_msg}", file=sys.stderr)

            # For timeout errors, suggest solutions
            if "timed out" in error_msg.lower():
                print(f"  Suggestion: Increase LLM_TIMEOUT in config.py (current: {config.LLM_TIMEOUT}s)", file=sys.stderr)
            elif "connect" in error_msg.lower():
                print(f"  Suggestion: Ensure LLM server is running at {args.host}:{args.port}", file=sys.stderr)

            print(file=sys.stderr)

            if args.debug:
                import traceback
                traceback.print_exc()

            failed += 1

            # Continue with next commit
            if len(commits) > 1:
                print(f"Continuing with next commit...\n", file=sys.stderr)
            continue

        except Exception as e:
            print(f"✗ Unexpected error processing commit {commit_ref}: {e}", file=sys.stderr)
            if args.debug:
                import traceback
                traceback.print_exc()

            failed += 1

            # Continue with next commit
            if len(commits) > 1:
                print(f"Continuing with next commit...\n", file=sys.stderr)
            continue

    # Print final summary for multiple commits
    if len(commits) > 1:
        print("=" * 70)
        print(f"Summary: {len(commits)} total commits")
        print(f"  ✓ {successful} successful")
        if failed > 0:
            print(f"  ✗ {failed} failed")
        if skipped > 0:
            print(f"  ⊘ {skipped} skipped")
        print("=" * 70)

    # Return error code if all commits failed
    if successful == 0 and (failed > 0 or skipped == len(commits)):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
