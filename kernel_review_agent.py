#!/usr/bin/env python3
"""
Linux Kernel Commit Review Agent

AI-powered agent for reviewing Linux kernel commits to detect potential regressions.
Focuses on code changes only, ignoring commit message quality and tags.
"""

import argparse
import sys
import os
import time
from datetime import datetime


class TimestampedStream:
    """Wraps a stream and prepends HH:MM:SS to every line."""

    def __init__(self, stream):
        self._stream = stream
        self._at_line_start = True

    def write(self, data):
        if not data:
            return
        output = []
        for ch in data:
            if self._at_line_start and ch != '\n':
                output.append(datetime.now().strftime('[%H:%M:%S] '))
                self._at_line_start = False
            output.append(ch)
            if ch == '\n':
                self._at_line_start = True
        self._stream.write(''.join(output))

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)

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
from git_integration import CommitExtractor, MultiRepoExtractor
from llm_integration import create_llm_client, get_provider_from_args, ToolEnabledClient
from prompt_management import PromptLoader, SubsystemMatcher
from analysis import ReviewWorkflow, HybridReviewWorkflow
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

  # Review multiple commits
  %(prog)s HEAD abc123 def456 --output-dir ./reviews/

  # Review multiple ranges
  %(prog)s HEAD~5..HEAD~3 HEAD~1..HEAD --output-dir ./reviews/

  # Review commits from a list file
  %(prog)s --list commits.txt --output-dir ./reviews/

  # Generate list with: git log --pretty=oneline > commits.txt
  # List format: one commit per line, first column is commit ID

  # Review patch file
  %(prog)s --patch my-changes.patch --output-dir ./reviews/

  # Review multiple patches
  %(prog)s --patch patch1.patch patch2.patch --output-dir ./reviews/
        """
    )

    parser.add_argument(
        "commit",
        nargs='*',
        help="Commit SHA(s), range(s), or patch file(s) (e.g., abc123, HEAD~5..HEAD, or with --patch: file.patch)"
    )

    parser.add_argument(
        "--patch",
        action="store_true",
        help="Treat arguments as patch files instead of commit references"
    )

    parser.add_argument(
        "--list",
        metavar="FILE",
        help="Read commit IDs from file (one per line, first column only, like 'git log --pretty=oneline')"
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
        "--output-dir",
        default=config.DEFAULT_OUTPUT_DIR,
        help=f"Output directory for reports (default: {config.DEFAULT_OUTPUT_DIR})"
    )

    parser.add_argument(
        "--max-tokens",
        type=int,
        help="Override maximum output tokens for all LLM calls (default: task-specific limits)"
    )

    parser.add_argument(
        "--timeout",
        type=int,
        help="LLM request timeout in seconds (0 = no timeout, default: 300)"
    )

    parser.add_argument(
        "--reevaluate-threshold",
        type=int,
        default=config.REEVALUATION_TIME_THRESHOLD,
        metavar="SECONDS",
        help="Re-run review if no issues found within this many seconds (0 = disabled, default: disabled)"
    )

    parser.add_argument(
        "--reasoning-effort",
        choices=["low", "medium", "high"],
        default=None,
        help="Reasoning effort for models that support it, e.g. gpt-oss (low/medium/high)"
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
        "--propose-fixes",
        action="store_true",
        help="Ask the LLM to propose fix patches for each identified issue (written to review-fix-patches.diff)"
    )

    parser.add_argument(
        "--max-tool-iterations",
        type=int,
        default=config.MAX_TOOL_ITERATIONS,
        metavar="N",
        help=f"Maximum number of tool-call iterations per step (default: {config.MAX_TOOL_ITERATIONS})"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-review even if output directory already exists for the commit"
    )

    parser.add_argument(
        "--prompts-dir",
        default=config.DEFAULT_PROMPTS_DIR,
        help=f"Directory containing review prompts (default: {config.DEFAULT_PROMPTS_DIR})"
    )

    parser.add_argument(
        "--suse-kernel-source",
        help="Path to SUSE kernel-source git repository (enables SUSE upstream verification)"
    )

    parser.add_argument(
        "--upstream-linux",
        help="Path to upstream Linux kernel git repository (optional, for SUSE verification)"
    )

    parser.add_argument(
        "--enable-tools",
        action="store_true",
        default=True,
        help="Enable hybrid mode with tool calling for enhanced verification (default: enabled for OpenAI-compatible providers)"
    )

    parser.add_argument(
        "--disable-tools",
        action="store_true",
        help="Disable tool calling and use standard pre-loaded context only"
    )

    parser.add_argument(
        "--log-file",
        metavar="FILE",
        help="Write output to FILE instead of stdout"
    )

    parser.add_argument(
        "--timestamps",
        action="store_true",
        default=config.TIMESTAMPS,
        help="Prefix each output line with a timestamp (HH:MM:SS)"
    )

    args = parser.parse_args()

    # Redirect stdout and stderr to log file if requested
    if args.log_file:
        try:
            log = open(args.log_file, 'w', buffering=1)
            sys.stdout = log
            sys.stderr = log
        except OSError as e:
            print(f"Error: Cannot open log file {args.log_file}: {e}", file=sys.stderr)
            return 1

    # Wrap streams with timestamp prefixer if requested
    if args.timestamps:
        sys.stdout = TimestampedStream(sys.stdout)
        sys.stderr = TimestampedStream(sys.stderr)

    # Handle --disable-tools flag (overrides default)
    if args.disable_tools:
        args.enable_tools = False

    # Handle --list flag: read commit IDs from file
    if args.list:
        if not os.path.exists(args.list):
            print(f"Error: List file not found: {args.list}", file=sys.stderr)
            return 1

        try:
            with open(args.list, 'r') as f:
                # Read commit IDs from first column (space/tab separated)
                commits_from_file = []
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        # Skip empty lines and comments
                        continue

                    # Extract first column (commit ID)
                    parts = line.split(None, 1)  # Split on whitespace, max 1 split
                    if parts:
                        commit_id = parts[0]
                        commits_from_file.append(commit_id)

                if not commits_from_file:
                    print(f"Error: No commit IDs found in {args.list}", file=sys.stderr)
                    return 1

                # Add to args.commit (combine with command-line commits if any)
                if args.commit:
                    args.commit.extend(commits_from_file)
                else:
                    args.commit = commits_from_file

                if args.verbose:
                    print(f"Loaded {len(commits_from_file)} commit(s) from {args.list}")

        except IOError as e:
            print(f"Error: Failed to read list file {args.list}: {e}", file=sys.stderr)
            return 1

    # Check if we have commits to process
    if not args.commit:
        print("Error: No commits specified. Provide commit SHA(s), ranges, or use --list FILE", file=sys.stderr)
        return 1

    # Check if in git repository (temporary extractor for check)
    temp_git = CommitExtractor(verbose=args.verbose)
    if not temp_git.is_git_repo():
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
        print()

    # Override token limits if --max-tokens specified
    if args.max_tokens:
        config.DEFAULT_MAX_TOKENS = args.max_tokens
        config.CATEGORIZE_MAX_TOKENS = args.max_tokens
        config.ANALYZE_MAX_TOKENS = args.max_tokens
        config.VERIFY_MAX_TOKENS = args.max_tokens

        if args.debug:
            print(f"[DEBUG] Token limits overridden to: {args.max_tokens}")
            print()

    # Override timeout if --timeout specified
    if args.timeout is not None:
        if args.timeout == 0:
            config.LLM_TIMEOUT = None  # Disable timeout
        else:
            config.LLM_TIMEOUT = args.timeout

        if args.debug:
            timeout_str = "disabled" if config.LLM_TIMEOUT is None else f"{config.LLM_TIMEOUT}s"
            print(f"[DEBUG] LLM timeout: {timeout_str}")
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
            if args.reasoning_effort:
                provider_kwargs['reasoning_effort'] = args.reasoning_effort
        elif provider == 'ollama':
            provider_kwargs.update({
                'host': args.host,
                'port': args.port,
            })
            if args.reasoning_effort:
                provider_kwargs['reasoning_effort'] = args.reasoning_effort
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

    # Initialize kernel-source extractor for commit message enhancement
    kernel_source_extractor = None
    suse_kernel_source = args.suse_kernel_source or config.SUSE_KERNEL_SOURCE_REPO

    if suse_kernel_source and not args.patch:
        kernel_source_extractor = MultiRepoExtractor(
            repo_path=suse_kernel_source,
            verbose=args.verbose,
            debug=args.debug
        )

        if kernel_source_extractor.is_available():
            if args.verbose:
                print(f"Kernel-source commit message enhancement enabled")
        else:
            if args.debug:
                print(f"[DEBUG] Kernel-source repository not available: {suse_kernel_source}")
            kernel_source_extractor = None

    # Initialize git commit extractor with kernel-source enhancement
    git = CommitExtractor(
        verbose=args.verbose,
        debug=args.debug,
        kernel_source_extractor=kernel_source_extractor
    )

    # Initialize SUSE verifier if configured (skip in patch mode)
    suse_verifier = None
    upstream_repo_extractor = None
    if not args.patch:
        upstream_linux = args.upstream_linux or config.UPSTREAM_LINUX_REPO

        # Create upstream repository extractor for backport verification
        if upstream_linux:
            upstream_repo_extractor = MultiRepoExtractor(
                repo_path=upstream_linux,
                verbose=args.verbose,
                debug=args.debug
            )

            if upstream_repo_extractor.is_available():
                if args.verbose:
                    print(f"Upstream Linux repository available for backport verification")
                if args.debug:
                    print(f"[DEBUG] Upstream repo: {upstream_linux}")
            else:
                if args.debug:
                    print(f"[DEBUG] Upstream Linux repository not available: {upstream_linux}")
                upstream_repo_extractor = None

        if suse_kernel_source:
            if args.debug:
                print(f"[DEBUG] Initializing SUSE verifier")
                print(f"[DEBUG]   kernel-source: {suse_kernel_source}")
                print(f"[DEBUG]   upstream: {upstream_linux}")

            from analysis import SuseUpstreamVerifier
            suse_verifier = SuseUpstreamVerifier(
                kernel_source_repo=suse_kernel_source,
                upstream_repo=upstream_linux,
                verbose=args.verbose,
                debug=args.debug
            )

            if not suse_verifier.is_enabled():
                print(f"Warning: SUSE kernel-source repository not available: {suse_kernel_source}",
                      file=sys.stderr)
                suse_verifier = None
            elif args.verbose:
                print(f"SUSE upstream verification enabled")

    # Create workflow (hybrid with tools or standard)
    if args.enable_tools:
        # Hybrid mode: pre-loaded context + tool calling (default)
        if provider not in ['openai', 'ollama']:
            if args.verbose or args.debug:
                print(f"Note: Tool calling only supported for OpenAI-compatible providers", file=sys.stderr)
                print(f"      Using standard workflow for {provider}", file=sys.stderr)
            args.enable_tools = False
        else:
            if args.verbose:
                print("Using hybrid mode: Pre-loaded context + tool calling for enhanced verification")
            if args.debug:
                print("[DEBUG] Hybrid mode: Tool calling enabled for deep-dive verification\n")

            # Replace LLM client with tool-enabled version
            git_dir = os.getcwd()
            llm = ToolEnabledClient(
                git_dir=git_dir,
                host=args.host,
                port=args.port,
                api_key=args.api_key,
                model=args.model,
                verbose=args.verbose,
                debug=args.debug,
                dump_prompts=args.dump_prompts,
                dump_dir=args.dump_dir,
                reasoning_effort=args.reasoning_effort or None
            )

            workflow = HybridReviewWorkflow(
                llm,
                prompts,
                matcher,
                verbose=args.verbose,
                debug=args.debug,
                skip_verification=args.skip_verification,
                suse_verifier=suse_verifier,
                enable_tools=True,
                upstream_repo=upstream_repo_extractor,
                propose_fixes=args.propose_fixes,
                max_tool_iterations=args.max_tool_iterations
            )

    if not args.enable_tools:
        # Standard workflow (pre-loaded context only)
        if args.verbose and args.disable_tools:
            print("Using standard mode: Pre-loaded context only (tool calling disabled)")
        elif args.verbose:
            print("Using standard mode: Pre-loaded context only")

        workflow = ReviewWorkflow(
            llm,
            prompts,
            matcher,
            verbose=args.verbose,
            debug=args.debug,
            skip_verification=args.skip_verification,
            suse_verifier=suse_verifier,
            propose_fixes=args.propose_fixes,
            max_tool_iterations=args.max_tool_iterations
        )
    formatter = ReportFormatter()
    metadata_gen = MetadataGenerator()

    # Process arguments: either patch files or commit references
    if args.patch:
        # Patch mode: arguments are patch files
        items_to_process = args.commit
        total_items = len(items_to_process)
        if args.verbose:
            print(f"Processing {total_items} patch file(s)...\n")
    else:
        # Commit mode: expand all commit arguments
        commits = []
        for commit_arg in args.commit:
            try:
                expanded = git.expand_range(commit_arg)
                commits.extend(expanded)
            except Exception as e:
                print(f"Error: Invalid commit or range: {commit_arg}", file=sys.stderr)
                print(f"Details: {e}", file=sys.stderr)
                return 1

        items_to_process = commits
        total_items = len(commits)
        if args.verbose:
            print(f"Processing {total_items} commit(s)...\n")

    # Track results
    successful = 0
    failed = 0
    skipped = 0
    failed_items = []  # Track failed commits/patches for summary

    # Patch mode: process patch files
    if args.patch:
        for i, patch_file in enumerate(items_to_process, 1):
            try:
                # Parse patch file
                if not os.path.exists(patch_file):
                    print(f"Error: Patch file not found: {patch_file}", file=sys.stderr)
                    failed += 1
                    failed_items.append(patch_file)
                    continue

                if args.verbose:
                    print(f"[{i}/{total_items}] Processing patch {patch_file}...")

                commit = git.from_patch_file(patch_file)

                # Execute review with timing
                start_time = time.time()
                result = workflow.execute_review(commit)
                elapsed_time = time.time() - start_time

                if args.debug:
                    print(f"[DEBUG] Review completed in {elapsed_time:.2f} seconds")

                # Re-evaluate if no issues found and review completed suspiciously fast
                if args.reevaluate_threshold > 0 and len(result.findings) == 0 and elapsed_time < args.reevaluate_threshold:
                    if args.verbose:
                        print(f"  No issues found in {elapsed_time:.1f}s — re-evaluating...")
                    reeval_start = time.time()
                    result2 = workflow.execute_review(commit)
                    reeval_elapsed = time.time() - reeval_start
                    if len(result2.findings) > 0:
                        if args.verbose:
                            print(f"  Re-evaluation found {len(result2.findings)} issue(s) — using re-evaluation result")
                        result = result2
                        elapsed_time = reeval_elapsed
                    elif args.verbose:
                        print(f"  Re-evaluation confirmed: no issues found")

                # Create output directory if needed
                if args.output_dir != "." and not os.path.exists(args.output_dir):
                    os.makedirs(args.output_dir)

                # Clean up old review files in patch mode (always overwrite)
                # (do this AFTER review succeeds but BEFORE writing new files)
                old_files = [
                    os.path.join(args.output_dir, "review-metadata.json"),
                    os.path.join(args.output_dir, "review-inline.txt"),
                    os.path.join(args.output_dir, "review-fix-patches.diff"),
                ]
                for old_file in old_files:
                    if os.path.exists(old_file):
                        os.remove(old_file)
                        if args.debug:
                            print(f"[DEBUG] Removed stale file: {old_file}")

                # Generate outputs
                report_text = formatter.format_report(
                    commit,
                    result.findings,
                    summary=result.summary,
                    suse_verification=result.suse_verification,
                    elapsed_time=elapsed_time,
                    is_patch=True,  # Flag for patch mode formatting
                    model_name=args.model
                )
                metadata = metadata_gen.generate(commit, result.findings, elapsed_time=elapsed_time, is_patch=True, model_name=args.model)

                # Write output files to output directory (flat structure for patches)
                report_path = os.path.join(args.output_dir, "review-inline.txt")
                metadata_path = os.path.join(args.output_dir, "review-metadata.json")

                with open(report_path, 'w') as f:
                    f.write(report_text)

                metadata_gen.save_json(metadata, metadata_path)

                # Write fix patches if proposed
                if result.fix_patches:
                    fix_path = os.path.join(args.output_dir, "review-fix-patches.diff")
                    with open(fix_path, 'w') as f:
                        f.write(result.fix_patches)
                    if args.verbose:
                        print(f"  Fix patches: {fix_path}")

                # Print summary
                print(f"✓ Patch {patch_file}: {commit.subject}")
                print(f"  Issues found: {len(result.findings)}")
                print(f"  Severity: {metadata['issue-severity-score']}")
                print(f"  Report: {report_path}")
                print(f"  Metadata: {metadata_path}")
                print()

                successful += 1

            except Exception as e:
                print(f"✗ Error processing patch {patch_file}: {e}", file=sys.stderr)
                if args.debug:
                    import traceback
                    traceback.print_exc()
                failed += 1
                failed_items.append(patch_file)
                continue

    # Commit mode: process commits
    elif not args.patch:
        for i, commit_ref in enumerate(items_to_process, 1):
            try:
                # Extract commit
                commit = git.get_commit(commit_ref)

                # Skip merge commits (too complex)
                if len(commit.diff.split('\n')) < 5 or "Merge:" in commit.message:
                    if args.verbose:
                        print(f"Skipping merge commit {commit.sha[:12]}")
                    skipped += 1
                    continue

                # Build output directory path: output_dir/ab/abc123.../
                sha_short = commit.sha[:12]
                commit_dir = os.path.join(args.output_dir, commit.sha[:2], commit.sha)

                # Check if commit was already processed (directory exists), unless --force
                if not args.force and os.path.exists(commit_dir):
                    if args.verbose:
                        print(f"[{i}/{len(commits)}] Skipping already processed commit {sha_short}...")
                    skipped += 1
                    continue

                # Show progress for multiple commits
                if total_items > 1 and args.verbose:
                    print(f"[{i}/{total_items}] Processing commit {sha_short}...")

                # Execute review with timing
                start_time = time.time()
                result = workflow.execute_review(commit)
                elapsed_time = time.time() - start_time

                if args.debug:
                    print(f"[DEBUG] Review completed in {elapsed_time:.2f} seconds")

                # Re-evaluate if no issues found and review completed suspiciously fast
                if args.reevaluate_threshold > 0 and len(result.findings) == 0 and elapsed_time < args.reevaluate_threshold:
                    if args.verbose:
                        print(f"  No issues found in {elapsed_time:.1f}s — re-evaluating...")
                    reeval_start = time.time()
                    result2 = workflow.execute_review(commit)
                    reeval_elapsed = time.time() - reeval_start
                    if len(result2.findings) > 0:
                        if args.verbose:
                            print(f"  Re-evaluation found {len(result2.findings)} issue(s) — using re-evaluation result")
                        result = result2
                        elapsed_time = reeval_elapsed
                    elif args.verbose:
                        print(f"  Re-evaluation confirmed: no issues found")

                # Create output directory after successful review
                os.makedirs(commit_dir, exist_ok=True)

                # If --force and directory exists, clean up old review files
                # (do this AFTER review succeeds but BEFORE writing new files)
                if args.force and os.path.exists(commit_dir):
                    old_files = [
                        os.path.join(commit_dir, "review-metadata.json"),
                        os.path.join(commit_dir, "review-pre-verification.json"),
                        os.path.join(commit_dir, "review-inline.txt"),
                        os.path.join(commit_dir, "review-fix-patches.diff"),
                    ]
                    for old_file in old_files:
                        if os.path.exists(old_file):
                            os.remove(old_file)
                            if args.debug:
                                print(f"[DEBUG] Removed stale file: {old_file}")

                # Generate pre-verification metadata if SUSE verification was done
                if result.suse_verification:
                    pre_verification_findings = (
                        result.suse_verification.get('findings_in_upstream', []) +
                        result.suse_verification.get('findings_only_downstream', [])
                    )

                    if pre_verification_findings:
                        pre_verification_metadata = metadata_gen.generate_pre_verification_metadata(
                            commit,
                            pre_verification_findings,
                            result.suse_verification
                        )

                        pre_verify_path = os.path.join(commit_dir, "review-pre-verification.json")
                        metadata_gen.save_json(pre_verification_metadata, pre_verify_path)

                        if args.verbose:
                            print(f"  Pre-verification findings saved: {pre_verify_path}")

                # Generate outputs
                report_text = formatter.format_report(
                    commit,
                    result.findings,
                    summary=result.summary,
                    suse_verification=result.suse_verification,
                    elapsed_time=elapsed_time,
                    model_name=args.model
                )
                metadata = metadata_gen.generate(commit, result.findings, elapsed_time=elapsed_time, model_name=args.model)

                # Write output files to commit directory
                report_path = os.path.join(commit_dir, "review-inline.txt")
                metadata_path = os.path.join(commit_dir, "review-metadata.json")

                with open(report_path, 'w') as f:
                    f.write(report_text)

                metadata_gen.save_json(metadata, metadata_path)

                # Write fix patches if proposed
                if result.fix_patches:
                    fix_path = os.path.join(commit_dir, "review-fix-patches.diff")
                    with open(fix_path, 'w') as f:
                        f.write(result.fix_patches)
                    if args.verbose:
                        print(f"  Fix patches: {fix_path}")

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
                failed_items.append(commit_ref)

                # Continue with next commit
                if total_items > 1:
                    print(f"Continuing with next commit...\n", file=sys.stderr)
                continue

            except Exception as e:
                print(f"✗ Unexpected error processing commit {commit_ref}: {e}", file=sys.stderr)
                if args.debug:
                    import traceback
                    traceback.print_exc()

                failed += 1
                failed_items.append(commit_ref)

                # Continue with next commit
                if total_items > 1:
                    print(f"Continuing with next commit...\n", file=sys.stderr)
                continue

    # Print final summary for multiple items
    if total_items > 1:
        item_type = "patches" if args.patch else "commits"
        print("=" * 70)
        print(f"Summary: {total_items} total {item_type}")
        print(f"  ✓ {successful} successful")
        if failed > 0:
            print(f"  ✗ {failed} failed")
        if skipped > 0:
            print(f"  ⊘ {skipped} skipped")
        print("=" * 70)

        # Show failed items for easy re-run
        if failed_items:
            print()
            print(f"Failed {item_type}:")
            for item in failed_items:
                print(f"  {item}")
            print()
            if args.patch:
                print(f"To retry failed patches:")
                print(f"  {' '.join(['kernel_review_agent.py', '--patch'] + failed_items)}")
            else:
                print(f"To retry failed commits:")
                print(f"  {' '.join(['kernel_review_agent.py'] + failed_items)}")
            print("=" * 70)

    # Return error code if all items failed
    if successful == 0 and (failed > 0 or skipped == total_items):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
