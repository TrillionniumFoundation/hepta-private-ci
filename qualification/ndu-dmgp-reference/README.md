# Hepta NDU-DMGP A0-A5 reference qualification (experimental)

**Status:** qualification-only reference code, never production authority. The code is intentionally isolated from the Rust NDU/CNS/runtime owners and does not invoke models, schedule tasks, load artifacts, train weights, issue final-use grants, or mutate repository runtime state. `production_qualified` is **always false**. Synthetic fixture tests prove rejection behavior, not multimodal generation quality.

## Core scientific question

Does a state-conditional NDU-guided dynamic portfolio of multimodal generator actions improve **externally observed task utility** at matched models, training inputs, hardware, resources and output quality, *beyond* fixed routing, MoE, one-step NDU, and risk-aware one-step portfolio selection?

Arms: A0 frozen encoder/decoder reference; A1 deterministic fixed-rule routing; A2 learned Top-k/MoE router; A3 one-step NDU Advantage; A4 conditional-covariance-aware one-step allocation; A5 recursive continuation NDU portfolio with optimal stopping (the policy code contains only a finite, non-authorizing surrogate, **not** a full FBSDE/HJB solver).

## Layout

- `portfolio_policy.py`: deterministic qualification reference for the six action-selection families, separate hard feasibility before utility; A4/A5 use a bounded mirror-ascent covariance surrogate on *routing probabilities*, never average incompatible images/audio/token latents. Missing conditional covariance falls back visibly to A3; if no feasible action, abstain. All results are advisory.
- `ndu_dmgp.py`: fail-closed data contract, conditional covariance rank and spectral support audit, diagonal shrink + low-rank PSD approximation, held-out scalar-state history-closure probe, full-circuit intervention credit, real-receipt-field structure, A0-A5 paired future/retention comparisons and controller overhead reports. Never confuses portfolio risk covariance with NDU BSDE martingale-driver covariance.
- `test_ndu_dmgp.py`, `test_portfolio_policy.py`: standard-library reproducible synthetic tests, including negative and adversarial fixtures.

Run from this directory on Python 3.10+:

```sh
python -m unittest -v test_ndu_dmgp test_portfolio_policy
python ndu_dmgp.py /path/to/actual_pre_registered_joint_generation_evidence.json --output /tmp/ndu-dmgp-report.json
```

No synthetic fixture is included as a claimed dataset. To derive a demo input for **testing only**, import `fixture` from `test_ndu_dmgp.py` and write it as JSON with `manifest.mode=reference_fixture`.

## Six blockers and their exact limitations

| Blocker | Enforced in this reference | Still required for actual closure |
| --- | --- | --- |
| NDU reward reality | fixed objective/metric/critic/observer identity, external-observed flag, paired out-of-sample future groups and independent owner separation | trusted host attestation/signature verification, concrete human or external oracle/real-world labels, temporal randomization and proper causal/OPE study |
| Cross-modal consistency | shared plan ID, independent bidirectional result, no entity/timeline violations, min semantic agreement and A/V sync bound | execute actual forward/backward image-text/audio-video verifiers, store signed time-aligned source/target spans, human evaluation on disjoint domains |
| Covariance identifiability | matched state condition, centered joint trials, ESS>=max(30,8K), full rank, eigen floor, condition<=1e6, shrinkage and bounded low-rank error; explicit fallback | demonstrated conditional sampling support across real task strata, interval coverage and BSDE driver-coordinate independent qualification |
| Computational benefit | actual measured decoder/controller/wall durations and RSS reporting, paired wall and net savings lower confidence bounds | signed host-side wall/GPU energy measurements, repeated physical benchmarks and quality-matched p95/p99/CPU/GPU/RSS receipts |
| Learning stability | frozen observer/critic/objective, KL trust threshold, next generation only, future gain and old-task retention | real training implementation, immutable critic provenance, temporal prospective windows, rollback, independent `learning.eval` selection and final-use |
| Global credit / state closure | paired full-circuit one-cell interventions with support ID, heldout compact vs history-augmented regression | experimentally identified joint interaction credit and calibrated uncertainty; multivariate causal/Markov sufficiency audits, not just scalar linear probes |

