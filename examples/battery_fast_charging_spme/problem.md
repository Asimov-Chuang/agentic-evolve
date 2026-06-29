# Battery Fast Charging SPMe

Design a staged fast-charging policy for a lithium-ion cell. The evaluator uses a reduced electrochemical-thermal-aging surrogate inspired by SPMe-T-Aging. It rewards charging from SOC 0.10 to SOC 0.90 quickly while avoiding voltage, thermal, plating, and aging stress.

## Submission Contract

Submit one Python file that defines:

```python
def build_charging_policy() -> dict:
    ...
```

The returned dict must contain:

```python
{
    "currents_c": [3.4, 2.8, 2.0, 1.2],
    "switch_soc": [0.22, 0.52, 0.78],
}
```

Rules:

- `currents_c` is a list of C-rate charge currents.
- `switch_soc` is a strictly increasing list of SOC thresholds.
- If there are `N` current stages, `switch_soc` must have length `N - 1`.
- Stage count, current bounds, and threshold bounds are defined in `references/battery_config.json`.
- Charging starts at the configured initial SOC and stops when target SOC is reached.

## Objective

Maximize `combined_score`. The score combines:

- shorter charging time,
- smaller SEI-aging loss,
- smaller plating loss and plating-margin stress,
- lower thermal stress,
- lower soft voltage excursion.

## Hard Constraints

Any hard violation makes the candidate invalid and gives score 0:

- terminal voltage must never exceed the hard cutoff,
- cell temperature must never exceed the hard cutoff,
- plating margin must never fall below the hard margin,
- the policy must reach target SOC within the configured horizon.

## Useful Metrics

The evaluator reports `charge_time_s`, `max_temp_c`, `max_voltage_v`, `min_plating_margin_v`, `plating_loss_ah`, `aging_loss_ah`, component scores, soft violation flags, and the final `combined_score`.

In pro mode, the archive includes `raw-artifact.json` with a per-step trajectory: SOC, stage index, current, voltage, temperature, plating margin, cumulative losses, and cutoff events. The analyzer may use that trajectory to diagnose which SOC bands and stages are limiting the policy.
