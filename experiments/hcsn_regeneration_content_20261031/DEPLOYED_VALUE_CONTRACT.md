# Frozen-policy continuation audit

This additive audit changes no primary model, controller, source, action, fee or
heldout outcome. Publish this source, this contract and `DEPLOYED_VALUE_FREEZE.json`
before running it. The freeze binds the audit source hashes; the root phase
receipt records the real published audit commit. `run_study.verify_freeze` and
`verify_candidate` bind the already published 54 models and six controllers.

The primary ridge was fitted to `Q*(s, READ/SKIP) - Q*(s, STOP)`. Those targets
assume optimal future continuation. They are not the same as the values of an
initial action followed by the actual fitted policy. This audit computes both
without refitting or selecting another model.

For each frozen width-16 backbone, seed 11/23/37 and each of the four registered
heldout configurations, build the identical finite causal history graph. Run
the actual public-feature controller to define `pi(s)`. In reverse time compute

```
Qpi(s, STOP) = true conditional correctness of this frozen model's STOP class
Qpi(s, a) = -complete_action_fee(a) + sum P(s' | s,a) * Vpi(s')
Vpi(s) = Qpi(s, pi(s))
```

Every downstream action follows the same frozen learned policy. Future
observations are integrated before their realization; no pathwise future maximum
is used. The teacher posterior remains outside the controller input.

Compare predicted READ/SKIP advantages against optimal `Q*` advantages and
deployed `Qpi` advantages separately. Report RMSE, signed bias and sign accuracy
with uniform legal state-action weights and with actual pi-occupancy weights;
also report each action head separately. Record targets within 1e-10 of zero.
The actual policy's one-step improvement regret `max_a Qpi - Vpi` is not called
its total oracle gap. Occupancy-weighted optimal-action regrets must reproduce
the global `V*-Vpi` gap; independently recomputed Vpi must reproduce primary
policy enumeration within 2e-10. Terminal probability mass must equal one.

For the first heldout configuration, independently execute all 1,024 latent raw
worlds after each of three forced first actions STOP/READ/SKIP, then follow the
same fitted policy. The root override is stateless (`slot==0`) and never sees
unread inputs. Save all requested/executed actions, costs, raw accesses, state
hashes and evaluator world identities in gzip JSONL. Generative-probability
weighted returns must match the root Qpi for the forced action within 2e-10.

Also evaluate a fixed 21-point root READ-cost grid from 0 to .5. At each cost
the existing fitted policy receives that public cost feature; its weights never
change. Record predicted continuation advantage, optimal continuation advantage,
actual-policy continuation advantage, chosen action and actual policy value.
Recompute optimal Q* and actual Qpi at the same fee for all future READs. Check
monotonicity separately. If learned-policy responses are nonmonotone, retain
them as value surfaces; do not manufacture a unique scalar free boundary or
claim smooth-pasting. Cost-ray values do not select or alter any candidate.

The complete registered size is six frozen models, 24 configuration graphs,
six root cost rays, and 18 forced-action enumerations totaling 18,432 actual
world executions. Uniform-history metrics and occupied-history metrics have
different denominators. This is a descriptive post-freeze audit of a small known
generative task, not a new training experiment or new superiority test.

All output directories must be new. The outer root phase records full child
CPU/wall, including imports and evidence writes; the audit's internal timer is
explicitly before its final receipt. No tariff or CPU measurement is called
energy. Run only after publication:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python deployed_value_audit.py --candidate-commit REAL_CANDIDATE_SHA \
  --audit-commit REAL_AUDIT_SHA --output evidence/deployed_value/formal_01
```
