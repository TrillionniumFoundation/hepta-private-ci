# Observation contract before fitting

`control_observations.py` defines bounded public states and complete-case labels
without importing or fitting a model. `control_test_fixtures.py` supplies a fully
manufactured schema example. Its flags exercise validation, not authentication.

Implementation labels require complete observed candidate/payload continuity;
unknown stages stay unknown. Value labels require separately completed STOP and
one-continuation branches with matching source, snapshot, evaluator and cost
profiles. All eight declared cost categories must be known in common utility
units. Missingness assumptions, observer authentication and complete physical
cost coverage remain external obligations. Neither label establishes usefulness.

Four observation-contract tests are independent of shadow-head fitting:

```sh
PYTHONPATH=scripts python -m unittest ndu_real_runtime.test_control_observations -v
```
