# Full-equity feature task-quality ablation

This is a separately identified, fixed small experiment completing the quality
side of the Call component-cost study. It contains exactly two synthetic tasks,
three frozen encoder seeds (11, 29, 47) and three arms: 18 trials. It neither
reuses the old N256 identity nor changes the adaptive/history implementations.

| Task | Train / development / test | Observed length |
|---|---:|---:|
| `future_return` | 96 / 48 / 48 | 16 |
| `delayed_recall` | 96 / 48 / 48 | 32 |

Use the existing formal dataset directories. Freeze checks their identities,
training/development shapes and test ID count. It does not load test labels.
The six task/seed groups each have a 120-second budget; the three arms share
their group's work. This is a write-ahead budget checked between operations,
with physical overruns preserved, not a hard process kill timer.

## Controlled comparison

All arms share the exact same FP64 encoder parameters, input-dependent drift,
fixed absolute log boundary zero, complete population state and observation
sequence. The encoder has six active cells, three Erlang phases and four
content channels, with reflecting upper handling. States restart between
independent examples. The encoder is frozen; no BP updates it here.

One backend pass per split produces all three feature variants:

| Arm | Last output column |
|---|---|
| `finite_policy` | Existing finite-policy regenerative continuation value |
| `drop_call` | Zero; the original solve is still executed |
| `full_hx` | Fixed full-HX active population equity feature from `FrozenHXCurve` |

The full-HX feature is `sum_active p_i * E_HX(x_i) / b_HX`. Its nine financial
parameters are fixed at the existing `HXParams` defaults and recorded. Its
financial coordinate is `V_HX=b_HX*exp(x)`. Phase and escape contributions are
zero. This is a different objective from the regenerative Call, not an exact
replacement of that process's value function. With fixed nodes and parameters,
it is a fixed nonlinear basis applied as a linear functional of active mass.
Task performance alone cannot identify financial optimality as its cause.

Each arm concatenates the last feature vector and its time mean. Each uses the
same training-only normalization rule and affine ridge objective:

`mean squared error + 0.001 * sum(non-bias weights squared)`.

Non-Call columns and their normalization statistics are identical. The two
aggregated Call columns have their own arm's training statistics. Every arm has
the same readout coefficient shape and allowed parameter mask; the dropped
columns are zero. Ridge is solved once per arm. Development data do not choose
encoder parameters, boundaries or penalty. The mean development MSE across all
three seeds selects an arm for each task before test opens, with ties resolved
in declared arm order. All 18 predeclared test results are reported, regardless
of selection.

## Cost accounting

The shared backend executes its original Call solve in every arm. The study
charges that encoder computation once, not three times, and separately charges
fixed financial curve construction and the additional HX applications. Curve
parameters, digest, payload size, setup time, full feature extraction time,
shared backend time, incremental HX time and posthoc assembly time are retained.
The write-ahead journal includes fitting, feature extraction and checkpoint
operations, including failures. Test evaluation has a separate cost journal.

This design permits a paired task-quality comparison with a measured incremental
financial-feature cost. It does not measure a backend that skips the original
Call, nor claim an end-to-end training speedup. Shared extraction and all-arm
assembly are explicitly shared costs, not independently timed standalone arms.
Only three frozen encoder seeds are used; report their individual results and
paired differences as well as means. These synthetic tasks cannot establish a
foundation-model or general multimodal advantage.

## Execution and holdout sequence

```sh
python -m unittest qualification.hcsn_equity_ablation.ablation_tests -v

python -m qualification.hcsn_equity_ablation.campaign freeze \
  --output /absolute/path/to/new/p1-equity-quality-20261121-v1 \
  --experiment-id p1-equity-quality-20261121-v1 \
  --future-data /absolute/path/to/formal_future_return \
  --recall-data /absolute/path/to/formal_delayed_recall

python -m qualification.hcsn_equity_ablation.campaign train \
  --output /absolute/path/to/new/p1-equity-quality-20261121-v1

python -m qualification.hcsn_equity_ablation.campaign seal \
  --output /absolute/path/to/new/p1-equity-quality-20261121-v1

python -m qualification.hcsn_equity_ablation.campaign finalize \
  --output /absolute/path/to/new/p1-equity-quality-20261121-v1
```

Root controls the last two commands. Freeze binds source, runtime and exact
dataset bytes. Training writes six group receipts, each containing three arm
results and one encoder/readout payload. The global seal binds every receipt
and payload, including all development choices. Finalization rechecks the whole
seal before an exclusive global holdout claim and before loading either test
split. A later altered choice is rejected, and a consumed claim cannot retry
after a crash. Completed final receipts can be read again without reopening
test data. A failure after the claim leaves partial per-group results/costs and
a failure receipt; it does not become a new test opportunity.

The two behavioral tests verify that only the two aggregated Call columns
change while complete state and encoder parameters remain equal, and that an
absent/changed global seal or an already consumed claim blocks test loading.
