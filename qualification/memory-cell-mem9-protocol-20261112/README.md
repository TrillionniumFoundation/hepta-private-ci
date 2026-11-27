# MEM9 prospective protocol admission

This review stage follows the isolated actor launcher in PR #6046. It introduces
`admit_protocol(plan, evidence_loader, observation_verifier=None)` and a typed
`AuthenticatedObservation` port. It does not yet add episode scoring admission.

The default verifier is absent. Hashing caller-supplied JSON or returning a
self-reported isolation flag cannot authenticate source exposure or runtime
custody. A real embedding must supply an independently configured observer.

## What is frozen

- Actual actor, launcher, model, analysis and evaluator identities.
- The existing MEM5/MEM6 public selector profile, public_rule mode and exact
  selector source bytes, plus the checkpoint/configuration identity.
- Task A and different task C digests, allowed sources, query/key digest,
  retrieval limit, context byte budget and replay seed.
- All six requested baseline families and the four distinct interventions:
  facts, association, ranking and delivery.
- Authenticated source admission and registration before execution. UNKNOWN
  exposure cannot be promoted to UNSEEN; UNAVAILABLE baselines remain unavailable.

The public profile digest is
`c9b56f198abd1737a9883326fd0c66f411e46218b126aec1e4b6f4f48e66870e`,
recomputed from existing `candidate_selector.PROFILE` using `canonical_sha`.
It describes both public and neural modes; a separate public_rule check prevents
a neural selector from passing merely because that shared profile matches.
The pinned selector source SHA-256 is
`a335533f75545b3f7ef8349ba57801c5bdb8a7ae2d3a40ded1c52c925e15f807`.

Different task digests detect exact repetition, not semantic independence.
The authenticated source/evaluator review must establish the latter. This
stage adds no numeric E source minimum and does not transfer W's historical
20-source threshold to an episodic experiment.

## Validation and boundary

The final exact blob bytes were read back and executed in a Python 3.12.14
in-memory module projection: five tests passed, none skipped. These are
synthetic contract controls with explicitly fixture verifiers, not model
episodes or authenticated new data. Ruff 0.15.13 checks passed.

This stage adds its own test selection to the existing exact-source MEM
integrity job. Hosted results must be read on the actual source commit.

ADMITTED_FOR_EXECUTION describes input-contract consistency only. Every result
continues to return scientific_acceptance=HOLD, benefit_established=false and
production_adoption=false. Actual actor/provider observations are the next
separate review stage.
