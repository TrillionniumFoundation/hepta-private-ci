# Pair a production no-change baseline with the three Neuron model trials

**Scope:** read-only diagnostic. This **does not** sign, issue authority, invoke the
live Neuron worker, or independently validate an actual LedgerWriter/host clock.
The selected production no-change is **not** synonymous with the `laya`
external A/B arm or the `linear` Head arm.

Use the existing `hepta_neuron_real_cohort_preflight.py` on the independent
Evaluator host first. That tool requires five externally pinned Ed25519 roles and
links the exact sealed JSONL to `DatasetSnapshotReceiptV3`-named source digests,
actual selected baseline descriptors, observation hashes, and chrono splits.
Those exported facts are *claims* until the actual owner and Observer prove their
origin. The trust profile must be controlled **out of band**; don't derive keys
from the cohort or register test fixture keys as production signers.

## Signed production baseline observation receipt

The real production owner (or an independently authorized read-only exporter)
provides a JSON file that is **not shipped in the source tree**:

```json
{
  "schema": "hepta.neuron.production-baseline-pair.v1",
  "body": {
    "cohort_sha256": "<raw SHA-256 of signed cohort.json>",
    "trial_manifest_sha256": "<raw SHA-256 of experimental manifest.json>",
    "dataset_sha256": "<raw SHA-256 of sealed.jsonl>",
    "blind_dataset_sha256": "<raw SHA-256 of blinded.jsonl>",
    "source_dataset_digest": "<native frozen dataset digest>",
    "frozen_plan_digest": "<pre-registered plan digest>",
    "no_change": "<exact object from the signed cohort payload>",
    "revalidated_at_unix_micros": 1757000600000000,
    "observations": "<every calibration, holdout, future_1, future_2 row>"
  },
  "owner_signature": {
    "role": "baseline_owner",
    "key_id": "<pinned baseline owner signing key ID>",
    "signed_at_unix_micros": 1757000700000000,
    "signature_ed25519_hex": "<valid signature>"
  }
}
```

This JSON above is a **schema sketch only**; angle bracket placeholders and
string-valued example `no_change`/`observations` are **invalid inputs**.
The signed message is the UTF-8 canonical sorted/minified JSON of
`{schema,body,role,key_id,signed_at_unix_micros}`, prefixed by the byte domain
`hepta.neuron.production-baseline-pair.v1\\0` (with an actual NUL byte). The
signature uses the independently registered **baseline_owner** Ed25519 key.
This diagnostic provides no private-key tooling; signing must happen inside
the owning production trust boundary and remain separate from the runner.

A text-decision observation binds `id`, `split`, native
`decision_record_digest`, `observation_sha256`,
`production_runtime_receipt_digest`, actual
`decision_at_unix_micros`, frozen `generation`, disposition
(`selected` / `abstained` / `slow_path`) and optional `selected_option` (a
legal option ID only when selected). For a Head observation, replace disposition
and selected option with two signed `drive_q24` / `prediction_q24` vectors.
Each observation must have a decision-time between its native input and terminal
outcome. The same frozen generation is required across windows; changed
production policies must be compared as a **new** preregistered experiment, not
reinterpreted as frozen no-change.

Native owner requirements **outside** this script:

* Re-open or query the current `LedgerWriter` under an authorized owner;
  `freeze_dataset`, `read_dataset_records`, and
  `revalidate_dataset_snapshot` must all succeed with current revocation and
  source-use policy checks. A previous hash is not a current-use grant.
* Join an actual `AuthenticatedDecisionV2` and terminal
  `AuthenticatedOutcomeV2` per observation with an independently authorized
  observation payload. The option ID must come from the native selected
  candidate; do not infer behavior from a model's argmax or use an Outcome's
  utility as an automatic ground-truth choice label.
* Record the **deployed** model/policy/route/owner runtime identities and the
  actual outcome/decision times. An unsigned JSON runtime digest is not proof
  that a model ran or that the policy remained deployed.
* Keep evaluator-only raw labels, source-use grants and private keys off GitHub
  and the model runner. Require independent host/clock/provenance attestation
  before any substantive efficacy or resource claim.

## Evaluator-only diagnostic comparison

After supplying the **real** signed cohort, sealed labels, immutable manifest,
production no-change receipt and all Laya or Head arm receipts:

```bash
python3 scripts/hepta_neuron_production_baseline_compare.py \
  --cohort /evaluator/immutable/cohort.json \
  --sealed /evaluator/private/sealed.jsonl \
  --trusted-issuers /control-plane/independently-pinned-issuers.json \
  --trust-sha256 OUT_OF_BAND_TRUST_SHA256 \
  --trial-manifest /evaluator/immutable/trial-manifest.json \
  --production-baseline /evaluator/immutable/no-change.json \
  --arm-receipt laya=/evaluator/immutable/laya.json \
  --arm-receipt typed=/evaluator/immutable/typed.json \
  --output /evaluator/new/production-paired-diagnostic.json
```

Use `laya` and `multilingual` for the multilingual family; `linear`, `mlp`
and `swiglu` for the Head family. No absent or cherry-picked arm is accepted.
The evaluator independently rechecks the original model-trial input/weight/
SDK/host/candidate receipt identities via `hepta_neuron_model_trials.compare`,
then pairs outputs by the **same source case ID** with the separately signed
production no-change decisions. It rejects omitted/reused episodes, wrong
source digests, wrong generation, wrong chosen option, stale trust signatures,
mismatched sealed-input bytes, time drift, malformed Q24 Head vectors and
missing calibration/future windows.

Output deliberately reports:

* The **external** Laya-vs-Typed / Laya-vs-Multilingual or Head A/B summary
  separately from the actual deployed no-change result.
* For text-choice baselines: selection coverage, abstentions/slow paths,
  selective accuracy and correct-decision coverage. A deterministic baseline
  without observed probability distributions has **no** meaningful Brier/ECE;
  these fields remain `null` rather than being manufactured from hard choices.
* For Head baselines: signed Q24 prediction MSE and paired MSE differences.
* Candidate-better/worse/equal event counts by holdout, future_1 and future_2.
  This is a **paired outcome proxy**, not an NDU causal gain; any unmatched
  abstention/slow-path cannot be relabeled as a wrong answer.
* An optional, deterministic **source-group-level paired bootstrap interval**
  for candidate-minus-production accuracy or MSE differences. The bootstrap
  samples entire correlated source groups, never individual rows. With fewer
  than eight distinct source groups it returns a point estimate but NULL
  bounds and an explicit insufficient-groups reason. Resampling is bounded to
  1,024 deterministic draws and 4,096 paired cases, reproducible from the
  signed cohort/baseline SHA identities. These are purely **descriptive**
  intervals, not a preregistered causal test, an independent-time attestation
  or permission for NDU selection. Positive accuracy and negative MSE favor
  the candidate; an apparent gain cannot override a missing production gate.
* `ndu_net_gain_verified=false`, `selection_authorized=false`, and
  `production_promotion_authorized=false` regardless of candidate result.

**Production admission stays elsewhere:** the trusted `ProductEvaluationRunnerV1`
and original `LongitudinalTimeEvidenceV1` / `ObservedFutureWindowV1` verifier
must observe two genuinely elapsed future windows, independent Observer,
proper risk/utilities, retained no-change, negative transfer, resource cost,
recovery and rollback before an owner can even request promotion.

CI tests use only synthetic labels and ephemeral test keys. They cannot
materialize a real Ledger Owner, secret data, production baseline, real-time
observer, NDU utility, or authorization token.
