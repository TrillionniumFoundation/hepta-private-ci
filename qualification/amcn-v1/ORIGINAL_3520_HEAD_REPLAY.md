# Independently replaying 3,520 original MiniLM MemoryCell Head forwards

Research-only / **DENY_ALL** / not a model selection or production artifact. This
adds *physical re-inference* to the existing original SHA-pinned material-only
audit, rather than counting immutable file hashes or original producer logs as
independently reexecuted model predictions.

## Original material and source identity

The original operator-staged local data, verified on 2026-10-14:

- LoCoMo ZIP SHA256: `07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`
- LoCoMo JSON SHA256: `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`
- MiniLM safetensors SHA256: `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db`
- Feature manifest RAW SHA256: `912931afc49f57dd3acd903ed2bef4a7c85dfbb7a2e3405f1640aca45b54b184`
- Original feature safetensors RAW SHA256: `33342df20c3d6348e32e4ff782bce9a269ec2dfbdb7ddb0611b7b46de67df11a`
- Original sealed prediction RAW SHA256: `d31296d818e90cd12fbe91f2c956d1271e9fe59c14bec32a88a631d95dcd8ac2`
- Original Head manifest RAW SHA256: `fc44ddf3dead1b24bee7be5b170f5b8b0a53960842a98475a4f55fe3188c3fe1`
- Original question-score RAW SHA256: `831474cd6f705367256a143310b1a60326f3f2cea9a5bc4d2eb31e2340bc7574`

Source-first candidate construction retains 15 questions with no publisher
weak support. The audit validates source and frozen feature *row order*, every
FP32 parameter tensor's geometry and original digest, and all five arm-specific
Head routing choices per each of the 704 non-TRAIN rows.

## Executed local result (not a hosted CI run)

Original physical files were reloaded and independently forwarded on a local
CPU/PyTorch process. Original 704 prediction rows × 5 Head arms = **3,520**
new HEAD forward calculations. Maximum absolute difference from the previously
sealed original predictions: **8.940696716308594e-08**, under the fixed
2e-6 refusal ceiling. Six Head safetensors are physically read; no original
publisher heldout targets are passed to the replay function.

Reproduce using the local 10-input `replay_original_head_forwards` function
in `amcn_typed_original_forward_verify_v2.py`, pointing to the exact original
ZIP, LoCoMo JSON, Encoder weights/vocab, feature tensors/manifest, sealed
predictions, Head bank, question-level scorer, and full public source roster.

The test module optionally executes the entire original replay when the
actual original files are already staged beneath
`HEPTA_AMCN_ORIGINAL_ROOT`. The ordinary hosted, read-only CPU workflow runs
the independent math/negative tests but does **not** stage the 376 MB original
archive. One explicitly **skipped** optional physical replay is NOT a hosted
3,520-call result. No staged archive, no executed material claim.

## Conservative results and research boundary

Original source-first historical weak-support Hit@1:
**lexical 14/44, typed 4/44, unspecialized equal-budget 2/44**.
A Head reproducing its old probabilities does not improve those outcomes.
A pair of `future_a/future_b` names is not two future calendar windows.
Neither a SHA-256 pin nor local manual MiniLM BERT/WordPiece implementation
verifies HF AutoTokenizer/AutoModel parity or independent data issuer identity.
The replay performs **zero new Encoder forwards and zero Reader calls**.

Before anything else may be called adaptive general memory: externally
authenticated source families, real prospective Reader task completions,
original matched strong-RAG controls, independent semantic entailment,
lifecycle costs, revocation+retrains, signed Selection, and the intact
`blocking-ci` and Architecture gates are required. Keep Draft and DENY_ALL.
