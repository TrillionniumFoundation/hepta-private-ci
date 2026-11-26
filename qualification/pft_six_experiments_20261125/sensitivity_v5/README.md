# V5 accepted-parent fixed-stencil proposal

**Status: source review only; the accompanying protocol is inactive.** No model,
project test, numerical gate, or training job was run while preparing this proposal.
Only root may register a separately hashed active protocol and spend this budget.

## The distinct question

The retained V4 original-parent result is `FAILED`, with SHA-256
`15fbd987921708767c8143185c0a98a5caeb50e9984b4a88bc629fbf81af4105`.
Its `raw_cost[4]` one-sided slope gaps were approximately 14.773267 and
14.773275 at radii `1e-5` and `5e-6`. The central approximations agreed with
each other and the selected VJP, but the unchanged two-scale resolution gate
failed. The other five coordinate rows passed. That original failure remains a
valid result at its original parent; no V5 outcome replaces it.

The separately accepted, exported, and cold-verified full candidate is a
different parent:

| Identity | SHA-256 |
| --- | --- |
| Complete checkpoint, 9,855 bytes | `87ed31e17899f4ae18cbad3ea7a9b7af05cf42662da4ffd94a1c2c83cde9ef88` |
| Complete tensor state | `9630e1de513658155e8c0c7c6cff13a3954cf49db3534ed3051c49fa035ac66c` |
| Exact cold candidate profile | `1ff30beb31a7033d1c9a6666dc76de9b2f9e93ac5d8467feafcef6db18dce17e` |
| Frozen source binding | `3146e2c56757ff7c818670aa3a9c229b26271c7336d573b1692b91ac8e7a00e9` |
| Accepted trial result | `8fff2a2525bb5ba411532e28fee28d549c491372add6feb2b58a9399d89a446e` |
| Cold verification result | `2e2cee24f0371ca53f148865f1f0f388ef69e4ae4dffb6fc2d8b205afb96c161` |

This candidate changed six parameter elements. Its `raw_cost[4]` is
approximately `-1.2602692602382997e-5`; the retained proposed displacement
from the original zero is exactly that binary64 value. The original large
radius interval would therefore lie between approximately `-2.26026926e-5`
and `-2.60269260e-6`, wholly below zero. This makes the accepted candidate a
specific, already-existing point worth checking. It does not establish that
all QVI, remap, reset, or other intermediate trajectory branches remain smooth.
Because all six coordinates changed, a successful result would not isolate a
causal effect of moving `raw_cost[4]` alone.

The proposed question is simply: **does the same fixed six-coordinate,
two-observation numerical gate pass at this already accepted parent?**

## Unchanged numerical contract

The new entry point imports the pinned, unedited V4 `first_order.py` and imports
only the fixed fixture and coordinates from `verify_first_order.py`. It does not
call the latter module's `execute`, `main`, or `quadratic_checks` functions.

The coordinates remain `raw_cost[4]`, `input_drive.weight[0]`,
`input_mark.weight[0]`, `recurrent.weight[96]`, `readout.weight[0]`, and
`readout.bias[0]`, all at coordinate scale one. The batch contains the same two
initial margins `0.59` and `0.73`, the same four input ticks, and six input
channels. Every AD and FD call rebuilds the complete `initial_state`; no detached
incoming physical state is reused.

The CPU FP64 numerical runtime remains Python `3.14.4`, NumPy `2.5.5`, PyTorch
`2.15.0+cpu`, one intra-op thread and one inter-op thread. The manifest, complete
checkpoint, original source capsule, all five imported V4 source files, and the
new entry point are content-pinned. The existing strict loader reconstructs the
complete original model class, config, tensors, buffers, and `requires_grad`
roster. The candidate uses eight cells, dense execution, `value_risk` features,
full messages, QVI boundaries, and its original `plain_linear` constructor.

The FD radii remain `1e-5` and `5e-6`; `atol=1e-7`, `rtol=3e-5`. At each
coordinate the two central differences must agree, the finer central difference
must match the selected VJP, and the one-sided slope gap must either lie below
`4 * (atol + rtol * scale)` or shrink by at least the original factor `0.75`.
No row is dropped, no tolerance is widened, and no smaller radius is tried.

## Exact source-derived budget

