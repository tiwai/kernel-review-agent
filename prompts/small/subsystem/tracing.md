# Tracing Subsystem Details

## Trace Event Definition and String Handling

`TRACE_EVENT` field macros in `TP_STRUCT__entry()`:

| Macro | Purpose |
|-------|---------|
| `__field(type, name)` | Fixed-size scalar field |
| `__array(type, name, len)` | Fixed-size embedded array |
| `__string(name, src)` | Dynamic string; source captured automatically |
| `__vstring(name, fmt, ap)` | Dynamic string from `va_list` |

Assignment rules in `TP_fast_assign()`:
- `__assign_str(name)` takes only the field name (single arg); source is implicit from `__string()` declaration
- `__assign_vstr(name, fmt, va)` formats into a `__vstring()` field
- No side effects in `TP_fast_assign()` — it only runs when tracing is active

Use `TRACE_EVENT_CONDITION` / `TP_CONDITION` to skip ring buffer allocation and `TP_fast_assign()` when a condition is false, avoiding expensive dereferences in the inactive path.

## Tracepoint Probe Registration and RCU

Tracepoint callbacks execute in RCU read-side critical sections: non-faultable tracepoints use `preempt_disable_notrace()`, faultable syscall tracepoints use RCU Tasks Trace.

- Probes registered via `tracepoint_probe_register()` or `rv_attach_trace_probe()` must remain valid until after `tracepoint_synchronize_unregister()` (issues both `synchronize_rcu_tasks_trace()` and `synchronize_rcu()`)
- Tracepoints are gated by `static_branch_unlikely()` on `STATIC_KEY_FALSE_INIT`; zero-probe path is a NOP
- Probe functions must not sleep in non-faultable context; faultable tracepoints (`DECLARE_TRACE_SYSCALL` / `TRACE_EVENT_SYSCALL`) allow sleepable operations

## Tracepoint Kconfig Dependencies

Kconfig dependencies must match the exact build-time availability of any consumed tracepoint. Check the Makefile and Kconfig guards for the file containing `CREATE_TRACE_POINTS`.

Example: `page_fault_kernel`/`page_fault_user` (from `include/trace/events/exceptions.h`) are instantiated in arch fault handlers. On RISC-V, `fault.o` requires `CONFIG_MMU`; on x86 `CONFIG_MMU` is always `y`.

```kconfig
# WRONG: RISC-V can be NOMMU
depends on X86 || RISCV

# CORRECT
depends on X86 || RISCV
depends on MMU
```

## Quick Checks
- No blocking operations in non-faultable trace context
- `__assign_str()` takes only the field name (single argument)
- Tracepoint names follow `subsystem_event` convention
- Exactly one `.c` file per tracepoint header defines `CREATE_TRACE_POINTS`
- Kconfig dependencies match build-time availability of any consumed tracepoints
