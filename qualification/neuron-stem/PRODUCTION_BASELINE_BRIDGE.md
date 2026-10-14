# Typed production no-change / Cell bridge

This is an evaluator-only supplement in the existing `four_gate_review.py`, not
another acceptance service. It reads original source/selected-baseline evidence;
it does not invoke a deployed owner, execute a model, issue grants or sign data.
The existing probability-based learning gate and its evidence floors are unchanged.

## Original owner code, not a new signature protocol

Stage `TrillionniumFoundation/hepta-private-ci` at
`aef947be91c9fbcac7f9f7315ecbc99122349e7d` in a trusted, private source directory.
The bridge checks the complete Git blobs of three original modules, copies only
those verified bytes into a private temporary directory, and invokes the original
cohort `verify` plus baseline `_check_baseline_receipt` using isolated Python.
No code path comes from the evidence packet; verifier changes need a reviewed pin.
The subprocess has a 30-second limit; each original input is capped at 4 MiB.
The evaluator supplies public-key trust bytes and their independently obtained
SHA-256 pin outside the evidence bundle. No private key is read by runtime code.

Signatures attest imported claims. Neither five role names nor five valid
signatures prove independent controllers, actual ledger state, physical model
execution, correct labels, a current permission, or elapsed future observations.
Native revalidation and production final-use remain with the existing owners.

## Same entrypoint, versioned supplemental bundle

Use `hepta.four-gate.evidence-bundle.v2` with the existing four `evidence` slots
and an additional `production_baseline` object containing seven original-byte
references: `cohort`, `sealed`, `manifest`, `baseline`, `dataset`, `trial` and
`prelabel_journal`. Each reference is the existing `{path, sha256}` shape.
The first four are unchanged #1494 owner inputs; the last three are the original
Cell dataset, trial and pre-label journal. Null/missing dependencies do not pass.

The frozen plan remains plan.v2 and adds `production_baseline` with exactly:
`profile=typed_production_policy_pairing.v1`, the pinned `owner_source_sha`,
`expected_descriptor_sha256`, `owner_frozen_plan_sha256` and a preregistered
`max_revalidation_age_us` in [0, 86400000000]. The latter is checked relative to
the declared assessment time, not represented as a live owner query.

Cell future case IDs must equal the complete owner future-case inventory. Scope
digest, source group, event time, window, state, question, option order, language,
domain and sealed label mapping must match. The dataset needs explicit `domain`
and `native_scope_digest` fields. No guessed ID join, success filtering, domain
hint substitution or hard-choice-to-one-hot conversion is accepted. The factored
`verify_cell_trace` reuses all existing Head seal, initialization and update-chain
checks; legacy `verify_and_index` still requires its genuine no-change probabilities.

The supplement reports frozen/trained shadow-argmax results, actual baseline
selection coverage and conditional accuracy, and better/worse counts on the
baseline-selected subset. Abstentions and slow paths stay separate. Baseline
Brier/ECE remain null; zero selections imply undefined selective accuracy.
`diagnostic_complete` is only completed verification/pairing. It does not prove
retention, OOD risk, causal gain or lifecycle resource improvement and does not
replace the probability learning gate. The supplemental bundle always retains
`current_acceptance_profile_passed=false`; its CLI exits 2, never promotion success.
An actual future typed-policy acceptance profile requires its own preregistered
risk/coverage/retention, uncertainty and cost comparison, not invented probabilities.

```sh
python3 qualification/neuron-stem/four_gate_review.py \
  --root /evaluator/immutable-evidence \
  --plan plan.json --plan-sha256 "$PLAN_SHA256" \
  --bundle bundle.json --bundle-sha256 "$BUNDLE_SHA256" \
  --baseline-owner-root /evaluator/pinned-owner-source \
  --baseline-trust /control-plane/public-issuers.json \
  --baseline-trust-sha256 "$INDEPENDENT_TRUST_SHA256" \
  --output /evaluator/new/typed-baseline-review.json
```

Keep sealed labels, source-use grants, real production packets and private keys
off GitHub and model workers. Hash/authority failures reveal no sealed row text in
subprocess diagnostics. Original file hashes and verifier/trust identities remain
in the report. Outputs use the existing exclusive-create writer.

## Verification

Local qualification subtree: 179 model-free regressions and 10 real CPU tensor
tests passed without skips. The separate `baseline_owner_bridge_checks` suite
requires the actual pinned owner checkout and cryptography; missing dependencies
fail instead of skipping. CI runs original owner tests and the bridge's generated
signature fixtures on source-head and prospective-merge checkouts independently.
All fixture keys are ephemeral, not production signers. Exact-head CI results and
real owner evidence must be read independently; local tests do not assert them.