| Operation | Maximum | Source path |
| --- | ---: | --- |
| Candidate checkpoint/model loads | 1 | One call to `small_hcsn_profile.load_profile` |
| AD physical forwards | 1 | One `_fresh_output` in `linearize_fresh` |
| Scalar-output first-order VJPs | 2 | One `torch.autograd.grad` for each of two scalar margins |
| FD baseline physical forwards | 1 | One initial `_fresh_output` in `controlled_finite_difference` |
| FD perturbation physical forwards | 24 | Six coordinates × two radii × two signs |
| Total physical forwards | **26** | `1 + 1 + 6 * 2 * 2` |
| Second-order autograd, quadratic solves, optimizer updates | 0 | No call sites |
| Historical training-matrix runs, known-quadratic reruns | 0 | No call sites |
| Candidate construction/export/adoption | 0 | No call sites |
| Retries or backtracking | 0 | No call sites |
| Wall / CPU seconds | 120 / 120 | Alarm and CPU limits; hard CPU cap 121 seconds for termination |

The model pre-forward and post-forward hooks only observe calls; they do not
change inputs, outputs, weights, or derivative formulas. The report distinguishes
forward invocations from completed forwards. On a completed AD phase, the
source-fixed two-row loop and observed differentiable logits establish exactly
two scalar-output VJP calls. If an exception interrupts that phase, the actual
VJP count is recorded as `null`, with a source-derived upper bound of two;
unobserved calls are not fabricated. `candidate_loads` counts loader invocations,
including an invocation that raises. Re-reading pinned bytes for integrity does
not deserialize another model. There are no child processes in this entry point.

The numerical helpers do not accumulate `.grad`, but the new driver also checks
full state, trainability, existing gradients, config, and module modes before
cleanup. The `finally` block restores all of them, including original gradient
objects and diagnostics. Any unexpected mutation fails the run even if cleanup
succeeds. The report records the complete trainability roster and its hash. It
then revalidates the profile and re-reads the candidate and all three retained
receipt files against their original hashes. Output is exclusively created in a
new directory, so existing results cannot be overwritten.

## Interpretation and fixed stopping rule

Success is named `PASSED_FIXED_NEW_POINT_STENCIL`. It establishes consistency
of the selected first-order calculation with these finite differences at this
one parameter point, on this exact fresh trajectory pair. It permits only this
bounded engineering record to move from untested to passed. It does not prove
classical differentiability, a smooth open neighborhood, mixed-direction
derivatives, other states or inputs, a global FBSDE inverse theorem, unique
weight identification, model superiority, or foundation-model training.

Even if the new `2 x 6` sensitivity matrix passes, its rank is at most two.
At least four coordinate directions remain locally unidentifiable from these
two scalar observations alone. Ridge regularization can select a solution but
cannot add missing data identification. No additional rank computation or
quadratic solve is necessary to establish this dimension bound.

Failure or an inconclusive row, changed identity, runtime mismatch, nonfinite
value, timeout, budget exception, unexpected mutation, or failed restoration
ends the single registered run. Preserve its `RESULT.json` and process log.
Do not change the parent, fixture, coordinates, steps, tolerances, gate, or
runtime; do not rerun to obtain a passing value. A killed process without a
complete report is not a pass and consumes the one attempted run. Any later
question requires a distinct scientific justification and a separately admitted
protocol. This proposal itself does not authorize such follow-up work.

## Root-only activation and invocation

Place `sensitivity_v5/` beside the exact pinned `sensitivity_v4/` and
`native_profile_v4/` directories. The inactive template uses concrete remote
input paths as documentation. Root first registers the input/output paths,
source hashes, fixed budget, and one execution slot; then creates a distinct
active protocol with `ready_for_execution=true` and hashes those exact bytes.
The script refuses the supplied inactive template before importing a framework.

Invocation requires all of `--protocol`, `--protocol-sha256`, `--profile`,
`--material-root`, `--failed-result`, `--accepted-result`, `--cold-result`, and
`--output`. Use the original pinned interpreter:
`/home/alex/pft-six-actual-hcsn-20261125/venv/bin/python`.
The output directory must not exist. No command is executed by this document.

Bootstrap failures occur before creation of a numerical result directory; root
must preserve the process log for those refusals. During the admitted numerical
run ordinary exceptions produce an exclusive `RESULT.json` with `status=FAILED`.
