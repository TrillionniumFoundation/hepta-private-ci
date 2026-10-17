# Real Hepta Neuron data — owner-bound preflight (not qualification)

The Laya model card and a GitHub Actions CPU forward are **not** Hepta's
production no-change baseline. This gate intentionally introduces no model
selection, authority issuer, storage writer or alternate NDU evaluator.

## Native source of truth and missing operator inputs

A trusted Hepta host must first obtain its **currently selected** production
Cell/route/policy and current generation from the authoritative runtime/CAS
owner. The baseline can be a trained model or a deterministic fallback; it is
not automatically `convaiinnovations/laya`. Keep an exact *baseline runtime
receipt*, selected model/weight or deterministic code identity, artifact-load
receipt, checkpoint, route, resource profile, frozen policy and source-use
receipt. A historical digest without a current owner witness is insufficient.

For data, use `codex_hepta_learning_ledger::LedgerWriter` in the owning process:

```rust
// Sketch only — host-specific trust, data use and terminal joins required.
let dataset = ledger.freeze_dataset(plan, &independent_signed_evaluator, now)?;
let events = ledger.read_dataset_records(&dataset, now)?;
// Join only authenticated DecisionV2/terminal OutcomeV2 events, source uses
// and independently observed outcome labels; never reconstruct raw text from
// event digests or let the model runner see evaluation labels.
ledger.revalidate_dataset_snapshot(&dataset, now)?;
```

`DatasetSnapshotReceiptV3` carries a source set, source cuts, current ledger
head, dataset digest and outcome watermark. Those are **not** the actual
text, option candidates, correct answer, or an independent label witness.
The source/observation owner must authorize raw observation reads, bind their
exact bytes/meaning to a ledger support root, and supply the evaluator with
question/state/option order or exact numeric features. The independent
observer must supply terminality and label semantics; utility-valued outcomes
are not automatically correct-choice labels or Brier ground truth.

Revalidate the current ledger and current source permissions **again** at
model invocation, evaluation and artifact publication. Corrections, delayed
outcomes, consent withdrawal, revocation, stale source or uncertain identity
must exclude the affected cohort and invalidate derived caches.

## Read-only diagnostic input

`hepta_neuron_real_cohort_preflight.py` accepts three operator-controlled
inputs, all kept outside the Git repository:

* `--cohort` — JSON `{schema, payload, attestations}`. The `payload` binds
  `DatasetSnapshotReceiptV3`-named source fields, active sorted source event
  digests, terminal Decision/Outcome joins, immutable observed text/features
  digests, split, source group/episode and actual selected no-change descriptor.
  The complete payload also includes `sealed_dataset_sha256`, computed from
  **exact original sealed JSONL bytes** before anyone signs; modifying even
  one `gold` label invalidates the five signatures. `attestations` signs that
  *one complete* payload using distinct ledger,
  observation, baseline, evaluator and observer roles. This is an exported
  **claim**, not a native LedgerWriter object.
* `--sealed` — evaluator-only JSONL. Rows use the same `id`, `split`,
  `source_group`, `observed_at_ms`, model input and sealed label fields as
  existing `hepta_neuron_model_trials.py`. The file never goes to the model
  runner. Its observations must hash to the owner-signed joins. Training/
  calibration/holdout cannot depend on post-freeze events; two future windows
  must be distinct and non-overlapping after the baseline freeze.
* `--trusted-issuers` — a separately protected, host-owned trust root with
  `schema=hepta.neuron.real-cohort.trust.v1` and a `roles` mapping. Every
  role pins `key_id`, `principal_id`, `controller_id`, and a 32-byte lowercase
  hex `ed25519_public_key_hex`. **Do not load keys from the cohort packet**;
  pin the external trust file SHA-256 using `--trust-sha256` from a separate
  trusted control plane. Each attestation binds role, key, payload SHA-256 and
  claimed signing time using the domain-separated Ed25519 message implemented
  in the preflight source.

After the named host/Evaluator has gathered authorized inputs:

```sh
python3 scripts/hepta_neuron_real_cohort_preflight.py \
  --cohort /evaluator/immutable/cohort.json \
  --sealed /evaluator/private/sealed.jsonl \
  --trusted-issuers /trusted-control/issuers.json \
  --trust-sha256 EXACT_OUT_OF_BAND_SHA256 \
  --output /evaluator/new/real-cohort-preflight.json
```

The tool fails closed on mismatched or duplicate source events, repeated
Episode across splits, source-group leakage, identical input across splits,
nonterminal outcomes, sealed-label tampering, unavailable
future windows, incomplete currently selected baseline identities, invalid
role signatures, unbound raw observations, JSON ambiguity and clock unit
mismatch. It writes no raw prompts/labels or private signing keys to the
result. It never *signs* records itself.

**Caution:** cryptographically valid signatures only prove the registered
keys attested an export. This tool does **not** open a real LedgerWriter,
authenticate the current owner, establish the collection clock, perform
independent data use authorization, re-check source revocation, or run NDU.
The output always says `production_promotion_authorized=false`. It is
structural preflight, not the native product evaluation receipt.

## Qualification still required (separate owners)

Use the existing `hepta-intelligence-eval::ProductEvaluationRunnerV1` for
independently measured preregistered holdout outcomes, and the native
`LongitudinalTimeEvidenceV1` / `ObservedFutureWindowV1` verification for
system-longitudinal claims. Freeze plans before future observations; a
signed timestamp alone cannot prove the calendar elapsed. Compare each new
arm against *both* the original Laya A/B control and the **actual frozen
production no-change policy**. Require real effect/utility joins, causal
credit/confounder controls, Brier/ECE/OOD, negative-transfer and retention;
score 64/256/1024/4096 Cell resources and recoverability on the named host
separately. An unsupported dataset, unsupported model or zero utility gain is
an ordinary no-change/slow-path outcome, never a permission to promote.

CI intentionally uses only synthetic ephemeral signatures and data to test
rejection behavior. No real dataset, trust root or deployable model is
committed here. Do not activate production from any preflight result.
