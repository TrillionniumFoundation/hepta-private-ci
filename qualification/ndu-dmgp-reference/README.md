# NDU-DMGP Shadow-Only Qualification Reference

**Status:** deterministic/synthetic reference implementation. **No model calls, weights, authority, promotion, or measured decoder performance.** No canonical schema or production owner is changed. This directory cannot be used as an activation certificate.

**Purpose:** establish falsifiable numerical and protocol checks for **NDU-guided Dynamic Multimodal Generation Portfolios** (a proposed Merton-style, multi-step policy atop existing Hepta NDU and DecisionCell owners). It does **not** implement a production NDU FBSDE solver, a multimodal encoder/decoder, or a genuinely trained Critic.

## Reproduce

From repository root (Python >=3.10; no external dependencies):

```sh
python3 -m unittest discover -s qualification/ndu-dmgp-reference -p 'test_*.py' -v
python3 qualification/ndu-dmgp-reference/reference.py \
  > /tmp/ndu-dmgp-shadow-report.json
```

The JSON report contains `dataset: synthetic_scenarios_only`, `real_decoder_observed: false`, `independent_future_observed: false`, `production_blockers_closed: false`, `no_promotion_authority: true`. Do not remove or reinterpret these provenance fields. Timed `controller_time_us_measured` and `controller_peak_python_bytes_measured` are **Python reference controller** measurements only; `synthetic_compute_units` is a declared simulator quantity, **not GPU time/FLOPs/energy or verified decoder resource measurement**. Runtime timings depend on host and must not be interpreted as production latency qualification.

## Six blocker families — reference claim versus actual closure

| Blocker | Reference gate and adversarial evidence | Not yet closed |
| --- | --- | --- |
| Independent NDU reward | Immutable objective fingerprint; external observer role distinct from Actor; rejects synthetic/unmetered outcomes, nonfinite amounts, split leakage and objective revision mismatch; fixed resource/risk prices | Signed independent outcome adapters, real device meters, causal attribution and held-out observations |
| Cross-modal consistency | Typed events; bidirectional source/output entity and semantic-tag coverage; audio-video time skew and entity coupling; strict required-modality constraint | Perceptual encoders, semantic reconstruction metrics, external human/video/audio validation |
| Covariance identifiability | Episode-paired outcome vectors, minimum matched support, shrinkage, bounded Jacobi eigensystem, optional low-rank+diagonal PSD approximation and fail-closed deterministic policy | Conditional observed risk across real generated outputs, external calibration and stability under distribution shift |
| Compute efficiency | Measures reference controller wall time and Python transient bytes separately from simulated Decoder cost; explicit `decoder_runtime_measured=false` | Matched host/backend GPU seconds, tokens/frames/samples, actual FLOPs, RSS, end-to-end p95/p99, time-to-quality |
| Learning stability | Frozen Critic, next-generation-only parameters, KL trust bound, matched future LCB vs baseline UCB, retention floor, synthetic evidence rejection | Real trained candidate, signed snapshots, trust-region estimator, independent evaluator, out-of-time future outcomes, CI and rollout |
| Global utility decomposition | Cell Credit support and conservation against global NDU including explicit interaction term; held-out history-predictivity closure audit rejects lossy compressed state | Real causal credit assignments, verified history sufficiency or uncertainty bounds, cross-organ boundary checks |

This repository's actual NDU mathematical source remains `docs/learning/NDU_FBSDE_SPEC.md`; authoritative contribution aggregation remains `codex-rs/hepta-ndu::evaluate_candidates_with_policy`. This reference uses **portfolio return covariance**, not the FBSDE martingale increment covariance. It must not replace canonical NDU/Control/TaskFlow implementation owners.

## Preregistered A0–A5 control ablation

All arms use the same **24 held-out evaluation scenarios**, budget, action set, hidden realized gains and observed interactions. A separate **24-episode training split** fits the A2 router and A4 covariance (no shared episode IDs); neither model reads evaluation labels. *Forecast* gains and interactions remain separate from held-out synthetic outcomes. No arm reads the latter when choosing an action.

