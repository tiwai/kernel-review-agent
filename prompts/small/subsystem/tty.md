# TTY/Serial Subsystem Details

## UART Device Registration and Callback Timing

`uart_add_one_port()` may synchronously invoke driver callbacks during registration via `uart_configure_port()`. If these callbacks call runtime PM APIs before `pm_runtime_enable()`, circular wait conditions occur.

**Rule:** Call `pm_runtime_enable()` / `devm_pm_runtime_enable()` BEFORE `uart_add_one_port()` if any `uart_ops` callback uses runtime PM APIs.

```c
// WRONG
ret = uart_add_one_port(drv, uport);  // May call ops->pm() before PM is ready
devm_pm_runtime_enable(dev);

// CORRECT
devm_pm_runtime_enable(dev);
ret = uart_add_one_port(drv, uport);
```

**Callbacks invoked during `uart_add_one_port()`** (via `uart_configure_port()`):
- `uart_ops->config_port()` — when `UPF_BOOT_AUTOCONF` set
- `uart_ops->pm()` — via `uart_change_pm()` to power on/off
- `uart_ops->set_mctrl()` — to de-activate modem control lines
- `port->rs485_config()` — if `SER_RS485_ENABLED` set

## 8250 Module Architecture

The 8250 driver splits into two modules with a **unidirectional** dependency (`8250.ko` depends on `8250_base.ko`). Violating this causes undefined symbols or circular deps, visible only with `CONFIG_SERIAL_8250=m`.

| Module | Key files |
|--------|-----------|
| `8250_base.ko` | `8250_port.o`, `8250_dma.o`, `8250_dwlib.o`, `8250_fintek.o`, `8250_pcilib.o`, `8250_rsa.o` |
| `8250.ko` | `8250_core.o`, `8250_platform.o`, `8250_pnp.o` |

**Rule:** Code in `8250_base.ko` MUST NOT call symbols from `8250.ko`. When functions move between files, check `Makefile` for `8250-y +=` vs `8250_base-y +=` assignments. Cross-module calls require `EXPORT_SYMBOL_GPL()`; reverse dependencies require redesign (move code back, or use function pointer indirection/registration callbacks).

## Quick Checks

- **Runtime PM ordering:** `pm_runtime_enable()` must precede `uart_add_one_port()` if any `uart_ops` callback uses runtime PM APIs.
- **Callback timing:** `pm()`, `config_port()`, `set_mctrl()`, `rs485_config()` may fire synchronously during `uart_add_one_port()`.
- **8250 code motion:** Check `Makefile` module assignments; `8250_base.ko` must not depend on `8250.ko`.