Crucial nonclaims: a text ID is not a cryptographic signature; an `independent_observed_outcome` boolean is not evidence of observer independence; passing a declared audio/video synchronization value does not mean actual audio/video was rendered and verified; a low-rank risk covariance is not the `Z Sigma = B` martingale regression in NDU; an observational matched comparison is not proof of causality; a linear history residual test is not a Markov theorem; mirror ascent does not establish a global optimal portfolio.

## A0-A5 data contract

A JSON object contains `manifest`, `runs`, `joint_trials`, `closure_probe`, `credit_pairs`.

- **Manifest** fixes 6 arms, objective/dataset/current-Backbone/next-candidate snapshots, actor/critic/observer ownership, frozen metric profile, hardware, semantic-plan schema, identical precommitted per-arm compute budget, split assignment and max trust-region KL. The current `snapshot_digest` on a run is the shared *frozen generating foundation*, not an authorization to select the next candidate during the active run. Policy variants must identify themselves separately by `arm` and actual `evaluated_arm`.
- **Runs**: one row for each (future or retention episode, A0..A5) with independent group and outcome receipt identities, actual selected arm (fallback cannot be disguised), immutable objective/critic/host/snapshot identities, same input and per-task semantic plan across all arms, equal admitted compute budgets and observed usage, observed utility and quality in `[-1,1]`, hard safety, quality/consistency check, `elapsed_ns`, `decoder_ns`, `controller_ns`, `peak_rss_bytes`, bounded policy KL. At least 30 independent paired episodes per split; no shared group across splits or within a split. Every run must have >=2 distinct output modalities.
- **Joint trials**: `split=train` only, no reused evaluation-group IDs; at least max(30,8K) independent jointly observed vectors for the *same pre-decision condition*, positive weights, 2<=K<=8. For valid A4/A5 live routing, bind the resulting covariance profile and action ordering to the selected state and artifact generation. **Do not** use candidate-independent marginal samples as independent joint trajectories.
- **Closure probe**: train and future rows for the compact state, history probe and independently observed next outcome; checks whether the extra history predicts more after conditioning on compact state. This pilot checks only a 1-D registered linear projection, not multivariate POMDP sufficiency.
- **Credit pairs**: at least 30 independent matched/randomized one-cell intervention groups, frozen objective and observer, matched full Circuit terminal utility with explicit counterfactual support. No local reward can substitute for the full-circuit outcome.

The qualification evaluator requires physically measured values to be supplied by trusted owners. It does *not* generate the data. `mode=observed` additionally requires a trust-root digest; actual attestation verification remains an explicit blocker.

## Statistics and validity

The primary preregistered family comprises five A1..A5-versus-A0 utility contrasts plus A5-versus-A2 and A5-versus-A4. One-sided alpha is Bonferroni-adjusted to 0.05/7. The local code uses a **normal-approximation LCB** and at least 30 genuinely independent groups. Real promotion must obtain design-appropriate paired/group-bootstrap or robust concentration bounds with multiplicity control, not treat the approximation as sufficient. Gains must hold on *future independent outcomes* with noninferior old-task quality/retention; primary scoring weights and success criteria cannot be tuned on the held-out window. Memory is peak RSS as reported by the host; no host source is currently authenticated.

This reference deliberately does not modify `docs/learning/NDU_FBSDE_SPEC.md`, `docs/contracts/PROTOCOL_SCHEMAS.json`, or current production Rust wire versions. A production implementation requires a separately versioned `PortfolioProposal`, `JointOutputObservation`, `ConditionalRiskProfile`, `CrossModalVerification` and `PortfolioEvaluationReceipt` through the established owner/module registration process, alongside CI golden vectors and current-revocation checks.

## Required follow-on acceptance sequence

1. Independent dataset/reference host + frozen SHA for models/weights/tokenizers/encoder; real text-image then audio-video render/verify, including source spans and outcomes.
2. Native Rust contract and deterministic A0/A1/A2/A3 + abstain integration through NDU owner (never create a second authority or executor).
3. Conditional joint covariance/low-rank support in shadow only, with low-support deterministic fallback and closed-loop decoder timings.
4. A4/A5 policy and future-NDU credit studies under fixed budget, including independent observer and external annotations.
5. Prospective future-window plus old-task retention; independent evaluator, signature/checkpoint/rollback, Rust CI and production host receipt; only then selection by the established final-use owner.

Do not claim any of these as complete from this reference's test pass.
