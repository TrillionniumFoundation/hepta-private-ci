# Physical flow integration

This opt-in research path joins the physical clock, content feedback, analytic
regeneration reference, conditional readout, and real streaming encoder study.
Historical default model configurations retain their legacy implementation.

## State and clock contract

`FlowSemantics("event_mask")` requires an explicit binary per-stream write mask.
`FlowSemantics("continuous_write", write_rate=k)` requires a finite positive
rate in inverse seconds. Pass elapsed physical seconds to `step_physical`.
The frozen interval law propagates population, marked content, and integrals
with the same finite generator. A snapshot alone does not bind a write law;
persist the model configuration with the state.

The output names distinguish expected event count, marked event count,
first-event probability, occupation rate, and continuation value. Diagnostics
add discounted first-event expectation and occupation integral. Initial
refractory population remains in the risk calculation. The first-event
probability for each interval must not be added across intervals as if it
were a whole-window probability. Event counts and occupation integrals are
additive. An immediate boundary-remap event is counted once.

Held-input, held-control subdivision tests cover both physical write laws.
Content feedback is recomputed at declared observation boundaries. Adding a
feedback update changes that control path and is not a subdivision invariant.
Exposure pooling uses physical durations but endpoint feature quadrature is
not an exact occupation integral. Its first-hit exposure summary is labelled
as a per-second exposure statistic, not a hazard.

## Content and reference process

`feedback_mode` routes bounded functions of previous active and refractory
marked content into drift, boundary, and reward. The `none` and enabled modes
have the same stored parameter count and state shape; disabled projection
parameters are inactive. The reward route changes the value calculation
without changing population propagation. `feature_bank="drop_value_risk"`
and `"ordinary_tanh"` retain feature width and still pay the full flow cost.

See `../hcsn_adaptive/REGENERATIVE_REFERENCE.md` for the independent constant
drift/diffusion, fixed reset, deterministic refractory reference. Its first
passage risk, repeated-event moments and regenerative value have explicit
domains. It is a mathematical comparison object, not a claim that a finite
Erlang refractory approximation is exact.

## Direct solution, BP and edits

`adaptation.adapt_model` compares KEEP, a fixed-encoder readout solve,
profiled outer BP, joint BP, or explicitly supplied bounded encoder edits.
The conditional readout uses one centered SVD for all target columns with an
unpenalized intercept. The profiled arm still differentiates the encoder and
re-solves the readout after each update. Old-task checks cover only the supplied
next-sensor preservation windows, not global knowledge retention.

Every candidate has a saved state, state digest, development decision and cost
ledger. Editing support and norm bounds are checked before executing an edit.
Candidates start from a common incumbent. A separate conditional head solve
is charged to each edit. Total wall time is measured directly; overlapping
phase timings must not be summed. Dynamic generator propagation currently
uses dense matrix exponentials and has no prepared-cache speed claim.

## Real streaming comparison

`python -m qualification.hcsn_scale.stream_benchmark CSV OUTPUT --arm ARM --seed SEED`
runs the declared CPU FP64 study. Source preparation is the existing UCI Room
Occupancy Estimation path: chronological splits, purged disjoint windows,
actual timestamps and train-only normalization. Occupancy labels train only
the evaluation probe; encoder updates use next-sensor prediction.

The default plan has ten arms and three seeds. The four HCSN arms are
`hcsn_feedback`, `hcsn_no_feedback`, `hcsn_drop_value_risk` and
`hcsn_ordinary_tanh`. The latter replaces value/risk features with ordinary
bounded input-map features while retaining full content feedback, feature
width, stored parameters and population-state shape. It still pays the full
flow computation. Six causal baselines complete the comparison.

All arms share windows and caps of 64 updates with eight windows per update.
The 600-parameter target, with a relative tolerance of 15%, covers the encoder
and SSL prediction head. Ridge-probe weights are additional; receipts report
both selected probe parameters and their sum with encoder/head parameters.
The persistent tensor-state limit is 8192 bytes per stream. Actual state
capacity is reported and is not identical across architectures; training
autograd tapes and saved output tensors are outside this state accounting.
Development scores select among step 0, 32 and 64; test is scored once after
selection. A selected step zero is retained as NoUpdate, with all training,
selection and final evaluation already performed still charged to that arm.

The 900-second arm budget is a soft work-wall admission rule, checked before
starting each optimizer update. Initial and scheduled evaluations, an admitted
update, final testing and artifact serialization may pass that limit. Receipts
record the stop reason, completed updates and actual budget overrun. Completing
all scheduled updates remains `completed` even if required final work exceeds
the admission budget; it is not a hard process timeout.

`work_wall_seconds` includes data preparation, capacity matching, optimizer
construction, training, development selection, testing and checkpoint/prediction
serialization. It excludes Python/import startup, runtime preflight and the
final result-receipt write. `wall_seconds` remains a compatibility alias for
this same internal measure. An outer launcher records the complete subprocess
cold lifecycle. The training-interval measure includes scheduled evaluations,
so overlapping timing fields must not be added together.

The runner saves the plan before work and records its exact-file SHA-256,
actual Python/Torch/NumPy/ncps versions, model device/dtype, thread counts and
deterministic-algorithm setting. Direct `run_arm` callers must establish the
same single-thread deterministic runtime as the CLI; the runner checks that
the chosen arm and seed belong to the saved plan and that model tensors are
CPU FP64. Bind the source manifest in the outer run ledger. This previously
used dataset is not a prospectively unseen corpus.

CfC uses official `ncps==1.0.1`. The gated-delta baseline implements the
[published recurrent update](https://github.com/fla-org/flash-linear-attention/blob/main/fla/ops/gated_delta_rule/naive.py)
in ordinary PyTorch, not the full optimized architecture. The transformer
uses a causal prefix and reports retained raw-prefix state, not optimized KV.
The LIF baseline is an endpoint single-event surrogate: it emits at most one
spike per source interval and does not solve within-interval event times or
repeated events exactly. Results apply to these explicit small reference
implementations and do not establish superiority to all SNN or Transformer
architectures.
The sensor source is [UCI dataset 864](https://archive.ics.uci.edu/dataset/864/room+occupancy+estimation),
DOI 10.24432/C5P605, distributed under CC BY 4.0.
