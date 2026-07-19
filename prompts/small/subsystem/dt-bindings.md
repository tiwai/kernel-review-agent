# Device Tree Bindings Subsystem Details

## Compatible String Conditional Blocks

Adding a new compatible string without updating all existing `if-then` blocks in the YAML schema causes invalid device tree configurations to silently pass validation.

Each `if:properties:compatible:contains:enum:` block that lists prior generations must include the new string if hardware shares the same constraints. Properties commonly guarded by conditionals:

| Property | Typical constraint |
|----------|-------------------|
| `interrupts` | `maxItems`, `minItems` |
| `clocks` | Number and order |
| `resets` | Reset line count |
| `power-domains` | Domain count |
| `required` | Which properties must be present |
| `reg` | Number and meaning of register regions |

## Hardware Variant Required Properties

When a hardware variant gains provider capabilities, the binding must add corresponding properties to `required` with `const` constraints:

| Capability | Required properties |
|------------|---------------------|
| GPIO controller | `gpio-controller`, `#gpio-cells` |
| PWM output | `#pwm-cells` |
| Clock provider | `#clock-cells` |
| Interrupt controller | `interrupt-controller`, `#interrupt-cells` |
| Reset provider | `#reset-cells` |

Cell-count properties must have a `const` matching the hardware (e.g., `#gpio-cells: const: 2`). The `examples` section must include all required properties to pass `dt_binding_check`. If conditionals become unwieldy, split into a separate YAML file.

## `$id` Path Consistency

The `$id` field must be `http://devicetree.org/schemas/<path-relative-to-bindings-dir>.yaml#`, exactly matching the file's location. Mismatches break `$ref` resolution and may produce silent validation failures.

```yaml
# File: Documentation/devicetree/bindings/gpio/vendor,device.yaml
$id: http://devicetree.org/schemas/gpio/vendor,device.yaml#  # CORRECT
$id: http://devicetree.org/schemas/vendor,device.yaml#       # WRONG
```

Common causes: missing subdirectory component, stale name from `.txt`-to-`.yaml` conversion, copy-paste without path update.

## Quick Checks

- New generation-marker compatible string: verify all `if` blocks covering prior generations include the new string.
- New provider capability in a variant: add corresponding properties to `required` with `const` constraints.
- `$id` path must exactly match file location; especially error-prone in `.txt`-to-`.yaml` conversions.
- Related files in the same family may need matching updates.
