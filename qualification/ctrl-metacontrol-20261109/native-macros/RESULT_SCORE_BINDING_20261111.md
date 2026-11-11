# CTRL native macro result-to-scorer binding — 2026-11-11

**Draft / HOLD_NO_GO / NoUpdate.** Scope is the bounded native macro
receipt-acceptance boundary only. No model weights, policy, episode owner,
scorer, reference, historical original data or production permissions change.

## Exact source and counterexample

Direct parent is [CTRL #5975](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5975)
at exact head `dd528ce8aaf0e730f0166a7440cf97c42204cc91`.
The three tested parent Python files were independently fetched by the GitHub
connector and recreated byte-for-byte on HeptaRuntime operator `ai395`:

- `metacontrol_macro_contract.py` SHA-256 `9d2227af8dba2dbc3779c0225b7c6c551b68d2e83c3313bbda004c9c88fe07e2`
- `test_macro_pair_fixtures.py` SHA-256 `2cf3726f7cdd4613b06915267842bd2257dbe84a622233cd981a2049c7dbde42`
- `test_macro_wire_delivery_admission.py` SHA-256 `19449c7eafdc982b0e27a7fb1f451e58e045444dc3774e667386ee2d9c2dbbc1`

The unchanged original fixture tests passed **2/2** (job
`1a1cadd6ca3-2564-8b5`, complete exit 0). The original `observe_branch`
checked `score.quality == result.gross_score`, delivery/scorer pins,
wire chronology and finalizing WRITE_TEXT, but did not check the persisted
`result.json` or require `result.score_components`, `result.rubric_sha256`
and `result.output_text_sha256` to match the final snapshot.

New adversarial fixtures on the **unpatched exact parent** failed as expected
(job `1a1cadefbaf-2564-8ba`, exit 1): six subcases accepted incorrectly
across three test methods. Counterexamples: persisted-vs-returned result
drift; reported delivery/rubric/quality drift in `score_components`;
reported output-text digest drift; and reported rubric digest drift.
These are manufactured receipts, not independently observed original
six-case failures or an actual operator compromise.

## Minimal correction and verification

- Require the host's returned result to equal the persisted original
  `result.json` before crediting the branch.
- Require the complete final `score_components` to equal the scored snapshot,
  and bind its reported rubric and canonical output-text digest to the
  pinned evaluator/rubric and delivered text.
- Align only the manufactured fixture's standard EpisodeHost result fields;
  no result or score from the historical collection is edited.
- Add an independent adversarial test file, including rejection of omitted
  result fields. The existing normal STOP and READ fixture subcases remain
  positive.

GREEN `ai395` jobs: `1a1cadfff60-2564-8c2` passed 5/5 test methods
before adding the missing-field regression; `1a1cae1132e-2564-8c8`
passed **6/6** methods afterwards, zero skips, complete exit 0.
The GREEN suite includes sixteen adversarial subcases and two normal
STOP/READ subcases. AST/compileall succeeded on the repaired files.

## Claims explicitly not made

This establishes **self-declared receipt consistency only**. It does not
authenticate the native owner, reconstruct an unrecorded historical selected
index, prove the original actor was uncompromised, measure implementation
probabilities on new tasks, establish calibration, complete provider/energy
costs, execute independent matched READ/STOP confirmation, or show net
policy improvement against light/fixed controls. Keep the separate historical
audit branch #5969 unmerged; do not infer it has been integrated. The
full exact-head GitHub CI result and independent prospective scientific
qualification remain to be checked. Maintain Draft / HOLD_NO_GO / NoUpdate.

