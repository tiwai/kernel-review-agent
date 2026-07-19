# Perf Tools Subsystem Details

## Tool API Callbacks

Omitting event callbacks in `struct perf_tool` silently drops events. In pipe mode, missing `perf_event_header_attr` callbacks prevents evlist/evsel creation.

- Unregistered event types are silently ignored
- Any tool registering `.mmap` must also register `.mmap2` (and vice versa)
- In pipe mode, verify attribute and feature callbacks are registered to populate evsels and `struct perf_env`

## Build Feature Detection and Conditional Compilation

Feature checks in `tools/build/feature/test-*.c` set `-DHAVE_*_SUPPORT` flags via `Makefile.config`. Missing guards or stubs break compilation when optional libraries are absent.

- Guard feature-dependent logic with `#ifdef HAVE_*_SUPPORT` or `CONFIG_*`
- Headers must provide dummy inline stubs (returning `-ENOTSUPP` or `NULL`) when the feature define is absent
- Keep `Makefile.config`, feature makefiles, and header guards strictly synchronized

## perf.data Header Validation

Pipe mode does not support seek; attributes and features arrive as synthesized events. `perf_env` is populated by `perf_session__new()` for files, but requires event processing in pipe mode, and is explicitly created in live mode.

- Accessing `perf_env` fields without verifying initialization is a bug

## Architecture-Specific Code and Cross-Platform Analysis

Code in `tools/perf/arch/` only runs on the host architecture, breaking cross-platform analysis of foreign `perf.data` files.

- `tools/perf/arch/` is only for host-execution logic (native PMU probing, hardware registers)
- For architectural variations during analysis, inspect `e_machine` dynamically via `struct perf_env`, session, machine, thread, or evsel structures

## Reference Count Checking and Pointer Handles

With `REFCNT_CHECKING` (enabled by ASAN/LSAN), reference-counted structs (`thread`, `maps`, `dso`) use pointer handles via `DECLARE_RC_STRUCT`. Imbalanced counts cause leaks or use-after-free.

- Every `_get()` or `_new()` acquisition must be paired with a matching `_put()`
- Never access struct fields after calling `_put()`; the handle is invalidated
- Use explicit `_get()`/`_put()` helpers; avoid raw pointer assignment

## Quick Checks

- **Callback error paths**: Verify callback errors trigger full cleanup before return.
- **Nested `openat`/`fdopendir`**: Track each resource separately and verify cleanup ordering.
- **Tool API callbacks**: Verify `.mmap`/`.mmap2` are paired and `.attr` is handled in pipe mode.
- **Feature detection guards**: Verify `HAVE_*_SUPPORT`/`CONFIG_*` guards and header fallback stubs.
- **`perf_env` validation**: Verify fields are checked for initialization before access.
- **Cross-platform analysis**: Verify arch logic queries `e_machine` dynamically, not `tools/perf/arch/`.
- **Reference count balancing**: Verify every `_new`/`_get` handle has a matching `_put` before scope ends.
