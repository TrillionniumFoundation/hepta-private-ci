# Decision-local continuation reuse without changing the learned policy

Parent: `ee78f78bc88db055f23b92eb6ff2a849a647e399`, Draft #1550. This
parent already includes input tying, novelty calibration, verified feedback and
learned depth allocation. They are preserved, not replaced by an older patch.

## Exact information and lifetime contract

The existing finite risk-neutral Bellman/BSDE recursion is unchanged. Its cached
values are keyed by BOTH public history and remaining verification horizon.
A one-step value is never substituted for a two-step value. Conditional state
probabilities do not depend on the computation horizon, so their paid evaluation
can be shared. InputTiedBelief now reduces the SAME ordered normalized worlds
once into holder, member and possible-observation distributions. Unit tests check
bit-for-bit parity with each original conditional port, including revelations.

`PlanningWorkspace` owns bounded ordinary dictionaries, not a recursive closure
wrapped in lru_cache. The original public `plan` opens one fresh workspace and
closes it on success/failure. A local weak-reference diagnostic on the parent left
17 of 20 problem objects alive until a diagnostic collection; the new public call
releases its problem reference on return without disabling or forcing GC. This
identifies a reference-cycle lifetime, NOT every historical CPU-overrun cause.
Python reference: https://docs.python.org/3.13/library/gc.html

The optional `--depth-planning-engine shared_continuation_v2` shares one workspace
across the paid one-step pilot, gate features and an optional deeper solve. The
original `fresh_solve_v1` allocation remains the default and strong control.
Actual source verification closes this allocation; the next public history gets
a NEW workspace. No state is borrowed across arms, models, scopes or generations.
Callers retain the existing immutable-model contract inside the lexical scope;
this is not a hostile-process boundary or general mutation attestation.

One cumulative 100,000,000 process-CPU-ns deadline and 20,000-new-value-node limit
apply; no reset on escalation. Construction, snapshots, gate work and cache cleanup
are included in the outer allocation check. Work reuse can avoid a recomputation,
not its already-paid pilot charge. Both successful and rejected exits clear all
scratch. Returned arrays are copies and cannot rewrite cached values. History and
model-identity drift reject. No GC setting or original scientific threshold changes.

## Executed comparison and qualifications

Parent hosted artifact 11751040665 from run 38252368460 is bound to the exact
parent SHA (ZIP SHA256 8cb7bb4cd522e61c0d49f01733ad662315c6eacb37f3d1469efe80c7302d1407).
Its already-generated 204 stories, trained semantic/residual parameters, frozen
router, thresholds and beliefs are the fixed comparison inputs. Three interleaved
repetitions of 10 modes x 204 stories x 3 implementations give 18,360 calls.
The original parent code, new fresh workspaces and shared continuation engine all
produce exactly the same decisions, probability values, verification sequences,
route features and rendered answers. Only measured work and cache metadata differ.

Median total controller CPU per 204-story repetition (seconds):

| Mode | Original parent | New fresh | Shared continuation |
| --- | ---: | ---: | ---: |
| Always two-step | .243974122 | .196571323 | .192566291 |
| Learned complete-threshold gate | .246376269 | .212651276 | .194138388 |
| Confidence complete-threshold gate | .244508814 | .221913957 | .185652864 |

Aggregated original/shared ratios are 1.2457, 1.2597 and 1.3213 respectively:
about 19.72%, 20.61% and 24.32% less measured controller CPU. This is one local
interleaved diagnostic, not stable latency, new semantic accuracy or full lifecycle
attribution. Cheap confidence remains faster than the learned gate; exact reverse
remains cheaper and more accurate. An earlier 18,360-call implementation without
the combined conditional reduction did NOT consistently save CPU and is retained.

Two full final-engine studies additionally executed the unchanged base-Head load,
54-operation residual feedback, numerical-router fitting and frozen evaluation.
Their 2,040 outputs have identical non-work fields. Both score 140/143 answers on
144 heldout stories for learned/full/confidence complete modes, with 121 checks;
one-step remains 132/135, and exact reverse is 144/144. These are reused historical
synthetic grammar tasks, not fresh independent observations or pretrained runs.
Per-run teacher provenance hashes include CPU observations and differ legitimately;
each is audited before pairing the full non-work teacher contents and thresholds.
No training provenance hash is overwritten merely to pass a comparison.

The existing saved-file auditor recomputes both studies. The additional pair audit
imports no planner or Torch. Final-source regression and tensor results, interrupted
commands and benchmark raw timings are retained in the conversation delivery and
PR execution note. Native full-repository validation is separate. Keep Draft.