| Arm | Actual reference policy | Question |
| --- | --- | --- |
| A0 | Single `flash` decoder surrogate and stop | Non-portfolio baseline |
| A1 | Fixed route over text→image→audio→video | Does a cheap deterministic controller suffice? |
| A2 | Frozen small top-k router fitted from independent training-episode per-expert net return per compute unit | Does conventional learned sparse routing suffice? |
| A3 | Greedy one-step risk/cost-adjusted NDU | Does one-step utility already capture benefit? |
| A4 | One-step KL-regularized, portfolio-covariance-adjusted allocation; selects highest allocation; deterministic fallback on unsupported covariance | Does portfolio risk improve routing? |
| A5 | Bounded exhaustive finite-horizon lookahead with interaction forecast, budget, legal modality and explicit stopping | Does continuation-aware control add value? |

A5 is **not an FBSDE solver** and its lookahead uses a synthetic forecast model; it is only a discrete dynamic-control reference. All six are evaluations, not actual model training. The fixed A1 route may match or beat A5; a reference-level difference is no efficacy claim.

## Signed independent-observer and host-meter evidence (advisory only)

The separate signed_evidence.py offline tool checks **detached Ed25519
signatures** on paired observations and resource receipts for every A0-A5
trial. The trusted observer and host-meter public keys, the expected frozen
objective digest and the time split cutoff must be supplied **out of band**,
not read from the submitted evidence. The two keys must be distinct.

Envelope format: JSON object with exactly two properties: payload
(a JSON object including role and the trial identity) and signature_b64
(an Ed25519 signature on canonical JSON payload bytes encoded as base64).
Canonical encoding is Python json.dumps(payload, sort_keys=True,
ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8").
A trial has observer and meter envelope members; the top-level manifest
identifies schema hepta.ndu-dmgp.signed-trials.v1 and contains trials[].

From the repository root:

    python3 qualification/ndu-dmgp-reference/signed_evidence.py REAL_TRIALS.json \
      --observer-public-key /trusted/observer.pem \
      --meter-public-key /trusted/meter.pem \
      --expected-objective-digest REGISTERED_SHA256 \
      --training-cutoff REGISTERED_TIME

The verifier binds objective, generation, episode, arm, run, trace, input
and artifact identities across independently signed records, checks frozen
split ordering and sample pairing, and rejects missing semantic or meter
evidence. For numerical diagnostics it requires at least 24 matched
episodes in each of train/future/retention. A paired A5 quality comparison
is **not** a general NDU superiority claim.

A signature authenticates bytes under a pinned public key; it does
**not** establish real device measurements, truthful semantic judgements,
a causally independent organization, trained models, identified conditional
covariance, Cell causal credit, Markov sufficiency or production admission.
The verifier always emits production_blockers_closed=false and
no_promotion_authority=true. CI keys and data are ephemeral test fixtures;
the tests must never be used as actual production evidence.

## Production evidence needed before closing blockers

1. Create a compatible versioned **Feature/Generation Proposal** contract bound to selected Encoder/Decoder/Head, tokenizer/preprocessor, objective, NDU snapshot, subject, generation, trajectory and remaining budget. Reuse existing owner admission. Do not extend a V1 wire format invisibly.
2. Run **real** shared encoders and at least text+image output Decoders in the designated inference owner, keeping massive latents in decoder workers; DecisionCell receives bounded state/summary features. Run all A0–A5 with equal compute and evaluation budgets, grouped, sealed episode assignment, and isolated held-out future outcomes.
3. Admit production resource receipts signed by the host and observer; attach matched per-episode utility observations under frozen registered objective and hard constraints. Calibrate risk in each supported condition, record sample/effective support, covariance residual/conditioning and abstain when unsupported.
4. Independently measure semantic and perceptual alignment (text–image first, then text–audio and audio–video), counterfactual/perturbation quality and OOD; structured contract checks here are not semantic consistency proofs.
5. Measure controller overhead **plus** true encoder/decoder cost, p95/p99, host RSS/GPU memory, quality per energy/latency, scaling with 64/256/1024/4096 logical cells and active-cell concurrency separately. Publish failure/rollback receipts.
6. Freeze baseline, critic, objective and eligible subjects. Use future-window, subgroup retention, negative transfer, KL/trust region, multiplicity-aware confidence bounds, observer independence and replay/correction checks. Selection and deployment remain separate Control/Evidence actions with no same-generation parameter replacement.

**Leakage rule:** training and evaluation episodes remain disjoint. Synthetic labels are not externally verified; training this toy router does not certify real learning, independent outcome truth or causal credit.

**Stop rule:** production blockers remain open until the user-requested real host, real task dataset, external outcome observer and signed execution artifacts exist, all canonical numerical/security gates pass, and independent acceptance is recorded. The reference runner never reports a production pass and has no capability to promote artifacts.
