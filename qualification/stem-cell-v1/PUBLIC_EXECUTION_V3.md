# Pinned public-weight execution and saved-tensor replay

Parent: PR #1652, `30d37744c9d86410654f5563d2e672dbf5afab89`.
This is an additive research continuation in the existing qualification directory.
It does not select a production Stem, replace mmBERT/Jina, modify native owners,
relax safetensors loading, or close any production/longitudinal efficacy gate.

## Why this increment

The prior path required a compatible local safetensors snapshot but had no
complete public provisioning/execution job. The pinned mmBERT-small publisher
revision contains a legacy `.bin` file. Rather than introduce pickle conversion
or relax exact tensor matching, this increment tests a separate official
safetensors candidate through the SAME `FrozenLocalHfBackend`.

A second defect was evidence completeness: the reviewer checked prediction and
selection JSON hashes but did not verify the referenced checkpoint files or
bind the normalizer. New run/selection schemas are explicitly V2; old source
and V1 records remain historical, not silently reinterpreted as qualified.

## Immutable external sources

- Model: `BAAI/bge-small-en-v1.5`, revision
  `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` (MIT).
- The published `model.safetensors` SHA256 is
  `3c9f31665447c8911517620762200d2245a2518d6e7208acc78cd9db317e21ad`.
- Dataset: `clinc/oos-eval`, revision
  `828f8093932c8fe6ca7936c3d2e52903b1c523de`, `data/data_full.json`,
  Git blob `7a7b26c5f2dfbbf213f3e67d2dd0727e1af545aa`, 2,495,390 bytes.
- Attribution: Larson et al., *An Evaluation Dataset for Intent Classification
  and Out-of-Scope Prediction*, EMNLP 2019. The original CC-BY-3.0 license is
  downloaded and byte-bound alongside the prepared data.

Publisher reference pages:
https://huggingface.co/BAAI/bge-small-en-v1.5/tree/5c38ec7c405ec4b44b94cc5a9bb96e735b38267a
https://github.com/clinc/oos-eval/tree/828f8093932c8fe6ca7936c3d2e52903b1c523de

`public_structural_stage.py` is a separate, explicit network provisioner with
only fixed public URLs. It verifies revision metadata, bounded exact byte
counts, Git/LFS content identity and the fixed weight SHA. It stages six files
outside the source checkout, refuses remote-code architecture maps, and never
loads model code itself. No `.bin`, custom Python, implicit token, model mutation,
conversion, broad repository download or random-weight fallback is introduced.
Publisher metadata and hashes are not independent hardware/owner attestation.
Partial downloads and FAILED records are preserved; no success manifest follows.

## Public partitions are not observation windows

The eight intents are fixed before execution: alarm, calendar, date, reminder,
time, timer, todo_list and weather. This is NOT the entire CLINC150 benchmark.
For each intent all original 100 training utterances are partitioned 40/30/30
into base/adapt/extra by source-content hash. All 20 official validation and
30 official test utterances remain in their publisher partitions, producing
1,200 rows and up to 1,200 held-out arm predictions (240 examples x five arms).
Unsupported split routing still yields an explicit unavailable arm, never a
fabricated checkpoint.

`time_basis=publisher_partition` is allowed only with public_retrospective.
All observed_at fields must be null, and future_1/future_2 are forbidden.
The default observed_at profile still requires actual timezone-aware ordered
windows. No artificial timestamps or fabricated prospective observation follow.
Source/episode/content isolation and the fixed ordered label schema remain.
Any overlap or missing selected row rejects the run instead of being silently
removed. Raw publisher bytes and per-row lineage are retained separately.
Content-based groups detect reuse; they do not establish independent speakers
or independent paraphrase seeds. Any calibration split choice remains conditional
research selection, not authenticated significance or production promotion.

## Executed path and numerical replay

The existing real-weight study still performs complete safetensors key/value
materialization checks, physical serial/no-cache versus shared-batch encoding,
one trained parent, and frozen/continued/wider/more_data/split controls. The
shared backend's mean pooling is intentionally unchanged; this is not an
assertion of reproducing BGE's published sentence-embedding recipe or leaderboard.
This component probe does not compare duplicated-421M residency or qualify p99.
The study captures the complete loading/materialization reports in run.json.

Every new V2 run binds normalizer bytes and referenced checkpoint bytes.
`seal_replay=true` separately opts into saving scoped f32 features and label-free
input identities BEFORE prediction. The public profile uses this opt-in; private
or prospective runs do not export derived feature matrices by default.

`development_study_replay.py` is a separate command and implements the declared
Head/routing formula directly. It does not import the fitter, RoutedBank or
BasisCellHeads. It validates bounded safetensors byte buffers, actual checkpoint
hashes, normalizer derivation from base training only, feature row order and the
complete prediction census. It then recomputes logits, with fixed absolute error
<=1e-5 and zero argmax reversals. Rehashed wrong logits and rehashed wrong
normalizers are negative tests. Matching all hashes alone cannot satisfy this
arithmetic check. A fully fabricated mutually consistent bundle would still
require independent execution attestation; numerical replay is not that proof.
The ordinary separate reviewer now refuses unbound/changed checkpoint files
before scoring. V1 runs require their historical source, not retroactive upgrades.

## CI and reproduction

The existing development workflow retains head AND prospective-merge mechanism
jobs, now including `public_structural_checks`. Only after both pass does its
new exact-head public-pretrained job provision pinned inputs, set HF offline
mode, run the existing five-arm study, run saved-tensor replay and separately
score the original predictions. Dependency or input failure is fatal; tests are
not skipped and failed downloads are not replaced. Artifacts retain exact source,
environment, lineage, learned small Heads, derived features, outputs and failures,
never the pretrained model weights or credentials.

```sh
PYTHONPATH=qualification/stem-cell-v1 python3 -m unittest -v \
  test_shared_encoder_eviction development_tensor_checks \
  development_repository_checks development_study_checks public_structural_checks
PYTHONPATH=qualification/stem-cell-v1 python3 qualification/stem-cell-v1/public_structural_stage.py --help
```

For the full physical commands use the existing workflow's
`public-pretrained-execution` job; its run inputs and outputs are outside checkout.

## Observations on this continuation

Local PyTorch CPU mechanism run: 79 tests passed, zero failures/skips. This uses
the prior partial source reconstruction with the original connector-fetched
model_runner/study function extracts in local_reference, not a full native build.
No extracts overwrite repository sources. Full-source head/merge tests remain
mandatory. Local physical staging was actually attempted and failed with DNS
resolution error before pretrained bytes or a success stage.json were obtained.
This failure is retained, not called a pretrained result. Current CI status must
be read on the new exact SHA; queued, skipped and predecessor results never pass.

Native Worker/Cell CAS/WAL/final-use, independent no-change, real future windows,
energy/RSS scaling, split efficacy, recurrent semantic reasoning, multimodal
understanding/generation and cross-Cell long-term retention remain separate
uncompleted gates. No 10T/100T equivalence, production activation or model winner
is asserted by this change.
