# A time-dependent information barrier and a small weight program

## Result and evidence status

Three actual trained SmallHCSN research checkpoints have a graph-level blind
spot: their neural residual cannot use raw inputs at odd ticks in the fixed
six-tick, boundary-only profile. Changing weights alone does not close that
path. A named final-tick mark connection makes the last observation available.
Within that changed graph, an analytic sign program using the existing head
compiles a lower-price comparison into at most four existing weights.

The new controlled task succeeds at all three parents. Unconditional use of
the changed graph damages the historical RAVDESS task and is rejected. An
explicit task-scoped route preserves normal outputs exactly. Random search and
ordinary four-parameter BP also solve the new task; BP produces better
cross-entropy. These results establish one useful circuit repair with a narrow
task contract, not a general superiority of direct editing or a trading gain.

The execution status is **COMPLETED_WITH_PROTOCOL_DEVIATION**. An independent
review found that the full-model versus reduced-expression comparison required
before fitting was performed after candidates were sealed. All comparisons
passed later without changing any candidate, but that does not repair the
original chronology. `PROTOCOL_DEVIATION_01.md` records this explicitly. The
protocol, original source, all candidates, costs and negative outcomes remain
unchanged.

## Actual source and parameters

The three parents are the frozen centered RAVDESS models at
`hepta-private-ci@bc4912ea657864d33b36a57da0b50eb35bee90af`, seeds 47, 83 and 137.
Their complete `.pt` SHA256 values are:

| Seed | Original checkpoint SHA256 |
| --- | --- |
| 47 | `92756ef7d5dc98d27cb305a9132eb03aca31487ceddaa09be7456457ed3df7dd` |
| 83 | `dff3771fca8cc19d99188179ea8eb745012521b87f1edddffd446e1867cab033` |
| 137 | `7b662ad2738c3816802fedc5ac41a2d9f3c4b24d4ddce8463dabc9dbd46a8428` |

The original restricted checkpoint reader checks complete source hashes before
decoding only whitelisted tensor records. Each model is serialized to a new
research safetensors artifact with unchanged tensor values. The Rust evaluator
binds its full artifact, profile and actual input bytes. The scientific graph
control is separate from the production editor's scope.

There are 330 registered scalar parameters. The program may change only
`body.input_mark.weight` indices 7, 16, 25 and 34: the four sender rows' price
coordinates. It changes 1, 2 and 0 actual scalars at seeds 47, 83 and 137.
Readout weights, bias, reset coordinates, physical laws and every other tensor
byte stay fixed. Seed137 is a KEEP alias and must not be counted as successful
parameter optimization.

## 1. Temporal information reachability

The old graph updates physical control laws at ticks 0, 2 and 4. A receiver
consumes the previous boundary message. Sender signed marks are not sent across
the boundary-only communication mask. The final head reads receivers after
tick 5. Consequently, when the separate external baseline is fixed:

| Input tick | Receiver probability, value, first-passage risk, unsigned event, margin | Receiver signed-event feature |
| --- | --- | --- |
| 0, 2 | A path exists | A path exists |
| 1, 3, 5 | No path | No path |
| 4 | No path before this head's deadline | A path exists at tick 5 |

The evidence uses three real parents and seven cases per parent: the original
first 16 TRAIN queries and one normalized input intervention at each tick.
Labels and external baseline remain unchanged. All 21 complete Rust forwards
passed the original physical tolerance. At ticks 1, 3 and 5 the entire final
receiver feature and score bytes are identical. At tick 4 only the signed-event
column changes; all four probability-derived columns remain byte-identical.
There are zero fits or backwards in this experiment.

This is a structural barrier. On a balanced pair with the same observable
history but swapped final quotes and opposite correct decisions, the old neural
branch produces identical outputs for every possible choice of its weights.
With the equal external baseline used in the declared new task, it can obtain
at most 50% correct decisions. This statement does not apply when an external
baseline already observes the final quote or to a different clock or graph.

