# Cosine residual TRAIN-scope regression and retry

Date: 2026-10-15.

The initial workflow run `38535740819` for source
`e10500d5f1c6dd9ba2711d9d060ea7b17be93695` was cancelled before its job began;
it produced no steps, logs or artifact. The exact same fixed job was re-run. Its
second attempt reached the regression step and failed before dependency
resolution, model acquisition, Encoder loading or Head fitting.

## Actual failure

The new TRAIN rectangle builder reused
`shared_gate_crossed_evidence.component`. That helper is intentionally scoped to
SELECT and creates cache identities beginning with `select`. The residual study
was constructing TRAIN questions and evidence, so the strict public-feature
identity check correctly rejected those keys as not previously encoded under the
registered TRAIN scope.

Sixteen tests failed from this one fixture-construction error. All other required
suites continued and passed. The failed artifact is `11939561315`, GitHub ZIP
SHA256 `b882c240f7c1bd2c74cd59c879a79660a41220f1c4859a39052b36c162203c0f`.
Its explicit disposition records `model_execution_completed=false`. No model
load, new Encoder forward, residual optimization or Reader call occurred.

## Correction

`shared_gate_cosine_residual.component` now creates feature identities with an
explicit partition. TRAIN rectangle construction uses `train` for the recipient
question, donor question, recipient evidence and donor evidence. The historical
SELECT helper and its completed result are unchanged.

The correction also binds each reconstructed original-source row to the exact
registered TRAIN family instead of relying on a later key mismatch. A dedicated
regression checks that all reused question/donor-evidence keys resolve to
existing TRAIN-scoped public features and that newly added own-evidence features
are also TRAIN scoped.

No scientific setting changed: the fixed cosine threshold, four arms, three
seeds, 256 steps, rank 8, learning rate, recipients, donors, labels and SELECT
readout remain exactly the same. Historical failed/cancelled attempts and their
costs remain visible. The corrected model experiment is not claimed successful
until the new exact-source workflow completes.
