#!/usr/bin/env python3
"""
Linux Kernel Commit Review Agent

AI-powered agent for reviewing Linux kernel commits to detect potential regressions.
Focuses on code changes only, ignoring commit message quality and tags.
"""

import argparse
import sys
import os

# Add module directory to Python path for system-wide installation
# This allows the script to find modules when installed in /usr/bin
# while modules are in /usr/share/kernel-review-agent or /usr/local/share/kernel-review-agent
def setup_module_path():
    """Add module directories to sys.path for system-wide installation."""
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Check if modules are in the same directory (development/local install)
    if os.path.isfile(os.path.join(script_dir, 'config.py')):
        # Already in the right place, no need to modify path
        return

    # Check system-wide installation paths
    possible_paths = [
        '/usr/share/kernel-review-agent',
        '/usr/local/share/kernel-review-agent',
        os.path.expanduser('~/.local/share/kernel-review-agent'),
    ]

    for path in possible_paths:
        if os.path.isfile(os.path.join(path, 'config.py')):
            sys.path.insert(0, path)
            return

    # If we get here, modules are not found
    # Let the import fail naturally with a clear error

setup_module_path()

import config
from git_integration import CommitExtractor
from llm_integration import create_llm_client, get_provider_from_args
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
        "--provider",
        choices=["openai", "anthropic", "anthropic-vertex", "google", "ollama"],
        help="LLM provider (default: auto-detect from other options)"
    )

    # Provider-specific arguments
    parser.add_argument(
        "--anthropic-api-key",
        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)"
    )

    parser.add_argument(
        "--google-project",
        help="Google Cloud project ID (or set GOOGLE_CLOUD_PROJECT env var)"
    )

    parser.add_argument(
        "--google-location",
        default="us-central1",
        help="Google Cloud region (default: us-central1)"
    )

    parser.add_argument(
        "--google-credentials",
        help="Path to Google Cloud service account JSON key file (or set GOOGLE_APPLICATION_CREDENTIALS env var)"
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

    parser.add_argument(
        "--skip-verification",
        action="store_true",
        help="Skip false-positive verification step (faster but may report more issues)"
    )

    parser.add_argument(
        "--prompts-dir",
        default=config.DEFAULT_PROMPTS_DIR,
        help=f"Directory containing review prompts (default: {config.DEFAULT_PROMPTS_DIR})"
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
        print(f"[DEBUG]   Prompts directory: {args.prompts_dir}")
        print(f"[DEBUG]   LLM: {args.host}:{args.port}")
        print(f"[DEBUG]   Model: {args.model}")
        print(f"[DEBUG]   Verbose: {args.verbose}")
        print(f"[DEBUG]   Debug: {args.debug}")
        print(f"[DEBUG]   Dump prompts: {args.dump_prompts}")
        if args.dump_prompts:
            print(f"[DEBUG]   Dump directory: {args.dump_dir}")
        print(f"[DEBUG]   Skip verification: {args.skip_verification}")
        print(f"[DEBUG]   Output directory: {args.output_dir}")
        if args.upstream_branch:
            print(f"[DEBUG]   Upstream branch: {args.upstream_branch}")
        print()

    # Set Google credentials if specified
    if hasattr(args, 'google_credentials') and args.google_credentials:
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = args.google_credentials
        if args.debug:
            print(f"[DEBUG]   Google credentials file: {args.google_credentials}")

    # Determine provider
    provider = get_provider_from_args(args)
    if args.debug:
        print(f"[DEBUG]   Provider: {provider}")

    # Initialize components
    try:
        # Prepare provider-specific kwargs
        provider_kwargs = {
            'model': args.model,
            'verbose': args.verbose,
            'debug': args.debug,
            'dump_prompts': args.dump_prompts,
            'dump_dir': args.dump_dir,
        }

        if provider == 'openai':
            provider_kwargs.update({
                'host': args.host,
                'port': args.port,
                'api_key': args.api_key,
            })
        elif provider == 'ollama':
            provider_kwargs.update({
                'host': args.host,
                'port': args.port,
            })
        elif provider == 'anthropic':
            if args.anthropic_api_key:
                provider_kwargs['api_key'] = args.anthropic_api_key
        elif provider == 'anthropic-vertex':
            if args.google_project:
                provider_kwargs['project_id'] = args.google_project
            if args.google_location:
                provider_kwargs['location'] = args.google_location
        elif provider == 'google':
            if args.google_project:
                provider_kwargs['project_id'] = args.google_project
            if args.google_location:
                provider_kwargs['location'] = args.google_location

        llm = create_llm_client(provider=provider, **provider_kwargs)

    except Exception as e:
        print(f"Error: Failed to initialize {provider} LLM client", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        return 1

    # Verify prompts directory exists
    if not os.path.exists(args.prompts_dir):
        print(f"Error: Prompts directory not found: {args.prompts_dir}", file=sys.stderr)
        print(f"Tip: Use --prompts-dir option to specify the prompts directory", file=sys.stderr)
        return 1

    try:
        prompts = PromptLoader(prompts_dir=args.prompts_dir)
    except Exception as e:
        print(f"Error: Failed to initialize prompt loader", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        return 1

    matcher = SubsystemMatcher()
    workflow = ReviewWorkflow(
        llm,
        prompts,
        matcher,
        verbose=args.verbose,
        debug=args.debug,
        skip_verification=args.skip_verification
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
