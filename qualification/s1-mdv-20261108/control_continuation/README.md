# CTRL-1: align one-slow planning with its frozen fast continuation

Parent: `b2646b4cbf19817145c9cb680d95333a267d19f4` (PR #5374).
The earlier one-slow adapter executed fast decisions after its root MPC call,
while the planner forecast future MPC actions and fees. This opt-in v2 adapter
forecasts and executes the same retained fast checkpoint after the root.
It does not replace the sealed v1 study or change its recorded results.

`OneSlowControllerV2` binds the scenario, pre-charge root, utility profile and
fast checkpoint. Root scores include its slow invocation fee and every future
fast fee. Forecasting covers the full remaining horizon. An incomplete root
comparison exposes no complete values, retains the full fee and uses the legal
fast fallback in the already charged state. Checkpoint drift is rejected.

## Regression evidence

| Constructed case | Old one-slow | v2 |
| --- | ---: | ---: |
| Root action | STOP | REPAIR |
| Root credits / simulated seconds | 4 / 1 | 4 / 1 |
| Forecast calls | 44 | 19 |
| Actual nested utility | 0.2495000000 | 0.4327160493 |

The case uses prior 1/3, horizon 2, repair probability 2/3 and risk 0.25.
It is a constructed regression, not new holdout evidence. v2 executes
repair then execute, with one slow call and five total controller credits.

Nine behavioral tests passed on Linux, including 24 complete root-action
comparisons with zero forecast/evaluation difference. An independent evaluator
also checked 36 configurations, 72 root values and 440 successor decisions;
the maximum observed difference was zero. The non-additive test distinguishes
nested entropic utility (0.0127655792) from a flattened path computation
(0.0217181732) at risk 0.7.

On native Mac, the nine tests ran together with eight companion strong-control
tests: 17 normal and 17 optimized tests passed. The source projection and
receipt name this combined scope; the smaller PR's test count is nine.
`just fmt`, Ruff 0.15.13 and whitespace checks passed, with AST equality to
the tested code and no local rerun after formatting. No full workspace run is
claimed. `native/` and `independent-review/` retain the relevant receipts.

## Use and remaining scope

```python
policy = OneSlowControllerV2(scenario, root_before_charge, profile, frozen_fast)
decision = policy.choose(scenario, root_before_charge)
forecast = policy.forecast
```

The old training entry and repeated learned router are unchanged. Training a
repeated router against its actual continuation remains separate work.
Scientific qualification is **HOLD** and production adoption **NoUpdate**.
Declared invocation prices are not measurements of full physical cost.
