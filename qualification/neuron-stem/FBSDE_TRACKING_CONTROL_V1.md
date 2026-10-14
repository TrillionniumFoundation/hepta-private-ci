# Learned-belief verification scheduling in the existing tracking workspace

Parent: `9c1f2bc3d68ec17afb8d5836a4164d7248c77e2d`, Draft #1550.
The same frozen gate, grammar, original benchmark, inference port, serialized
record buffer, exact controls and study entrypoint remain. New explicit option:
`--tracking-control-profile learned_belief_v1`. The default `all_steps_v1` and
all six old physical matrix entries remain. Two new backend entries are additive.

## What is learned and what is solved

The existing shared gated Head is fit on simulator single-operation labels only.
After freezing it, 360 generated calibration events select one temperature from
(.25,.5,1,2,4) by operation NLL; benchmark examples and targets are not used.
A participant score vector s becomes a categorical distribution over exactly two
participants: q(a,b) proportional to exp((s[a]+s[b])/temperature). The operation
state is no longer only an argmax symbol. A bounded probability workspace carries
its effect through the entire event sequence to the queried original holder.

This is a planner over LEARNED BELIEFS, not a separately learned neural policy,
not dynamic preferences, and not a continuous fully coupled semantic FBSDE.
Independence of event errors is an explicit approximation. In particular, using
one shared gate on repeated canonical inputs can create correlated epistemic
errors. Temperature fitting is not a risk/coverage certificate, even at zero
observed errors. No finite numerical residual authenticates the semantic law.

For this risk-neutral profile, V(h)=max(0, max_j[2p_j(h)-1],
max_i E[V(h with revealed event i)]-c). Here c=.02 utility units, correct=+1,
wrong=-1, abstain=0. For each verification action f=-c and Z_j=V_j-E[V], so
V_j=V-f+Z_j with E[Z]=0. A common total budget of at most TWO verifications is
never reset by replanning. The two-step recursion can condition its second action
on the first result. Exact whole-world tests include complementary information:
one check alone has no value, both produce .8 at .1 cost each; at .6 both stop.

The value ceiling 1-c permits exact model-level early stopping when no possible
first check can improve the current terminal value. Otherwise all nonzero model
outcomes are included, not their maximum. Node and process-CPU limits reject
rather than returning an unresolved answer. Denied planner work retains its cost
and no action. Both proposal and planner limits are 100,000,000 process CPU ns;
this is post-computation admission, not preemption or a whole-request deadline.

## Information and cost boundaries

The planner receives only the finite distributions, public query and identities,
never correct pairs, raw event text, benchmark targets or sample labels. The
surrounding parser/source verifier reveals a selected exact pair after action
choice. This is an evaluator-process information contract, NOT an OS sandbox.
The parser already checks the whole constrained story; selecting fewer checks
therefore does not prove physical parsing work was saved. Check charges are
modelled utility costs, distinct from measured CPU, and are not hardware prices.

For matched counterfactual comparison, one set of real gate proposals is computed
per story and shared across the seven schedulers. Inference/fitting is counted
once in the physical ledger, not seven times. Per-arm scheduler CPU excludes
shared proposal and grammar preparation. Complete standalone lifecycle cost is
NOT reported. Exact reverse needs no neural proposal; it remains a stronger cheap
control, not a deliberately weakened algorithm. All predictions are serialized
and sealed before benchmark targets enter final scoring. BBH is evaluation only.

The seven arms are greedy, posterior without checks, .95 confidence heuristic,
myopic verification, two-step NDU, verify every event, and direct exact reverse.
Unchecked posterior answers are NOT semantic certificates. Verify-all and exact
reverse guarantees concern only the explicitly supported swap grammar.

## Actual executed evidence and its limit

On the first complete local BBH run (750 original stories), every arm answered
750 correctly. Simulator temperature selection chose .25; all learned-belief
controllers chose ZERO checks, whereas verify-all used 3750. Thus NDU did not beat
no-check or exact reverse. The new state/control mechanism works, but this already
solved grammar supplies no extra efficacy opportunity. Model-score confidence is
not independently calibrated for unseen natural language. The benchmark and many
normalized operation forms have been inspected in prior exploratory work.

The final run after stable tiny-NLL accounting uses identical frozen selection
rules; it is a repeat of the same tasks, not fresh confirmation. Early run records
are retained. The independent arithmetic audit imports neither planner nor model;
it propagates full actor-holder matrices FORWARD, recomputes conditional policy
values, reveals only requested original events, and checks final decoded answers,
source/calibration bindings, original labels, action charges and timing sums.

Riccati-Newton remains a separate numerical inner solver for suitable continuous
subproblems. It is not inserted into this small finite decision table merely to
rename the controller. Native final-use, no-change, independent future evaluation,
retention and risk admission remain with their existing owners. No promotion.

```sh
PYTHONPATH=qualification/neuron-stem python qualification/neuron-stem/fbsde_study.py \
  --profile verified_tracking_v1 --tracking-source bbh --backend hashing_reference_v1 \
  --tracking-feature-profile local_participant_v2 --tracking-record-profile serialized_records_v2 \
  --tracking-control-profile learned_belief_v1 --output /new/evidence
```
