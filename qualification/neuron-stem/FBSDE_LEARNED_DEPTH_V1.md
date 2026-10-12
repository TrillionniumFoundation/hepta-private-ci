# A learned computation-depth gate, with paid pilot work and cheap controls

Parent: `651a2c9feaae848b6eb53a04d9618363580b96ae`, Draft PR #1550.
The parallel input-tied, novelty and verified-feedback revisions already exist
and are preserved. The original study entry gains `learned_depth_allocation_v1`.
No original model, evaluator, workflow lane, risk floor or native owner changes.

## Learned mechanism and limitations

The previous shared 129-parameter residual repairs participant rankings while
keeping the three base Heads and lexical Encoder immutable. Reuse that exact
54-operation feedback, 18-operation calibration and 160-step candidate fitting.
The new module learns a DIFFERENT function: whether a paid one-step planning
result is likely to benefit from two-step computation. It sees fifteen bounded
belief summaries, including current outcome probabilities, entropy, available
input groups and the one-step value; it receives no source text, correct pair,
external test outcome, or hidden two-step answer during deployment.

A 265-parameter gated network (15->8->1) is trained for 160 AdamW updates on 256
numerically generated belief contexts. The target is whether exact two-step
MODEL value exceeds exact one-step value by .002. This price is a declared
model-utility proxy, NOT measured CPU, energy or an execution receipt. The teacher
is the existing finite planner, not a human verifier or evidence of correct
language. Numerical teacher fitting, 64-row threshold selection, 64-row model
test and their computation are all recorded. Each partition has a separate
fixed seed and ID namespace. A high teacher score does not certify real risk.

The original coarse threshold grid is retained. Its first completed experiment
selected threshold zero: always run two steps. Inspection of the SELECTION grid
identified missing score breakpoints. A separately named complete-breakpoint
variant searches every selection score for BOTH learned and confidence routers.
No semantic test target or model-test row selects a threshold. Nevertheless this
variant was introduced after the coarse experiment, and the inherited semantic
frames were already explored; this is not independent confirmatory evidence.

## Inference and budget contracts

Adaptive modes actually execute and pay for a one-step pilot. Escalation starts
an additional two-step solve; it does not borrow the result computed for another
arm. Both solves plus gate/feature computation must fit ONE 100,000,000 process
CPU ns limit and ONE 20,000-node allowance. The second solve receives only the
remaining node allowance. The total two-verification action budget never resets.
Choosing the approximate one-step policy is explicitly not an optimality proof.
Problem, model, calibration, scope and generation bindings must match the router.

The cheap confidence control and myopic diagnostic share the same observable
feature-record path; this is not a claim of their minimum implementation cost.
Their unnecessary feature collection could be optimized further. Always-two-step
has no pilot charge; exact reverse does not require any learned proposal. Every
control remains available, including no checks, fixed one/two steps, frozen gate,
both threshold selectors, verify all UNIQUE inputs, and exact reverse.

All actions and predictions are sealed before final label scoring. Source
verification reveals only a selected event to the planner; the outer simulator
still knows the constrained grammar and whole source. No OS isolation or new
source authority is provided. Repeated known-frame replay is not independent
retention evidence. The 144 heldout stories reuse only 36 instruction strings.

## Final local experiment (lexical reference, no pretrained forward)

| Arm | Correct/answered of 144 | Checks | Two-step requests | Planner nodes including pilot | Controller CPU ns |
| --- | ---: | ---: | ---: | ---: | ---: |
| no checks | 102/117 | 0 | 0 | 144 | 25883172 |
| one-step | 132/135 | 105 | 0 | 936 | 294613139 |
| always two-step | 140/143 | 121 | 144 | 2134 | 387983867 |
| coarse confidence | 140/143 | 121 | 39 | 1855 | 357048519 |
| coarse learned | 140/143 | 121 | 144 | 2800 | 430438823 |
| complete confidence | 140/143 | 121 | 39 | 1855 | 371505110 |
| complete learned | 140/143 | 121 | 20 | 1584 | 403741819 |
| verify all unique | 144/144 | 288 | 0 | 144 | 114021545 |
| exact reverse | 144/144 | 0 | 0 | 0 | 42174250 |

The final learned threshold is .17258737709649427. Fitting BCE decreased from
.6513827443 to .0708749890. On the separate 64-context numerical test it chose
26 deep requests with zero measured missed model value. This is finite sampled
model behaviour, not a guarantee. A two-step request can itself stop immediately
at a value bound; request count is NOT executed reasoning depth. Nodes and CPU
are retained separately. All modes retain 60/60 known replay; only verify-all
pays for 120 checks there.

The complete learned gate saves node expansions relative to always-deep, but
its final batch CPU is HIGHER, and the cheap confidence control is faster still.
No latency or full-lifecycle win is claimed. Router preparation alone includes
teacher jobs and training; the physical ledger also retains unused semantic
candidate fit jobs, shared encoding/proposals, evidence recording and audits.
Standalone attribution and independent source/risk qualification remain open.

## Reproduction and exact validation scope

Use an original byte-bound lexical input-tied artifact (not BBH training data):

```sh
PYTHONPATH=qualification/neuron-stem python qualification/neuron-stem/fbsde_study.py \
  --profile learned_depth_allocation_v1 --evidence-dir /fixed/base-study \
  --output /new/depth-study
```

Fourteen new unit contracts and five actual Torch contracts passed. The locally
available 411 inherited source tests plus fourteen new ones passed (425 total);
this is NOT the complete 434-test parent inventory, because 23 parallel tests
were not materialized locally. Fifty-two inherited nontracking Torch tests passed;
the full tracking group and native Rust were not rerun. Their historical failures
remain. The existing feedback workflow preserves its full exact-head/merge tests,
old source/feedback run and outputs, then executes the new gate and retained logs.
New final-SHA hosted results are required independently. Keep Draft.