## 2. Explicit connection and analytic program

The experimental `final_tied_mark_bridge` shares the existing sender
`input_mark` affine map with its paired receiver on tick 5. No parameter is
added, and no QVI, reset or probability law is changed. Existing previously
disconnected parameters gain a path, so the function class and effective
connectivity change even though the registered parameter count is constant.

For a fixed pre-final history, the signed-event feature has the affine form

\[
f_j^{\rm signed}=a_j+\alpha_j\tanh(r_j+x_5 W_j+b_j),\qquad \alpha_j\geq0.
\]

The physical forward supplies the historical offset, nonnegative coefficient
and recurrent offset. Let \(v_j\) be the existing readout's class-contrast
coefficient on that signed feature. The program reads the actual weights and
sets the price coordinate to

\[
W'_{j,7}=-\operatorname{sign}(v_j)|W_{j,7}|.
\]

A predeclared small magnitude handles a zero price coefficient; a reusable
compiler must abstain if every usable \(v_j\) is zero. All executed parents
have nonzero signed-head contrasts. On identical choice histories, all offsets
and non-price features cancel. In real arithmetic the derivative of score with
respect to the last price is

\[
\frac{dS}{d\mathrm{price}}
=\sum_j v_j\alpha_j W'_{j,7}\operatorname{sech}^2(\cdot)\leq0.
\]

Thus the existing head ranks the lower price higher whenever a live term is
strict. The actual candidate is F32 and is evaluated through the complete
native graph; the derivative statement alone is not a universal floating-point
or near-tie guarantee.

## 3. New task and full ablation

The instruction is to wait through a noisy shared context, receive two final
numeric quotes, then select the lower quote. The input contains prices, not
answer labels. Each context is paired with a swapped-price version. TRAIN has
32 contexts/64 queries, DEV 16/32, and the final TEST 40/80. PCG64 seeds and
price ranges were frozen; TEST was generated only after all three parents'
candidates were sealed. Its price interval is wider than TRAIN's.

The three parents share those 40 final contexts. The 80 paired queries and
three repeated model views are not 240 independent observations. This is new
synthetic input, not new RAVDESS actors or market data.

| Seed | Original graph, KEEP or edited | Bridge alone | Sign program | Reverse sign | Random64 | BP64 | Actual sign edits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 47 | 40/80 | 80/80 | 80/80 | 0/80 | 80/80 | 80/80 | 1 |
| 83 | 40/80 | 0/80 | 80/80 | 0/80 | 80/80 | 80/80 | 2 |
| 137 | 40/80 | 80/80 | 80/80 | 0/80 | 80/80 | 80/80 | 0 |

Bridge-only is an essential control: most of the new accuracy at seeds 47 and
137 comes from making the input reachable. At seed83 the extra sign program
corrects the direction of the connected circuit.

The deterministic compiler reads no labels, performs no model calls and
computes no objective derivative. Random64 draws all 64 frozen-seed directions
within the direct delta's four-coordinate radius and selects only by TRAIN CE.
BP64 uses 64 Adam steps in that same four-coordinate domain and radius.
All directions, gradients, steps and final parameter values are retained.
The radius is 0.1254787, 0.6347385 and zero for the three parents; the last seed's
random/BP methods therefore remain KEEP. These are controlled local training
comparisons, not unrestricted full-model fine-tuning.

| Mean across the three parent views | Accuracy | Cross-entropy | Brier |
| --- | ---: | ---: | ---: |
| Original graph | 50.00% | 0.693147 | 0.250000 |
| Bridge without editing | 66.67% | 0.672872 | 0.239876 |
| Bridge + sign program | 100.00% | 0.654109 | 0.230504 |
| Bridge + random64 | 100.00% | 0.642010 | 0.224486 |
| Bridge + BP64 | 100.00% | 0.640190 | 0.223585 |

