#!/usr/bin/env python3
"""
Linux Kernel Commit Review Agent

AI-powered agent for reviewing Linux kernel commits to detect potential regressions.
Focuses on code changes only, ignoring commit message quality and tags.
"""

import argparse
import json
import sys
import os
import time
from datetime import datetime
import multiprocessing
import threading
try:
    from queue import Empty
except ImportError:
    from Queue import Empty  # Python 2 compatibility


class TimestampedStream:
    """Wraps a stream and prepends HH:MM:SS to every line."""

    def __init__(self, stream, instance_id=None):
        self._stream = stream
        self._at_line_start = True
        self._instance_id = instance_id

    def write(self, data):
        if not data:
            return
        output = []
        for ch in data:
            if self._at_line_start and ch != '\n':
                if self._instance_id is not None:
                    output.append(f'[{self._instance_id}]')
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
from prompt_management.prompt_set_mapper import PromptSetMapper
from analysis import ReviewWorkflow, HybridReviewWorkflow
from output import ReportFormatter, JSONReportFormatter, MetadataGenerator


def process_commit_worker(instance_id, work_queue, results_queue, args, host_reset_event, stop_event):
    """
    Worker process for parallel commit processing.

    Args:
        instance_id: Instance number for logging
        work_queue: Queue containing items to process (commits or patches)
        results_queue: Queue to put results into
        args: Parsed command-line arguments
        host_reset_event: Event to signal host reset is needed
        stop_event: Event to signal workers should stop
    """
    # Set up instance-specific logging if timestamps enabled
    if args.timestamps:
        # Get the original stream (unwrap if already wrapped to avoid double-timestamping)
        stdout = sys.stdout._stream if hasattr(sys.stdout, '_stream') else sys.stdout
        stderr = sys.stderr._stream if hasattr(sys.stderr, '_stream') else sys.stderr
        sys.stdout = TimestampedStream(stdout, instance_id=instance_id)
        sys.stderr = TimestampedStream(stderr, instance_id=instance_id)

    try:
        # Initialize all components for this worker instance
        # (Same initialization as in main(), but per-worker)
        provider = get_provider_from_args(args)

        # Initialize LLM client
        provider_kwargs = {
            'model': args.model,
            'verbose': args.verbose,
            'debug': args.debug,
            'dump_prompts': args.save_prompts,
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

        # Wrap with resilient client if host reset enabled
        enable_reset = (args.enable_host_reset if hasattr(args, 'enable_host_reset')
                        else config.ENABLE_HOST_RESET)

        if enable_reset:
            from llm_integration.resilient_client import ResilientLLMClient

            factory_kwargs = provider_kwargs.copy()
            factory_kwargs['provider'] = provider

            fallback_model = None
            max_attempts = 0

            if hasattr(args, 'host_reset_model') and args.host_reset_model:
                fallback_model = args.host_reset_model
            elif config.HOST_RESET_FALLBACK_MODEL:
                fallback_model = config.HOST_RESET_FALLBACK_MODEL

            max_attempts = (args.host_reset_max_attempts
                           if hasattr(args, 'host_reset_max_attempts')
                           else config.HOST_RESET_MAX_ATTEMPTS)

            llm = ResilientLLMClient(
                wrapped_client=llm,
                enable_reset=True,
                fallback_model=fallback_model,
                max_reset_attempts=max_attempts,
                **factory_kwargs
            )

        # Apply --max-tokens override to config module (worker has fresh import)
        if getattr(args, 'max_tokens', None):
            config.DEFAULT_MAX_TOKENS = args.max_tokens
            config.CATEGORIZE_MAX_TOKENS = args.max_tokens
            config.ANALYZE_MAX_TOKENS = args.max_tokens
            config.VERIFY_MAX_TOKENS = args.max_tokens

        # Initialize prompt loader
        _config = config.load_configuration()
        config_overrides = _config.get('CUSTOM_MODEL_TO_PROMPT_SET', {})

        prompts = PromptLoader(
            prompts_dir=args.prompts_dir,
            prompt_set=args.prompt_set,
            model_name=args.model,
            config_overrides=config_overrides,
            upstream_review=getattr(args, 'upstream_review', False)
        )

        matcher = SubsystemMatcher(prompts_dir=args.prompts_dir, prompt_loader=prompts)

        # Initialize patch repo extractor for commit message enhancement
        kernel_source_extractor = None
        if not getattr(args, 'patch', False):
            patch_repo = getattr(args, 'patch_repo', None) or config.PATCH_REPO
            if patch_repo:
                kernel_source_extractor = MultiRepoExtractor(
                    repo_path=patch_repo,
                    verbose=args.verbose,
                    debug=args.debug
                )
                if not kernel_source_extractor.is_available():
                    kernel_source_extractor = None

        # Initialize upstream repo extractor for backport verification
        upstream_repo_extractor = None
        if not getattr(args, 'patch', False):
            upstream_repo = getattr(args, 'upstream_repo', None) or config.UPSTREAM_REPO
            if upstream_repo:
                upstream_repo_extractor = MultiRepoExtractor(
                    repo_path=upstream_repo,
                    verbose=args.verbose,
                    debug=args.debug
                )
                if not upstream_repo_extractor.is_available():
                    upstream_repo_extractor = None

        # Initialize git extractor
        git = CommitExtractor(
            verbose=args.verbose,
            debug=args.debug,
            kernel_source_extractor=kernel_source_extractor
        )

        # Initialize workflow
        if args.enable_tools:
            git_dir = os.getcwd()
            llm = ToolEnabledClient(
                git_dir=git_dir,
                host=args.host,
                port=args.port,
                api_key=args.api_key,
                model=args.model,
                verbose=args.verbose,
                debug=args.debug,
                dump_prompts=args.save_prompts,
                reasoning_effort=args.reasoning_effort or None
            )

            if enable_reset:
                from llm_integration.resilient_client import ResilientLLMClient
                llm = ResilientLLMClient(
                    wrapped_client=llm,
                    enable_reset=True,
                    fallback_model=fallback_model,
                    max_reset_attempts=max_attempts,
                    **factory_kwargs
                )

            workflow = HybridReviewWorkflow(
                llm, prompts, matcher,
                verbose=args.verbose,
                debug=args.debug,
                skip_verification=args.skip_verification,
                upstream_verifier=None,  # TODO: pass if needed
                enable_tools=True,
                upstream_repo=upstream_repo_extractor,
                kernel_source_repo=kernel_source_extractor,
                propose_fixes=args.propose_fixes,
                max_tool_iterations=args.max_tool_iterations,
                stop_after=args.stop_after
            )
        else:
            workflow = ReviewWorkflow(
                llm, prompts, matcher,
                verbose=args.verbose,
                debug=args.debug,
                skip_verification=args.skip_verification,
                upstream_verifier=None,
                propose_fixes=args.propose_fixes,
                max_tool_iterations=args.max_tool_iterations,
                stop_after=args.stop_after,
                git_dir=os.getcwd()
            )

        formatter = ReportFormatter()
        json_formatter = JSONReportFormatter()
        metadata_gen = MetadataGenerator()

        # Process items from queue
        while not stop_event.is_set():
            try:
                # Get next item with timeout
                item_data = work_queue.get(timeout=0.5)
                if item_data is None:  # Sentinel to stop
                    break

                item_idx, item_ref, is_patch = item_data

                try:
                    # Process the commit or patch
                    if is_patch:
                        # Process patch file
                        patch_file = item_ref
                        if not os.path.exists(patch_file):
                            results_queue.put({
                                'status': 'failed',
                                'item': patch_file,
                                'error': f"Patch file not found: {patch_file}"
                            })
                            continue

                        commit = git.from_patch_file(patch_file)
                        commit_dir = args.output_dir
                    else:
                        # Process commit
                        commit = git.get_commit(item_ref)

                        # Skip merge commits
                        if len(commit.diff.split('\n')) < 5 or "Merge:" in commit.message:
                            results_queue.put({
                                'status': 'skipped',
                                'item': item_ref,
                                'reason': 'merge commit'
                            })
                            continue

                        sha_short = commit.sha[:12]
                        commit_dir = os.path.join(args.output_dir, commit.sha[:2], commit.sha)

                        # Check if already processed
                        if not args.force and os.path.exists(commit_dir):
                            results_queue.put({
                                'status': 'skipped',
                                'item': item_ref,
                                'reason': 'already processed'
                            })
                            continue

                    # Execute review
                    start_time = time.time()
                    result = workflow.execute_review(commit, commit_output_dir=commit_dir)
                    elapsed_time = time.time() - start_time

                    # Create output directory
                    os.makedirs(commit_dir, exist_ok=True)

                    # Generate outputs
                    report_text = formatter.format_report(
                        commit, result.findings,
                        summary=result.summary,
                        upstream_verification=result.upstream_verification,
                        backport_comparison=result.backport_comparison,
                        elapsed_time=elapsed_time,
                        is_patch=is_patch,
                        model_name=args.model,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens
                    )
                    report_json = json_formatter.format_report(
                        commit, result.findings,
                        summary=result.summary,
                        upstream_verification=result.upstream_verification,
                        backport_comparison=result.backport_comparison,
                        elapsed_time=elapsed_time,
                        is_patch=is_patch,
                        model_name=args.model,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens
                    )
                    metadata = metadata_gen.generate(
                        commit, result.findings,
                        elapsed_time=elapsed_time,
                        is_patch=is_patch,
                        model_name=args.model,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                        backport_comparison=result.backport_comparison
                    )

                    # Generate pre-verification metadata if we have pre-verification findings
                    # This saves all information needed to re-verify findings later
                    if result.pre_verification_findings and len(result.pre_verification_findings) > 0:
                        pre_verification_metadata = metadata_gen.generate_pre_verification_metadata(
                            commit,
                            result.pre_verification_findings,
                            upstream_verification=result.upstream_verification,
                            categories=result.categories,
                            subsystems=result.subsystems_loaded,
                            code_context_formatted=result.code_context_formatted
                        )

                        pre_verify_path = os.path.join(commit_dir, "review-pre-verification.json")
                        metadata_gen.save_json(pre_verification_metadata, pre_verify_path)

                        if args.verbose:
                            print(f"  Pre-verification findings saved: {pre_verify_path}")

                    # Write outputs
                    report_path = os.path.join(commit_dir, "review-inline.txt")
                    json_path = os.path.join(commit_dir, "review-inline.json")
                    metadata_path = os.path.join(commit_dir, "review-metadata.json")

                    with open(report_path, 'w') as f:
                        f.write(report_text)
                    metadata_gen.save_json(report_json, json_path)
                    metadata_gen.save_json(metadata, metadata_path)

                    # Write fix patches if any
                    if result.fix_patches:
                        fix_path = os.path.join(commit_dir, "review-fix-patches.diff")
                        with open(fix_path, 'w') as f:
                            f.write(result.fix_patches)

                    # Report success
                    results_queue.put({
                        'status': 'success',
                        'item': item_ref,
                        'commit': commit,
                        'findings': len(result.findings),
                        'severity': metadata['issue-severity-score'],
                        'elapsed_time': elapsed_time,
                        'report_path': report_path,
                        'metadata_path': metadata_path
                    })

                except Exception as e:
                    # Check if it's a host error that requires reset
                    from llm_integration.error_detector import is_fatal_host_error
                    if is_fatal_host_error(e):
                        host_reset_event.set()
                        # Re-queue the item for retry after reset
                        work_queue.put(item_data)

                    results_queue.put({
                        'status': 'failed',
                        'item': item_ref,
                        'error': str(e)
                    })

            except Empty:
                continue
            except Exception as e:
                if args.debug:
                    import traceback
                    traceback.print_exc()
                break

    except Exception as e:
        if args.debug:
            import traceback
            traceback.print_exc()


def list_prompt_sets(prompts_dir: str):
    """
    List available prompt sets and exit.

    Args:
        prompts_dir: Directory containing prompt sets
    """
    print("Available prompt sets:\n")

    try:
        mapper = PromptSetMapper(prompts_dir)
        available_sets = mapper.list_available_sets()

        if not available_sets:
            print("  No prompt sets found.")
            return

        # Sort by name for consistent display
        for set_name in sorted(available_sets.keys()):
            set_info = available_sets[set_name]
            name = set_info.get('name', set_name)
            description = set_info.get('description', 'N/A')
            estimated_tokens = set_info.get('estimated_tokens', 'Unknown')

            print(f"  {set_name}:")
            print(f"    Name: {name}")
            print(f"    Description: {description}")
            print(f"    Estimated tokens: {estimated_tokens}")
            print()

        # Show model mappings
        print("\nDefault model mappings:")
        model_mappings = mapper.get_model_mappings()
        if model_mappings:
            for model, prompt_set in sorted(model_mappings.items()):
                print(f"  {model} → {prompt_set}")
        else:
            print("  (none configured)")

    except Exception as e:
        print(f"Error listing prompt sets: {e}", file=sys.stderr)


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

  # Review commits in parallel (2x speed with 2 instances)
  %(prog)s --list commits.txt --parallel 2 --output-dir ./reviews/

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
        "--verifier-model",
        default=None,
        help="Model to use as the verifier in --reverify/--reverify-update mode. "
             "When set, --model identifies whose results are being re-verified while "
             "--verifier-model is used for the verification step itself."
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
        "--save-prompts",
        action="store_true",
        help="Save LLM prompts, responses, and thinking blocks in commit output directory under prompts/ subdirectory"
    )

    # Host reset options
    parser.add_argument(
        "--enable-host-reset",
        action="store_true",
        help="Enable automatic LLM host reset on fatal connection errors"
    )

    parser.add_argument(
        "--host-reset-model",
        help="Fallback model for host reset test query (default: provider-specific)"
    )

    parser.add_argument(
        "--host-reset-max-attempts",
        type=int,
        default=0,
        help="Maximum host reset attempts per operation (0 = unlimited, default: 0)"
    )

    parser.add_argument(
        "--skip-verification",
        action="store_true",
        help="Skip false-positive verification step (faster but may report more issues)"
    )

    parser.add_argument(
        "--reverify",
        metavar="PATH",
        help="Re-verify findings from existing review-pre-verification.json file(s). "
             "PATH can be a file or directory containing pre-verification JSON files."
    )

    parser.add_argument(
        "--reverify-update",
        action="store_true",
        help="Re-verify and prune findings for the given commits from their existing "
             "review-inline.json output files.  Updates review-inline.*, "
             "review-metadata.json in-place (preserving all other metadata) and saves "
             "removed findings to review-pruned.json.  Requires commits to be specified "
             "and an output directory containing prior review results."
    )

    parser.add_argument(
        "--stop-after",
        choices=["categorize", "analyze", "verify"],
        help="Stop workflow after the specified stage (for dataset generation). "
             "categorize = stop after Task 1 (change categorization), "
             "analyze = stop after Task 2 (regression analysis), "
             "verify = stop after Task 3 (verification, equivalent to full run)"
    )

    fix_group = parser.add_mutually_exclusive_group()
    fix_group.add_argument(
        "--propose-fixes",
        action="store_true",
        default=None,
        help="Ask the LLM to propose fix patches for each identified issue (written to review-fix-patches.diff)"
    )
    fix_group.add_argument(
        "--no-propose-fixes",
        action="store_true",
        help="Disable fix patch proposals (overrides config default)"
    )

    parser.add_argument(
        "--upstream-review",
        action="store_true",
        default=config.UPSTREAM_REVIEW,
        help="Enable upstream review mode: check commit message quality, Fixes: tags, "
             "and subjective code quality (default: disabled)"
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
        "--prompt-set",
        default=config.DEFAULT_PROMPT_SET,
        help="Prompt set to use: 'auto' (map from model), 'default' (full), "
             "'small' (simplified), or custom set name (default: auto)"
    )

    parser.add_argument(
        "--list-prompt-sets",
        action="store_true",
        help="List available prompt sets and exit"
    )

    parser.add_argument(
        "--patch-repo",
        help="Path to an intermediate patch repository for commit message extraction and distro-commit resolution"
    )

    parser.add_argument(
        "--upstream-repo",
        help="Path to upstream Linux kernel git repository for backport comparison"
    )

    # Deprecated aliases for backward compatibility
    parser.add_argument("--suse-kernel-source", dest="patch_repo", help=argparse.SUPPRESS)
    parser.add_argument("--upstream-linux", dest="upstream_repo", help=argparse.SUPPRESS)

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

    parser.add_argument(
        "--parallel",
        type=int,
        metavar="NUM",
        help="Run NUM instances in parallel for the same model (default: 1, sequential)"
    )

    args = parser.parse_args()

    # Redirect stdout and stderr to log file if requested
    if args.log_file:
        try:
            log = open(args.log_file, 'a', buffering=1)
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

    # Handle propose-fixes with config default
    if args.no_propose_fixes:
        args.propose_fixes = False
    elif args.propose_fixes is None:
        args.propose_fixes = config.PROPOSE_FIXES

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

    # Handle --list-prompt-sets: show available prompt sets and exit
    if args.list_prompt_sets:
        list_prompt_sets(args.prompts_dir)
        return 0

    # Check if we have commits to process (unless in reverify mode)
    if not args.commit and not args.reverify:
        print("Error: No commits specified. Provide commit SHA(s), ranges, use --list FILE, or use --reverify PATH", file=sys.stderr)
        return 1

    # Check if in git repository (not required for reverify mode)
    if not args.reverify:
        temp_git = CommitExtractor(verbose=args.verbose)
        if not temp_git.is_git_repo():
            print("Error: Must run in a git repository", file=sys.stderr)
            return 1

    # Show debug info if enabled
    if args.debug:
        print(f"Configuration:")
        print(f"  Install directory: {config.INSTALL_DIR}")
        print(f"  Prompts directory: {args.prompts_dir}")
        print(f"  LLM: {args.host}:{args.port}")
        print(f"  Model: {args.model}")
        print(f"  Verbose: {args.verbose}")
        print(f"  Debug: {args.debug}")
        print(f"  Save prompts: {args.save_prompts}")
        print(f"  Skip verification: {args.skip_verification}")
        print(f"  Upstream review: {args.upstream_review}")
        print(f"  Output directory: {args.output_dir}")
        print()

    # Override token limits if --max-tokens specified
    if args.max_tokens:
        config.DEFAULT_MAX_TOKENS = args.max_tokens
        config.CATEGORIZE_MAX_TOKENS = args.max_tokens
        config.ANALYZE_MAX_TOKENS = args.max_tokens
        config.VERIFY_MAX_TOKENS = args.max_tokens

        if args.debug:
            print(f"Token limits overridden to: {args.max_tokens}")
            print()

    # Override timeout if --timeout specified
    if args.timeout is not None:
        if args.timeout == 0:
            config.LLM_TIMEOUT = None  # Disable timeout
        else:
            config.LLM_TIMEOUT = args.timeout

        if args.debug:
            timeout_str = "disabled" if config.LLM_TIMEOUT is None else f"{config.LLM_TIMEOUT}s"
            print(f"LLM timeout: {timeout_str}")
            print()

    # Set Google credentials if specified
    if hasattr(args, 'google_credentials') and args.google_credentials:
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = args.google_credentials
        if args.debug:
            print(f"  Google credentials file: {args.google_credentials}")

    # Determine provider
    provider = get_provider_from_args(args)
    if args.debug:
        print(f"  Provider: {provider}")

    # Determine effective verifier model (--verifier-model overrides --model for LLM calls
    # in reverify modes; --model still identifies whose results are being re-verified)
    verifier_model = args.verifier_model if args.verifier_model else args.model
    if args.verifier_model and args.debug:
        print(f"  Verifier model: {verifier_model} (reviewing results of: {args.model})")

    # Determine host reset configuration (used for both initial and tool-enabled clients)
    enable_reset = (args.enable_host_reset if hasattr(args, 'enable_host_reset')
                    else config.ENABLE_HOST_RESET)

    fallback_model = None
    max_attempts = 0  # 0 = unlimited
    factory_kwargs = {}

    if enable_reset:
        # Determine fallback model (CLI > config > provider default)
        if hasattr(args, 'host_reset_model') and args.host_reset_model:
            fallback_model = args.host_reset_model
        elif config.HOST_RESET_FALLBACK_MODEL:
            fallback_model = config.HOST_RESET_FALLBACK_MODEL

        # Get max attempts
        max_attempts = (args.host_reset_max_attempts
                       if hasattr(args, 'host_reset_max_attempts')
                       else config.HOST_RESET_MAX_ATTEMPTS)

    # Initialize components
    try:
        # Prepare provider-specific kwargs
        provider_kwargs = {
            'model': verifier_model,
            'verbose': args.verbose,
            'debug': args.debug,
            'dump_prompts': args.save_prompts,
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

        # Wrap with resilient client if host reset enabled
        if enable_reset:
            from llm_integration.resilient_client import ResilientLLMClient

            # Prepare factory kwargs for client recreation during reset
            factory_kwargs = provider_kwargs.copy()
            factory_kwargs['provider'] = provider

            # Wrap the client
            llm = ResilientLLMClient(
                wrapped_client=llm,
                enable_reset=True,
                fallback_model=fallback_model,
                max_reset_attempts=max_attempts,
                **factory_kwargs
            )

            if args.verbose:
                fb_display = fallback_model if fallback_model else f"{provider} default"
                print(f"Host reset enabled (fallback: {fb_display}, max attempts: {max_attempts})")

    except Exception as e:
        print(f"Error: Failed to initialize {provider} LLM client", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        return 1

    # Verify prompts directory exists
    if not os.path.exists(args.prompts_dir):
        print(f"Error: Prompts directory not found: {args.prompts_dir}", file=sys.stderr)
        print(f"Tip: Use --prompts-dir option to specify the prompts directory", file=sys.stderr)
        return 1

    # Load configuration for custom model mappings
    _config = config.load_configuration()
    config_overrides = _config.get('CUSTOM_MODEL_TO_PROMPT_SET', {})

    # Initialize PromptLoader with prompt-set support
    try:
        prompts = PromptLoader(
            prompts_dir=args.prompts_dir,
            prompt_set=args.prompt_set,
            model_name=verifier_model,
            config_overrides=config_overrides,
            upstream_review=args.upstream_review
        )

        if args.verbose:
            print(f"Using prompt set: {prompts.prompt_set}")
            if prompts.metadata:
                desc = prompts.metadata.get('description', 'N/A')
                tokens = prompts.metadata.get('estimated_tokens', 'N/A')
                print(f"  Description: {desc}")
                print(f"  Estimated tokens: {tokens}")

    except Exception as e:
        print(f"Error: Failed to initialize prompt loader", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        return 1

    # Initialize SubsystemMatcher with prompt loader for subsystem filtering
    matcher = SubsystemMatcher(prompts_dir=args.prompts_dir, prompt_loader=prompts)

    # Initialize patch repo extractor for commit message enhancement
    kernel_source_extractor = None
    patch_repo = args.patch_repo or config.PATCH_REPO

    if patch_repo and not args.patch:
        kernel_source_extractor = MultiRepoExtractor(
            repo_path=patch_repo,
            verbose=args.verbose,
            debug=args.debug
        )

        if kernel_source_extractor.is_available():
            if args.verbose:
                print(f"Patch repo commit message enhancement enabled")
        else:
            if args.debug:
                print(f"Patch repository not available: {patch_repo}")
            kernel_source_extractor = None

    # Initialize git commit extractor with optional patch repo enhancement
    git = CommitExtractor(
        verbose=args.verbose,
        debug=args.debug,
        kernel_source_extractor=kernel_source_extractor
    )

    # Initialize upstream verifier if configured (skip in patch mode)
    upstream_verifier = None
    upstream_repo_extractor = None
    if not args.patch:
        upstream_repo = args.upstream_repo or config.UPSTREAM_REPO

        # Create upstream repository extractor for backport verification
        if upstream_repo:
            upstream_repo_extractor = MultiRepoExtractor(
                repo_path=upstream_repo,
                verbose=args.verbose,
                debug=args.debug
            )

            if upstream_repo_extractor.is_available():
                if args.verbose:
                    print(f"Upstream Linux repository available for backport verification")
                if args.debug:
                    print(f"Upstream repo: {upstream_repo}")
            else:
                if args.debug:
                    print(f"Upstream Linux repository not available: {upstream_repo}")
                upstream_repo_extractor = None

        if patch_repo or upstream_repo:
            if args.debug:
                print(f"Initializing upstream verifier")
                if patch_repo:
                    print(f"  patch-repo: {patch_repo}")
                if upstream_repo:
                    print(f"  upstream: {upstream_repo}")

            from analysis import UpstreamVerifier
            upstream_verifier = UpstreamVerifier(
                kernel_source_repo=patch_repo,
                upstream_repo=upstream_repo,
                llm_client=llm,
                verbose=args.verbose,
                debug=args.debug
            )

            if not upstream_verifier.is_enabled():
                if patch_repo:
                    print(f"Warning: Patch repository not available: {patch_repo}",
                          file=sys.stderr)
                upstream_verifier = None
            elif args.verbose:
                print(f"Upstream verification enabled")

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
                print("Hybrid mode: Tool calling enabled for deep-dive verification\n")

            # Replace LLM client with tool-enabled version
            git_dir = os.getcwd()
            # Verify that we're in a git repository
            if not os.path.exists(os.path.join(git_dir, '.git')):
                print(f"Warning: Current directory is not a git repository: {git_dir}", file=sys.stderr)
                print("Tool-based verification may not work correctly.", file=sys.stderr)
            if args.debug:
                print(f"Tool-enabled client git_dir: {git_dir}")

            llm = ToolEnabledClient(
                git_dir=git_dir,
                host=args.host,
                port=args.port,
                api_key=args.api_key,
                model=verifier_model,
                verbose=args.verbose,
                debug=args.debug,
                dump_prompts=args.save_prompts,
                reasoning_effort=args.reasoning_effort or None
            )

            # Wrap ToolEnabledClient with resilient client if host reset enabled
            if enable_reset:
                from llm_integration.resilient_client import ResilientLLMClient

                llm = ResilientLLMClient(
                    wrapped_client=llm,
                    enable_reset=True,
                    fallback_model=fallback_model,
                    max_reset_attempts=max_attempts,
                    **factory_kwargs
                )

                if args.verbose:
                    print(f"Tool-enabled client wrapped with host reset")

            workflow = HybridReviewWorkflow(
                llm,
                prompts,
                matcher,
                verbose=args.verbose,
                debug=args.debug,
                skip_verification=args.skip_verification,
                upstream_verifier=upstream_verifier,
                enable_tools=True,
                upstream_repo=upstream_repo_extractor,
                kernel_source_repo=kernel_source_extractor,
                propose_fixes=args.propose_fixes,
                max_tool_iterations=args.max_tool_iterations,
                stop_after=args.stop_after
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
            upstream_verifier=upstream_verifier,
            propose_fixes=args.propose_fixes,
            max_tool_iterations=args.max_tool_iterations,
            stop_after=args.stop_after,
            git_dir=os.getcwd()
        )
    formatter = ReportFormatter()
    json_formatter = JSONReportFormatter()
    metadata_gen = MetadataGenerator()

    # Re-verification mode: load and re-verify existing pre-verification JSON files
    if args.reverify:
        reverify_path = args.reverify

        # Collect JSON files to re-verify
        json_files = []
        if os.path.isfile(reverify_path):
            if not reverify_path.endswith('.json'):
                print(f"Error: File must be a JSON file: {reverify_path}", file=sys.stderr)
                return 1
            json_files.append(reverify_path)
        elif os.path.isdir(reverify_path):
            # Find all review-pre-verification.json files in directory tree
            for root, dirs, files in os.walk(reverify_path):
                for file in files:
                    if file == 'review-pre-verification.json':
                        json_files.append(os.path.join(root, file))
            if not json_files:
                print(f"Error: No review-pre-verification.json files found in {reverify_path}", file=sys.stderr)
                return 1
        else:
            print(f"Error: Path not found: {reverify_path}", file=sys.stderr)
            return 1

        if args.verbose:
            print(f"Re-verification mode: processing {len(json_files)} file(s)...\n")

        # Track results
        successful = 0
        failed = 0

        for i, json_file in enumerate(json_files, 1):
            try:
                if args.verbose:
                    print(f"[{i}/{len(json_files)}] Re-verifying {json_file}...")

                # Re-verify using workflow
                start_time = time.time()
                result = workflow.reverify_from_json(json_file)
                elapsed_time = time.time() - start_time

                # Reconstruct commit for output formatting
                with open(json_file, 'r') as f:
                    pre_data = json.load(f)

                from git_integration import Commit
                commit = Commit(
                    sha=pre_data['sha'],
                    author=pre_data.get('author', 'Unknown'),
                    date=pre_data.get('date', ''),
                    subject=pre_data['subject'],
                    message=pre_data.get('message', pre_data['subject']),
                    diff=pre_data['diff'],
                    files=pre_data.get('files', []),
                    upstream_commit=pre_data.get('upstream_commit'),
                    distro_commit=pre_data.get('upstream_verification', pre_data.get('suse_upstream_verification', {})).get('distro_commit_sha')
                )

                # Determine output directory (same as original)
                commit_dir = os.path.dirname(json_file)

                # Generate outputs
                report_text = formatter.format_report(
                    commit,
                    result.findings,
                    summary=result.summary,
                    upstream_verification=result.upstream_verification,
                    backport_comparison=result.backport_comparison,
                    elapsed_time=elapsed_time,
                    model_name=verifier_model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens
                )
                report_json = json_formatter.format_report(
                    commit,
                    result.findings,
                    summary=result.summary,
                    upstream_verification=result.upstream_verification,
                    backport_comparison=result.backport_comparison,
                    elapsed_time=elapsed_time,
                    model_name=verifier_model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens
                )
                metadata = metadata_gen.generate(
                    commit, result.findings,
                    elapsed_time=elapsed_time,
                    model_name=verifier_model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    backport_comparison=result.backport_comparison
                )

                # Write output files (overwrite existing)
                report_path = os.path.join(commit_dir, "review-inline.txt")
                json_path = os.path.join(commit_dir, "review-inline.json")
                metadata_path = os.path.join(commit_dir, "review-metadata.json")

                with open(report_path, 'w') as f:
                    f.write(report_text)

                metadata_gen.save_json(report_json, json_path)
                metadata_gen.save_json(metadata, metadata_path)

                # Print summary
                sha_short = commit.sha[:12]
                print(f"✓ Re-verified {sha_short}: {commit.subject}")
                print(f"  Issues found: {len(result.findings)} (was {pre_data.get('potential_issues_found', 0)} before verification)")
                print(f"  Severity: {metadata['issue-severity-score']}")
                print(f"  Report: {report_path}")
                print(f"  Metadata: {metadata_path}")
                print()

                successful += 1

            except Exception as e:
                print(f"✗ Error re-verifying {json_file}: {e}", file=sys.stderr)
                if args.debug:
                    import traceback
                    traceback.print_exc()
                failed += 1
                continue

        # Print summary
        if len(json_files) > 1:
            print("=" * 70)
            print(f"Re-verification Summary: {len(json_files)} total files")
            print(f"  ✓ {successful} successful")
            if failed > 0:
                print(f"  ✗ {failed} failed")
            print("=" * 70)

        return 0 if successful > 0 else 1

    # Re-verify-update mode: re-verify and prune findings from existing review-inline.json files
    if args.reverify_update:
        # Expand commits (same as normal commit processing)
        commits = []
        for commit_arg in args.commit:
            try:
                expanded = git.expand_range(commit_arg)
                commits.extend(expanded)
            except Exception as e:
                print(f"Error: Invalid commit or range: {commit_arg}", file=sys.stderr)
                print(f"Details: {e}", file=sys.stderr)
                return 1

        if args.verbose:
            print(f"Re-verify-update mode: processing {len(commits)} commit(s)...\n")

        successful = 0
        failed = 0
        skipped = 0
        total_update_time = 0.0
        completed_updates = 0

        for i, commit_sha in enumerate(commits, 1):
            try:
                commit = git.get_commit(commit_sha)
            except Exception as e:
                print(f"✗ Could not resolve commit {commit_sha}: {e}", file=sys.stderr)
                failed += 1
                continue

            commit_dir = os.path.join(args.output_dir, commit.sha[:2], commit.sha)
            inline_json_path = os.path.join(commit_dir, 'review-inline.json')

            if not os.path.exists(inline_json_path):
                print(f"✗ {commit.sha[:12]}: review-inline.json not found in {commit_dir} — skipping")
                skipped += 1
                continue

            try:
                if args.verbose:
                    eta_str = ""
                    if completed_updates > 0:
                        avg_time = total_update_time / completed_updates
                        remaining = len(commits) - i + 1
                        eta_seconds = avg_time * remaining
                        eta_minutes = int(eta_seconds / 60)
                        eta_secs = int(eta_seconds % 60)
                        if eta_minutes > 0:
                            eta_str = f" (ETA: {eta_minutes}m {eta_secs}s)"
                        else:
                            eta_str = f" (ETA: {eta_secs}s)"
                    print(f"[{i}/{len(commits)}] Re-verify-update {commit.sha[:12]}...{eta_str}")

                start_time = time.time()
                result, pruned = workflow.reverify_update_from_json(inline_json_path)
                elapsed_time = time.time() - start_time
                total_update_time += elapsed_time
                completed_updates += 1

                # Load existing inline data to preserve all metadata except findings/summary
                with open(inline_json_path, 'r') as f:
                    inline_data = json.load(f)

                original_count = len(inline_data.get('findings', []))
                surviving_count = len(result.findings)
                pruned_count = len(pruned)

                # Patch review-inline.json in-place (findings + summary only)
                updated_inline = dict(inline_data)
                updated_inline['findings'] = [json_formatter._format_finding(f) for f in result.findings]
                updated_inline['summary'] = result.summary
                metadata_gen.save_json(updated_inline, inline_json_path)

                # Regenerate review-inline.txt with original timing/token metadata preserved
                pre_verify_path = os.path.join(commit_dir, 'review-pre-verification.json')
                with open(pre_verify_path, 'r') as f:
                    pre_data = json.load(f)

                from git_integration import Commit as CommitObj
                full_commit = CommitObj(
                    sha=commit.sha,
                    author=inline_data.get('author', commit.author),
                    date=pre_data.get('date', ''),
                    subject=inline_data.get('subject', commit.subject),
                    message=pre_data.get('message', commit.subject),
                    diff=pre_data['diff'],
                    files=pre_data.get('files', []),
                    upstream_commit=inline_data.get('upstream-commit') or pre_data.get('upstream_commit'),
                    distro_commit=inline_data.get('distro-commit') or pre_data.get('upstream_verification', {}).get('distro_commit_sha')
                )

                orig_elapsed = inline_data.get('review-time-seconds')
                orig_model = inline_data.get('model', args.model)
                orig_input_tokens = inline_data.get('input-tokens')
                orig_output_tokens = inline_data.get('output-tokens')

                report_text = formatter.format_report(
                    full_commit,
                    result.findings,
                    summary=result.summary,
                    upstream_verification=result.upstream_verification,
                    backport_comparison=result.backport_comparison,
                    elapsed_time=orig_elapsed,
                    model_name=orig_model,
                    input_tokens=orig_input_tokens,
                    output_tokens=orig_output_tokens
                )
                txt_path = os.path.join(commit_dir, 'review-inline.txt')
                with open(txt_path, 'w') as f:
                    f.write(report_text)

                # Regenerate review-metadata.json (findings count/severity change;
                # timing and token metadata are preserved from original run)
                metadata = metadata_gen.generate(
                    full_commit,
                    result.findings,
                    elapsed_time=orig_elapsed,
                    model_name=orig_model,
                    input_tokens=orig_input_tokens,
                    output_tokens=orig_output_tokens,
                    backport_comparison=result.backport_comparison
                )
                metadata_path = os.path.join(commit_dir, 'review-metadata.json')
                metadata_gen.save_json(metadata, metadata_path)

                # Write review-pruned.json
                pruned_data = {
                    'commit': commit.sha,
                    'subject': inline_data.get('subject', commit.subject),
                    'original-count': original_count,
                    'pruned-count': pruned_count,
                    'surviving-count': surviving_count,
                    'pruned-findings': pruned
                }
                pruned_path = os.path.join(commit_dir, 'review-pruned.json')
                metadata_gen.save_json(pruned_data, pruned_path)

                sha_short = commit.sha[:12]
                print(f"✓ {sha_short}: {commit.subject}")
                print(f"  Findings: {original_count} → {surviving_count} ({pruned_count} pruned)")
                print(f"  Severity: {metadata['issue-severity-score']}")
                if pruned_count > 0:
                    print(f"  Pruned findings saved: {pruned_path}")
                print()

                successful += 1

            except Exception as e:
                print(f"✗ Error updating {commit.sha[:12]}: {e}", file=sys.stderr)
                if args.debug:
                    import traceback
                    traceback.print_exc()
                failed += 1
                continue

        if len(commits) > 1:
            print("=" * 70)
            print(f"Re-verify-update Summary: {len(commits)} total commits")
            print(f"  ✓ {successful} successful")
            if skipped > 0:
                print(f"  - {skipped} skipped (no existing review-inline.json)")
            if failed > 0:
                print(f"  ✗ {failed} failed")
            print("=" * 70)

        return 0 if successful > 0 or skipped > 0 else 1

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

    # Track timing for ETA calculation
    total_review_time = 0.0
    completed_reviews = 0
    overall_start_time = time.time()

    # Check if parallel processing is requested
    if args.parallel and args.parallel > 1:
        # Parallel processing mode
        num_workers = args.parallel

        if args.verbose:
            print(f"Running in parallel mode with {num_workers} instances\n")

        # Create multiprocessing queues
        work_queue = multiprocessing.Queue()
        results_queue = multiprocessing.Queue()
        host_reset_event = multiprocessing.Event()
        stop_event = multiprocessing.Event()

        # Populate work queue
        for idx, item in enumerate(items_to_process):
            work_queue.put((idx, item, args.patch))

        # Add sentinel values to signal workers to stop
        for _ in range(num_workers):
            work_queue.put(None)

        # Start worker processes
        workers = []
        for i in range(num_workers):
            worker = multiprocessing.Process(
                target=process_commit_worker,
                args=(i + 1, work_queue, results_queue, args, host_reset_event, stop_event)
            )
            worker.start()
            workers.append(worker)

        # Monitor workers and collect results
        completed_count = 0
        while completed_count < total_items:
            try:
                # Check for host reset event
                if host_reset_event.is_set():
                    if args.verbose:
                        print("\n⚠ Host reset required - synchronizing all instances...")

                    # Signal all workers to stop
                    stop_event.set()

                    # Wait for all workers to finish with timeout
                    for worker in workers:
                        worker.join(timeout=30)
                        if worker.is_alive():
                            worker.terminate()

                    # Perform host reset (placeholder - actual reset logic depends on provider)
                    if args.verbose:
                        print("Performing host reset...")
                    time.sleep(2)  # Give the host time to reset

                    # Clear events
                    host_reset_event.clear()
                    stop_event.clear()

                    # Restart workers
                    workers = []
                    for i in range(num_workers):
                        worker = multiprocessing.Process(
                            target=process_commit_worker,
                            args=(i + 1, work_queue, results_queue, args, host_reset_event, stop_event)
                        )
                        worker.start()
                        workers.append(worker)

                    if args.verbose:
                        print("All instances restarted\n")
                    continue

                # Get result with timeout
                result = results_queue.get(timeout=1.0)

                if result['status'] == 'success':
                    successful += 1
                    completed_count += 1

                    commit = result['commit']
                    sha_short = commit.sha[:12] if hasattr(commit, 'sha') else 'patch'

                    # Calculate ETA for parallel mode
                    eta_str = ""
                    if args.verbose and completed_reviews > 0:
                        avg_time = total_review_time / completed_reviews
                        # In parallel mode, divide by number of workers for effective speed
                        remaining_items = total_items - completed_count
                        if remaining_items > 0:
                            eta_seconds = (avg_time * remaining_items) / num_workers
                            eta_minutes = int(eta_seconds / 60)
                            eta_secs = int(eta_seconds % 60)
                            if eta_minutes > 0:
                                eta_str = f" (ETA: {eta_minutes}m {eta_secs}s)"
                            else:
                                eta_str = f" (ETA: {eta_secs}s)"

                    print(f"✓ [{completed_count}/{total_items}] {result['item']}: {commit.subject}{eta_str}")
                    print(f"  Issues found: {result['findings']}")
                    print(f"  Severity: {result['severity']}")
                    print(f"  Report: {result['report_path']}")
                    print(f"  Metadata: {result['metadata_path']}")
                    print()

                    total_review_time += result['elapsed_time']
                    completed_reviews += 1

                elif result['status'] == 'failed':
                    failed += 1
                    completed_count += 1
                    failed_items.append(result['item'])

                    print(f"✗ [{completed_count}/{total_items}] Error processing {result['item']}: {result['error']}", file=sys.stderr)
                    print()

                elif result['status'] == 'skipped':
                    skipped += 1
                    completed_count += 1

                    if args.verbose:
                        print(f"⊘ [{completed_count}/{total_items}] Skipped {result['item']}: {result.get('reason', 'unknown')}")

            except:
                # Timeout or other queue exception
                # Check if all workers are dead
                all_dead = all(not worker.is_alive() for worker in workers)
                if all_dead:
                    break
                continue

        # Wait for all workers to finish
        for worker in workers:
            worker.join(timeout=5)
            if worker.is_alive():
                worker.terminate()

        if args.verbose:
            print("All workers completed\n")

    # Sequential processing mode (original behavior)
    # Patch mode: process patch files
    elif args.patch:
        for i, patch_file in enumerate(items_to_process, 1):
            try:
                # Parse patch file
                if not os.path.exists(patch_file):
                    print(f"Error: Patch file not found: {patch_file}", file=sys.stderr)
                    failed += 1
                    failed_items.append(patch_file)
                    continue

                if args.verbose:
                    # Calculate ETA based on average time per review
                    eta_str = ""
                    if completed_reviews > 0:
                        avg_time = total_review_time / completed_reviews
                        remaining_items = total_items - i + 1
                        eta_seconds = avg_time * remaining_items
                        eta_minutes = int(eta_seconds / 60)
                        eta_secs = int(eta_seconds % 60)
                        if eta_minutes > 0:
                            eta_str = f" (ETA: {eta_minutes}m {eta_secs}s)"
                        else:
                            eta_str = f" (ETA: {eta_secs}s)"
                    print(f"[{i}/{total_items}] Processing patch {patch_file}...{eta_str}")

                commit = git.from_patch_file(patch_file)

                # Execute review with timing
                start_time = time.time()
                result = workflow.execute_review(commit, commit_output_dir=args.output_dir)
                elapsed_time = time.time() - start_time

                if args.debug:
                    print(f"Review completed in {elapsed_time:.2f} seconds")

                # Re-evaluate if no issues found and review completed suspiciously fast
                if args.reevaluate_threshold > 0 and len(result.findings) == 0 and elapsed_time < args.reevaluate_threshold:
                    if args.verbose:
                        print(f"  No issues found in {elapsed_time:.1f}s — re-evaluating...")
                    reeval_start = time.time()
                    result2 = workflow.execute_review(commit, commit_output_dir=args.output_dir)
                    reeval_elapsed = time.time() - reeval_start
                    if len(result2.findings) > 0:
                        if args.verbose:
                            print(f"  Re-evaluation found {len(result2.findings)} issue(s) — using re-evaluation result")
                        result = result2
                        elapsed_time = reeval_elapsed
                    elif args.verbose:
                        print(f"  Re-evaluation confirmed: no issues found")

                # Update timing statistics for ETA calculation
                total_review_time += elapsed_time
                completed_reviews += 1

                # Create output directory if needed
                if args.output_dir != "." and not os.path.exists(args.output_dir):
                    os.makedirs(args.output_dir)

                # Clean up old review files in patch mode (always overwrite)
                # (do this AFTER review succeeds but BEFORE writing new files)
                old_files = [
                    os.path.join(args.output_dir, "review-metadata.json"),
                    os.path.join(args.output_dir, "review-inline.txt"),
                    os.path.join(args.output_dir, "review-inline.json"),
                    os.path.join(args.output_dir, "review-fix-patches.diff"),
                ]
                for old_file in old_files:
                    if os.path.exists(old_file):
                        os.remove(old_file)
                        if args.debug:
                            print(f"Removed stale file: {old_file}")

                # Generate outputs
                report_text = formatter.format_report(
                    commit,
                    result.findings,
                    summary=result.summary,
                    upstream_verification=result.upstream_verification,
                    backport_comparison=result.backport_comparison,
                    elapsed_time=elapsed_time,
                    is_patch=True,  # Flag for patch mode formatting
                    model_name=args.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens
                )
                report_json = json_formatter.format_report(
                    commit,
                    result.findings,
                    summary=result.summary,
                    upstream_verification=result.upstream_verification,
                    backport_comparison=result.backport_comparison,
                    elapsed_time=elapsed_time,
                    is_patch=True,
                    model_name=args.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens
                )
                metadata = metadata_gen.generate(
                    commit, result.findings,
                    elapsed_time=elapsed_time,
                    is_patch=True,
                    model_name=args.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    backport_comparison=result.backport_comparison
                )

                # Write output files to output directory (flat structure for patches)
                report_path = os.path.join(args.output_dir, "review-inline.txt")
                json_path = os.path.join(args.output_dir, "review-inline.json")
                metadata_path = os.path.join(args.output_dir, "review-metadata.json")

                with open(report_path, 'w') as f:
                    f.write(report_text)

                metadata_gen.save_json(report_json, json_path)
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
                    # Calculate ETA based on average time per review
                    eta_str = ""
                    if completed_reviews > 0:
                        avg_time = total_review_time / completed_reviews
                        remaining_items = total_items - i + 1
                        eta_seconds = avg_time * remaining_items
                        eta_minutes = int(eta_seconds / 60)
                        eta_secs = int(eta_seconds % 60)
                        if eta_minutes > 0:
                            eta_str = f" (ETA: {eta_minutes}m {eta_secs}s)"
                        else:
                            eta_str = f" (ETA: {eta_secs}s)"
                    print(f"[{i}/{total_items}] Processing commit {sha_short}...{eta_str}")

                # Execute review with timing
                start_time = time.time()
                result = workflow.execute_review(commit, commit_output_dir=commit_dir)
                elapsed_time = time.time() - start_time

                if args.debug:
                    print(f"Review completed in {elapsed_time:.2f} seconds")

                # Re-evaluate if no issues found and review completed suspiciously fast
                if args.reevaluate_threshold > 0 and len(result.findings) == 0 and elapsed_time < args.reevaluate_threshold:
                    if args.verbose:
                        print(f"  No issues found in {elapsed_time:.1f}s — re-evaluating...")
                    reeval_start = time.time()
                    result2 = workflow.execute_review(commit, commit_output_dir=commit_dir)
                    reeval_elapsed = time.time() - reeval_start
                    if len(result2.findings) > 0:
                        if args.verbose:
                            print(f"  Re-evaluation found {len(result2.findings)} issue(s) — using re-evaluation result")
                        result = result2
                        elapsed_time = reeval_elapsed
                    elif args.verbose:
                        print(f"  Re-evaluation confirmed: no issues found")

                # Update timing statistics for ETA calculation
                total_review_time += elapsed_time
                completed_reviews += 1

                # Create output directory after successful review
                os.makedirs(commit_dir, exist_ok=True)

                # If --force and directory exists, clean up old review files
                # (do this AFTER review succeeds but BEFORE writing new files)
                if args.force and os.path.exists(commit_dir):
                    old_files = [
                        os.path.join(commit_dir, "review-metadata.json"),
                        os.path.join(commit_dir, "review-pre-verification.json"),
                        os.path.join(commit_dir, "review-inline.txt"),
                        os.path.join(commit_dir, "review-inline.json"),
                        os.path.join(commit_dir, "review-fix-patches.diff"),
                    ]
                    for old_file in old_files:
                        if os.path.exists(old_file):
                            os.remove(old_file)
                            if args.debug:
                                print(f"Removed stale file: {old_file}")

                # Generate pre-verification metadata if we have pre-verification findings
                # This saves all information needed to re-verify findings later
                if result.pre_verification_findings and len(result.pre_verification_findings) > 0:
                    pre_verification_metadata = metadata_gen.generate_pre_verification_metadata(
                        commit,
                        result.pre_verification_findings,
                        upstream_verification=result.upstream_verification,
                        categories=result.categories,
                        subsystems=result.subsystems_loaded,
                        code_context_formatted=result.code_context_formatted,
                        backport_comparison=result.backport_comparison
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
                    upstream_verification=result.upstream_verification,
                    backport_comparison=result.backport_comparison,
                    elapsed_time=elapsed_time,
                    model_name=args.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens
                )
                report_json = json_formatter.format_report(
                    commit,
                    result.findings,
                    summary=result.summary,
                    upstream_verification=result.upstream_verification,
                    backport_comparison=result.backport_comparison,
                    elapsed_time=elapsed_time,
                    model_name=args.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens
                )
                metadata = metadata_gen.generate(
                    commit, result.findings,
                    elapsed_time=elapsed_time,
                    model_name=args.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    backport_comparison=result.backport_comparison
                )

                # Write output files to commit directory
                report_path = os.path.join(commit_dir, "review-inline.txt")
                json_path = os.path.join(commit_dir, "review-inline.json")
                metadata_path = os.path.join(commit_dir, "review-metadata.json")

                with open(report_path, 'w') as f:
                    f.write(report_text)

                metadata_gen.save_json(report_json, json_path)
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
                for line in error_msg.splitlines():
                    print(f"  {line}", file=sys.stderr)

                # Suggest host reset if fatal error and not already enabled
                from llm_integration.error_detector import is_fatal_host_error
                if (is_fatal_host_error(e) and
                    not getattr(args, 'enable_host_reset', False) and
                    not config.ENABLE_HOST_RESET):
                    print(f"  Suggestion: This appears to be a host connectivity issue.", file=sys.stderr)
                    print(f"              Try --enable-host-reset to automatically recover.", file=sys.stderr)
                # For timeout errors, suggest solutions
                elif "timed out" in error_msg.lower():
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

        # Show timing statistics in verbose mode
        if args.verbose and completed_reviews > 0:
            overall_elapsed = time.time() - overall_start_time
            avg_time = total_review_time / completed_reviews
            print(f"  Time: {int(overall_elapsed/60)}m {int(overall_elapsed%60)}s total, {avg_time:.1f}s avg per review")

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
