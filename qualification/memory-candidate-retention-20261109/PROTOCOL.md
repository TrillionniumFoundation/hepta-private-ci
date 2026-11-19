# MEM candidate retention: frozen actor, complete denominators

## Scope and intervention

Compare `current_only` with `bounded` using the same immutable original image,
encoder/OCR, actor parameters, controller, action space, candidate entry cap and
serialized byte cap. Both modes use the bounded admission rule; only retention
between observations changes. No neural-memory or replay advantage is assumed.
This experiment does not permit cross-image, cross-document or cross-task reuse.
Source changes require a new scope and cannot reuse old coordinates as actions.

Freeze the complete paired episode roster and executable source identities in
`PLAN.json` before execution. Retain every planned operation, including failures,
timeouts, budget stops and missing outcomes. `EVIDENCE.json` binds every retained
artifact by relative path, exact bytes and SHA-256. Hash consistency is not
independent authentication of execution or prospective registration.

## Offline attribution

The actor receives no private target or scoring feedback. After the actor exits,
the report verifies each sidecar's episode/source/profile/model identities,
chain and actual action, then checks offered candidates against their recorded
same-scope raw origins. Private references use the existing independent field
normalizer. Final delivery is independently rescored, including image pixels,
image pass criteria and preservation of committed outputs. Actor/result quality
claims are not used as labels. Sealed confirmation roles remain inaccessible.

The episode attribution anchor is the **last `WRITE_TEXT` decision**, or the
final actor decision if no text was written. Earlier failed selections are not
mistaken for the choice that produced a corrected final output.

| Event | Meaning |
| --- | --- |
| O | A correct candidate appeared in raw frozen-pipeline outputs by the anchor |
| C | A correct candidate was actually offered to the actor at the anchor |
| S | The actor's recorded selected index identifies a correct offered candidate |
| D | That candidate was actually written and final delivery independently passed |

Report `P(C)`, `P(S|C)`, `P(D|S)`, and also `P(O)` and `P(C|O)`. The extra O
event is necessary to distinguish perception omissions from post-observation
candidate loss. Early stopping without inference supplies no C/S observation;
it is not counted as a negative candidate recognition test. Missing evidence is
unknown, conflicting evidence is rejected, and zero conditional denominators
produce `null`. Counts and conservative unknown-outcome bounds accompany rates.
`candidate_unavailable_at_decision` means an earlier observed correct candidate
was absent from the offered decision roster. Physical pool eviction, admission
loss and a policy that did not consume candidates require their own receipts;
unprocessed early stopping remains a separate unknown/no-op outcome.

Unconditional success requires `Completed` and independently correct delivery;
final content correctness is retained separately for failed/budget-stopped runs.
Initial-correct/no-write successes and successful bypasses are separate from D.
Prespecified initial-correct, initial-incorrect and initial-unknown strata never
replace the all-planned denominator. The primary paired descriptive contrast is
unconditional success for `bounded - current_only`, with missing pairs retained.
Conditional rates across arms have different candidate support and alone do not
identify a causal improvement in the selector. No sampling-confidence or model
training-repeat claim follows from a small finite source panel.

## Scientific boundary and next gate

Bakermans et al., *Constructing future behavior in the hippocampal formation
through composition and replay* (online 10 March 2025,
[DOI](https://doi.org/10.1038/s41593-025-01908-3)), combine a compositional model
with rodent recordings. Its reusable building-block assumptions motivate a new
combination benchmark; they do not establish a benefit for Hepta's memory head.

Thompson et al., *Replay of procedural memory is independent of the hippocampus*
(online 23 July 2026,
[DOI](https://doi.org/10.1038/s41593-026-02362-5)), report striatal replay after
hippocampal lesions and association with later performance. Their Discussion
also requires selective replay disruption to establish its causal contribution.
The study motivates separating factual/episodic and procedural replay; it does
not validate a particular software replay scheduler.

After candidate availability, test versions, revocations, dependencies and new
combinations against strong retrieval plus an equally informed relation/join
baseline. Match replay source exposure, bytes, updates and teacher cost before
assessing priorities. If the matched structured rule or neural association loses,
retain the stronger ordinary baseline. Code checks, fixtures and pilot results
keep scientific acceptance `HOLD` and production adoption disabled.
