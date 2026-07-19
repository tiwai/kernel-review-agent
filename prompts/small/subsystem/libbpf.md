# Libbpf Public API Error Handling

## errno Convention

Public libbpf API functions (`LIBBPF_API` in `tools/lib/bpf/` headers) must set `errno` on all error paths via three wrappers in `libbpf_internal.h`:

- `libbpf_err(ret)`: integer-returning APIs; sets `errno = -ret`, returns `ret`
- `libbpf_err_ptr(err)`: pointer APIs with known error code; sets `errno = -err`, returns `NULL`
- `libbpf_ptr(ret)`: pointer APIs wrapping `ERR_PTR()`-returning internals; sets errno and returns `NULL` on error, else returns `ret`

## Which Functions Need Wrappers

- **Public APIs** (`LIBBPF_API` or in `libbpf.map`): all error returns must use wrappers
- **Internal/static functions**: do NOT use wrappers (use kernel-style negative codes or `ERR_PTR` internally)

Wrappers must be on the `return` statement itself, not applied earlier.

## Return Type Patterns

```c
// Integer
return libbpf_err(-EINVAL);

// Pointer, known error
return libbpf_err_ptr(-ENOMEM);

// Pointer, from ERR_PTR-returning internal
return libbpf_ptr(internal_func());
```

## LIBBPF-001: Missing errno on Public API Error Paths

**REPORT as bugs** — public API functions returning errors without the appropriate wrapper:

- `return -EINVAL;` instead of `return libbpf_err(-EINVAL);`
- `return NULL;` instead of `return libbpf_err_ptr(-ESOMETHING);`
- `return ERR_PTR(-EINVAL);` — public APIs must never return `ERR_PTR`; callers check for `NULL`
- Wrapper applied earlier in function but a later path returns unwrapped