Confidence is still weak. Equal ranking accuracy does not establish equal model
quality; BP has better CE and Brier here. Its backward is the exact reduced
chain rule of the last-step four-parameter map, after freezing physical dynamics
that are structurally independent of those four coordinates. It is not a
backward through the complete encoder.

## 4. Retention decides deployment scope

On all 32 historical RAVDESS retention queries, unconditional bridge use loses
2, 4 and 3 previously correct decisions for the sign program. It fails the
registered retention gate at every parent. Random64 and BP64 also fail.
These candidates are rejected for unconditional use.

The predeclared request-scoped mode takes the new route only for the supplied
late-price task and the old route for normal requests. On normal requests it
reproduces complete parent features, heads and scores byte-for-byte at all three
parents. The mode is an explicit task selector, not a learned ability to detect
unknown tasks. No deployed model or trainer was changed.

## 5. A complete rollback must include the graph

A supplementary six-forward experiment restored all edited bytes into separate
artifacts and verified exact full parent hashes. Keeping the bridge active after
that byte restoration still gave 24/25/24 correct normal queries, versus the
original 25/27/27, and every output differed. Restoring the original graph as
well recovered features, heads and scores exactly at all three parents.

Seed137 is decisive: its candidate weights are already identical to its parent,
yet its changed graph changes behavior. Parent SHA equality cannot prove
semantic restoration. A reusable transaction must bind and restore parameters,
graph profile, request route, evaluator/source identity, input and evaluation
phase. This supplement checks restoration semantics in isolated artifacts;
it does not claim a persistent server transaction or a process-crash test.

The retained 2,880 full trace records also show that the sign edit leaves QVI
boundary, drift, cost and all probability-derived features byte-identical. The
receiver's pre-final features stay identical. Its final signed-event elements
change 160/320/0 times at the three parents, exactly matching the affected
receiver count. First-passage, reset and analytic continuation are preserved
objects here. This fixed model has no independent learned Belief or
Continuation-Q head and no trained NDU value law; none is declared repaired.

## Verification and resource boundary

The 15 new final candidate comparisons agree between an independent NumPy
physical replay/reduced expression and the complete Rust evaluator within
2.3842e-7 in features and 4.7684e-7 in scores. The physical tolerance remains
2e-9. A separate array-only audit recomputed all final scores and metrics,
candidate digests and price-pair symmetry; it passed without a new fit or model
call.

The three stages used 63 complete native forwards and 12 independent Python
forwards. Their recorded wall times are 1.589 s for temporal probes, 9.400 s for
the main matrix and 1.486 s for graph restoration. Native CPU totals 6.912 s and
Python/orchestration CPU 5.292 s. These timings exclude prior parent training,
earlier failures/research, source analysis, dependency setup and native build.
They do not support an end-to-end learning speedup ratio.

The reusable next step is a semantic weight-program plan that first verifies
the graph/input contract, rejects information-inaccessible targets, emits only
the four allowed byte edits, validates the real current endpoint and restores
both graph and weights on failure. Its NDU decision must evaluate the declared
task objective and actual costs: when a parent already satisfies the goal,
KEEP is a valid optimum of the finite available action set. This is separate
from global optimization over arbitrary neural weights or calibrated trading
returns.

## Local evidence map

- `LATE_INFORMATION_PROTOCOL.md`: original frozen task and experiment contract.
- `temporal_results/RESULT.json`: 21 native temporal interventions.
- `late_results/RESULT.json`: all late-task and retention outcomes and costs.
- `PROTOCOL_DEVIATION_01.md`: retained pre-fit ordering deviation and scope limits.
- `POSTEXECUTION_AUDIT.json`: independent array/input/digest audit.
- `GRAPH_ROLLBACK_PROTOCOL.md` and `graph_rollback_results/RESULT.json`: complete
  restoration identity and weights-only negative control.
- Executed sources, raw native traces, candidates, inverse artifacts and seals
  accompany the archive. Public checkpoint/source origin is pinned above.
