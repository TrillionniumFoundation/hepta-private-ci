# History, refractory-law and Call component study

This is a new, independently identified small-CPU study of the adaptive backend.
It does not rerun a historical experiment or inherit a result from the frozen
N256 experiment. Its source list includes this directory, the adaptive backend
and the existing spatial/HX implementations; baseline HX/generator Git blobs
must match integration `0cee57ca617e0324e2df8e9447a2c075a6c76952`.

```sh
python -m qualification.hcsn_history.history_benchmark \
  --experiment-id p1-history-call-20261121-v1 \
  --output /absolute/path/to/new/p1-history-call-20261121-v1 \
  --max-seconds 90 --repeats 12
```

The output directory must not exist. `events.jsonl` is flushed after each
completed measurement, and `summary.json` records completion, a budget stop or
failure. Failed/partial receipts must be retained under their original identity.
The wall budget is checked between small CPU operations. It is not a process
kill timer. Runtime import/startup precedes the reported experiment timer.
The benchmark sets one Torch CPU thread, uses no GPU and performs no fitting.

## What the history measurement establishes

The declared profiles are FP64 and FP32 trainable layers/outputs with FP64
transport/state. Both use six active cells, four content channels, reflecting
upper handling and four independent samples. Phase counts are 1, 2, 4 and 8.
Each case streams 512 observation intervals of 0.1 time unit under
`torch.no_grad()`, with checkpoints at 32, 128 and 512. Each sample receives its
own deterministic, time-varying input-dependent drift. No output sequence or
autograd history is retained.

The tensor payload should remain exactly

`8 * [B * (1 + K) * (N + R + 1) + B]` bytes.

The script measures this payload at every step and rejects growth. It records
probability conservation, signed-content balance and bounds, the integer clock,
active/refractory/escape mass, cumulative expected events, wall time and process
CPU time. Step timings include the backend's invariant checks and all feature
calculations. Host timings additionally include input construction, measurement
bookkeeping and checkpoint receipts. Tensor payload excludes parameters,
temporary matrices, the Python/Torch runtime and training tapes; it is not a
claim about process peak memory or full BP storage.

Samples are arranged in two pairs. The odd member receives an intervention of
`[1, -0.5, 0]` on its first observation; each pair then receives exactly the same
future input. Probability/content differences and feature differences are
reported at each checkpoint. This is a concrete response to past input. It does
not establish a task's recoverable memory capacity. A fixed-dimensional state
can forget the intervention, and small late differences are not a failure of
the storage bound. The writer acts once per observation, so additional
observations would change the model even at the same elapsed time.

## What the phase measurement establishes

With R phases and declared mean refractory duration h, each stage has rate R/h.
The waiting time is Erlang, with mean h and variance h squared divided by R.
The script independently obtains its first two moments from the transient
generator and rejects disagreement with those formulas. It also reports 8,192
seeded waiting-time samples, sample mean/variance, mean absolute deviation from
h, the coefficient of variation and probability of returning before h/2.

Increasing R concentrates delay around h but increases state/matrix size. There
is no strict minimum waiting time for any finite R. This does not reproduce an
exact deterministic-delay queue. In particular, the CDF at h approaches one
half; pointwise convergence cannot be claimed at the discontinuity of the
deterministic-delay CDF. Delay-law error, temporal input freezing and spatial
discretization are different approximations.

## Full HX equity adapter and its objective

`call_adapters.py` reuses the complete existing
`qualification/hcsn/tensor.py` equity implementation, including its prepared
parameter path. It does not replace equity with a simple constant-carry formula.
For the adaptive grid's relative margin x, it defines a separate financial
coordinate `V_HX = b_HX * exp(x)` using HX's own parameter-derived default
boundary. The replacement feature is

`sum_active p_i * E_HX(x_i; theta_HX) / b_HX`.

Refractory and escaped population contribute zero to this feature. The adaptive
model's absolute log boundary is not identified with the financial asset value
or with `b_HX`. This adapter is an explicit feature experiment: the financial
equity objective is different from the backend's regenerative finite-policy
Call, which values future phase returns and charges future event costs. Their
values are not expected to match, and their runtime ratio is not a speedup for
solving the same objective.

`policy_call` independently reconstructs the backend Call from the same
generator, reward and event intensity. The benchmark checks agreement with the
last feature returned by `step`. It checks full-HX direct/prepared/cached
agreement and direct/prepared derivatives with respect to all nine financial
parameters, margin nodes and ambient probability coordinates. Fresh graphs are
built for every backward evaluation. When SciPy is available, the independent
scalar quadrature oracle is checked on all six declared margin nodes; otherwise
the oracle is explicitly reported as unavailable. This default-domain check
does not certify all historical extreme-domain stress cases.

## Cost interpretation and legal reuse

Separate timings cover the finite-policy solve with a rebuilt or already
available generator; full HX direct evaluation; full HX fresh preparation;
reuse of a frozen parameter context; construction/application of a detached
fixed-grid curve; and fresh forward/backward calculations. The recorded batch,
state size, parameter targets, dtype and thread count define their scope.
Direct and prepared HX implement the same function. HX and the finite-policy
Call have different parameter targets and economic/neural semantics.

The direct normalized-feature adapter calls the public `hx_equity` and
`hx_boundary` functions separately. They each construct parameter components;
the prepared API exposes its boundary as part of the context. Thus their
reported ratio includes this public-API preparation difference. Passing an
explicit boundary to `hx_equity` does not remove its internal component
construction. These measurements must not be described as a pure special-
function speedup with identical preparation work.

The finite-policy generator already exists in `step`, so its reused-generator
solve is the relevant isolated component. A frozen financial curve is valid
only while financial parameters, margin nodes, dtype and device remain fixed.
`FrozenHXCurve` rejects trainable source nodes/parameters and checks grid/dtype/
device on application. Its parameter tuple identifies the intentionally fixed
financial objective. Changes to those parameters require a new cache; curve
preparation time and payload are reported separately. Applying a cache can
still propagate gradients through the population, but does not train the
frozen financial parameters or nodes.
The frozen dataclass prevents field reassignment, not in-place mutation of its
Torch tensors. It is a trusted-caller research cache: callers must not mutate
the cached nodes or values. It is not an authenticated immutable artifact.

`replace_call` changes the final output column. A zero replacement is the
functional no-Call arm. The adaptive backend currently computes its original
Call before either an output mask or a posthoc replacement. Consequently these
functional ablations do not save the original solve, and an HX substitution
adds its measured component cost to that backend. The study makes no
end-to-end training speedup, equal-task-accuracy or multimodal scaling claim.
