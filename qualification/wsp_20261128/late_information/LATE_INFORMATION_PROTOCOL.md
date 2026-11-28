# Late-information route and four-coordinate weight program

Registered before any new intervention or task result is computed. Existing historical
SmallHCSN results and their failures have been read. This is a new controlled task
family and an architecture comparison; the actual parent weights come from the
frozen RAVDESS research checkpoints at source commit
`bc4912ea657864d33b36a57da0b50eb35bee90af`, seeds 47, 83 and 137. No HeptaTrader
deployment, trading return, general foundation-model gain, or replacement of
encoder training is claimed.

## Frozen structural question

The six-step centered-boundary profile updates its law on ticks 0, 2 and 4,
transmits only the previous boundary, reads only receiver features, and has a
separate external baseline. With that baseline held fixed, inputs at ticks 1, 3
and 5 have no path to the final neural residual for any parameter values. Tick-4
input may affect the final receiver signed-event feature, but cannot affect the
receiver probability, value, risk, unsigned event or margin through the last
frozen-law interval. This claim is about this graph and schedule, not arbitrary
Hepta models.

For each of the three real parents run the same source-bound Rust evaluator on
the first 16 original TRAIN queries and six one-tick input interventions. Replace
the selected tick's normalized input by its negative plus 0.125; keep labels and
external baseline byte-identical. Compare complete final feature and score F32
bytes. Predicted exact equalities are tested without a numeric tolerance;
unexpected changes fail the stated structural claim. Ticks 0/2 are sensitivity
controls, not task-quality endpoints. Record every forward and physical residual.

## Minimal experimental architecture

`final_tied_mark_bridge` adds the existing input_mark affine output to the four
receivers' raw signed marks on tick 5 only. It adds no parameters and changes no
probability generator, reset, QVI or learned head. It does activate previously
disconnected existing parameters, so equality of registered parameter counts
does not mean equality of effective capacity. Production defaults and editor
permissions remain unchanged. A request-scoped version uses this route only for
the declared late-price comparison task; normal requests take the old route.

For fixed pre-final physical history, the final signed feature is exactly
offset_j + alpha_j tanh(rec_j + x_last Wmark_j + bias_j), alpha_j >= 0.
Use full physical replay to obtain those coefficients. Verify the reduced
expression against a separate complete bridge forward before fitting. A
float64 derivative of this represented final computation is used for BP;
reported candidates are cast to actual F32 and evaluated through the full route.

## Task and semantic weight program

The task is: wait through a shared, noisy context; after receiving two final
numeric quotes, choose the lower final price. The last input contains quoted
prices, not class labels. Choices have identical histories and non-price final
features; their last price values differ. External baseline is zero. Each
context occurs in an original and a price-swapped pair, producing balanced
labels and an exact 50% upper bound for any policy unable to observe the final
prices. This is a declared controlled task, not a natural-market benchmark.

For receiver j let v_j be its existing head's class-contrast coefficient on the
signed-event feature. Without accessing task labels or outputs, set the existing
price weight Wmark[j,7] to -sign(v_j)*abs(parent Wmark[j,7]); if that magnitude is
zero and v_j is nonzero use 1/16. Zero-v channels keep their original coefficient.
All other parameter bytes remain unchanged. If all v_j are zero, report ABSTAIN.
The existing head is retained. For shared histories the score derivative with
respect to price is sum_j v_j alpha_j Wmark[j,7] sech^2(...), which is nonpositive
and is strictly negative when a live channel is unsaturated. The program edits
at most four of the original 330 registered scalar parameters.

## Arms and accounting

1. Original graph KEEP, and original graph with the compiled price weights.
2. Bridge graph with unchanged weights.
3. Bridge graph with the deterministic sign program.
4. Bridge graph with the sign-reversed price program (negative control).
5. Bridge graph with 64 random four-coordinate directions on the same L2 radius
   as the actual direct delta; select minimum TRAIN cross-entropy with first-index
   ties. Record all directions and costs. No rejected direction is discarded.
6. Bridge graph with 64 fixed Adam BP steps, learning rate 0.03, betas 0.9/0.999,
   epsilon 1e-8, updating those same four coordinates and projecting onto the same
   L2 ball around the parent. The loss is mean binary cross-entropy. No dev-based
   early stopping or retuning. A zero direct radius yields a zero-update baseline.

Direct compilation uses no labels, solves, model calls or objective derivatives.
Random/BP may use TRAIN labels. Shared feature construction, model loading,
evaluation, writing, failures and compilation costs are separately recorded. The
common envelope is 64 optimization objective calls, not a claim of equal actual
work. Report accuracy, CE, Brier, changed coordinates, radius, full forwards,
reduced evaluations, backward steps, wall and CPU time; no accuracy-only speedup.

## Data, sealing, and acceptance

Use NumPy PCG64 with seeds 2026112801 TRAIN (32 contexts, 64 paired queries),
2026112802 DEV (16 contexts, 32 paired queries), 2026112803 final TEST
(40 contexts, 80 paired queries). Each context is independent N(0,0.5) in the
nine normalized inputs for six ticks. Both choices share the full context.
TRAIN quotes are uniform [-1,1], DEV [-1.5,1.5], TEST [-3,3]; enforce an absolute
quote gap of at least 0.2 by deterministic redraw, then include the swapped pair.
Generate TEST only after all candidates and their source/parameter hashes are
sealed. DEV is descriptive only and cannot change selection. The test is new
synthetic input, not new real actors. All three actual parent seeds are reported.

Primary mechanism acceptance requires original-graph equality controls,
mathematical/independent reduced-route agreement within 2e-6 in features and
scores, unchanged physical residual tolerance 2e-9, and at least 95% final-task
accuracy for the sign program on each parent. A correct rank with weak
confidence remains weak calibration and must be reported.

Normal-task retention uses all 32 original RAVDESS RETAIN rows, the same external
baseline, historical labels and ordering. Run the unconditional bridge and the
request-scoped bridge separately. Acceptance for unconditional use requires no
lost correct decisions and CE no greater than parent +1e-6 at every parent.
Failure means REJECT for unconditional use, even if the late task succeeds. The
request-scoped route must reproduce complete original normal-task outputs
byte-for-byte; it is an explicit task mode, not an inferred general solution.

Full computation cap: 120 seconds CPU for native temporal probes and 300 seconds
CPU for the Python experiment, single BLAS thread. No new GPU job, encoder
training, model deployment or automated future task is authorized by this file.
Any exceeded cap, parse error, rejected physical state or mismatch is retained
and cannot be relabeled PASS. Protocol amendments require a new record before
affected results are observed; no silent budget or endpoint changes.
