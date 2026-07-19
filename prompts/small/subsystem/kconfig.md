# Kconfig Subsystem Details

## Config Symbol References

Silent build failures result from referencing non-existent config symbols in `select` or `depends on`.

- Every `select FOO` and `depends on FOO` must match an actual `config FOO` definition in the tree
- Watch for typos between similar prefixes: `QCM_` vs `QCS_`, `IMX8M_` vs `IMX8MM_`
- Verify selected symbol names by searching for their `config` definition

## Dependency Propagation

`select B` in config A bypasses B's own `depends on`, causing Kconfig `unmet direct dependencies` warnings when A is enabled on platforms where B cannot be.

- When `config A` selects `config B`, A must have dependencies compatible with (same or stricter than) B's `depends on`
- Common case: if B has `depends on ARM64 || COMPILE_TEST`, A must too

```
# WRONG
config QCS_DISPCC_615
    select QCS_GCC_615   # QCS_GCC_615 depends on ARM64 || COMPILE_TEST

# CORRECT
config QCS_DISPCC_615
    depends on ARM64 || COMPILE_TEST
    select QCS_GCC_615
```

## Cross-Config Consistency

When multiple related configs are added together (e.g., same SoC family), inconsistencies indicate copy-paste errors.

- Compare new configs with existing similar configs in the same file
- Related configs (e.g., `QCS_DISPCC_615`, `QCS_GPUCC_615`, `QCS_VIDEOCC_615`) must follow the same dependency/select patterns
- Any deviation from the pattern should be verified as intentional

## Architecture-Specific Symbols in COMPILE_TEST Drivers

Drivers with `depends on ARCH_FOO || COMPILE_TEST` can build on any arch; using `select ARCH_SPECIFIC_SYMBOL` in such drivers causes unmet dependency warnings on other architectures.

- Use conditional selection: `select SOME_SUBSYSTEM if ARM64`
- Or change to `depends on SOME_SUBSYSTEM` so the driver is restricted to where the infrastructure exists

## Quick Checks

- **Selected symbol existence**: Every `select FOO` must reference a real config symbol
- **Dependency inheritance**: Selector must have dependencies compatible with the selected symbol's `depends on`
- **Naming consistency**: Check for typos by comparing with related configs in the same subsystem
- **COMPILE_TEST with arch-specific select**: Verify all `select` targets are available on all architectures
