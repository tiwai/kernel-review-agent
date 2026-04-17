# Kernel Review Prompts

This directory contains systematic Linux kernel review protocols and subsystem-specific
analysis guides.

## Source

These prompts are from the **review-prompts** project maintained by Chris Mason:

- Repository: https://github.com/masoncl/review-prompts
- Original location: `kernel/` directory in that repository
- License: MIT License

## License

Copyright (c) 2024 Chris Mason

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Contents

### Core Review Protocol
- **review-core.md**: Main 5-task review workflow
- **technical-patterns.md**: Comprehensive bug patterns and kernel topics
- **false-positive-guide.md**: Verification checks to eliminate false positives
- **callstack.md**: Bidirectional callstack analysis methodology
- **inline-template.md**: LKML-compliant formatting guidelines

### Subsystem Guides
The `subsystem/` directory contains 51 specialized guides for kernel subsystems:
- Memory management (MM): VMA, folios, page tables, allocators, etc.
- Concurrency: RCU, locking, synchronization primitives
- Networking: sockets, skb, protocols
- BPF: verifier, maps, kfuncs
- Filesystems: VFS, btrfs, NFSD
- Hardware: block, DRM/GPU, PCI, TTY
- And many more...

See `subsystem/subsystem.md` for the complete index and trigger patterns.

## Usage in This Agent

The kernel-review-agent loads these prompts dynamically based on:
1. The review task being performed (categorization, analysis, verification)
2. The subsystems affected by the commit (automatic pattern matching)
3. The type of changes detected (control flow, resource management, locking, etc.)

The prompts guide the LLM to perform systematic, evidence-based regression analysis
focused on code changes rather than subjective style or message quality.
