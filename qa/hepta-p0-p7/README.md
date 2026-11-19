# Hepta P0–P7 evidence gate (research-only)

This additive audit is **not** another Encoder, Cell, runtime owner, or permission path. It is a fail-closed, standard-library gate for candidate experiment bundles. No submitted JSON, passed unit test, or checksum by itself authenticates a pretrained model forward, a human evaluation, independent CI, or production authority. **All outputs remain `DENY_ALL / HOLD_NO_GO`.**

## Evidence and run contract

The operator freezes a `protocol.json` **before** evaluation and passes its independently recorded SHA256 via `--protocol-sha256`; the protocol contains exactly nine arms (`base`, `static`, `moe`, `router`, `best_of_2`, `risk_neutral_mpc`, `fixed_risk_mpc`, `ndu`, `ndu_no_cov`), at least three decoding seeds, an Encoder digest/generation, a positive hard episode budget and a common-random-number plan. Do not use a checksum supplied *inside* the protocol as an independent pin.

Supply source `sources.json` and historical exclusions `history.json`, followed by a complete `episodes.jsonl` containing *every* test source × seed × arm. The source manifest records original-file hashes, original source-family IDs, file paths, split (`train/dev/calibration/test`), and modalities. The audit opens original files, hashes bytes, rejects cross-split family leakage, historical exact-byte collisions, symlinks and traversal. It requires ≥128 **distinct declared `original_group` IDs in the test split**, not merely 128 differently hashed frames/crops derived from fewer recordings. Multiple file views of one group remain permitted and are counted as files, not newly independent sources. The report separately exposes `source_groups`, `heldout_source_files`, `declared_source_group_provenance_verified=false`, and `independent_source_clustered_inference_verified=false`. The latter flags are intentionally false: this is an identifier-consistency gate, not authentic source custody, independence proof, or group-clustered statistical inference. This does **not** exclude foundation-model pretraining overlap, near duplicates without matching bytes, forged group IDs, or recurring real-world entities. Descriptive means/tails still weight file-level rows; they are not claimed as independent-source significance tests.

Each episode binds source hash, seed, common-noise digest, actual action trace, full trace digest and action digest, Encoder owner/generation/one shared forward, all selected Cell feature identities, full measured cost components (`encoder/head/controller/verifier/decoder/io`), validity, coverage, severe errors, quality and saved output bytes. Valid completed NDU episodes must contain **8–16 actually recorded** state-linked decisions; declaring a depth capacity is not enough. Nonzero risk coefficient is mandatory; zero-risk NDU fails. Incomplete or overbudget outputs get quality zero and severe=true and stay in the denominator. Each arm must be present for each source/seed, with identical predeclared common-noise identity.

The script produces descriptive quality, top-tail CVaR90, actual wall, coverage and mechanism observations, including paired episode cost/coverage parity and whether a covariance removal changed a traced action. Descriptive mean dominance **does not** imply superiority: multi-seed original-source clustered confidence intervals and independent task scoring must be obtained separately. The covariance-effect flag compares the **actual action sequences**, not merely two digest values; the complete recorded state transitions and paid step costs are separately digest-bound. An arbitrary hash or counterfactual action difference never establishes causality.

```bash
python3 -m unittest discover -v -s qa/hepta-p0-p7 -p 'test_*.py'
python3 qa/hepta-p0-p7/qualification.py \
  --protocol /absolute/path/protocol.json \
  --protocol-sha256 <independently-frozen-64-hex-SHA256> \
  --sources /absolute/path/sources.json \
  --history /absolute/path/history.json \
  --episodes /absolute/path/episodes.jsonl \
  --artifacts-root /absolute/path/artifacts
```

Exit codes: **3** invalid evidence; **2** structurally consistent evidence but insufficient externally authenticated P0–P7 promotion proof. **No exit 0** is currently defined. Local synthetic 128-source/three-seed examples exist *only in tests*, never as experiment results.

## Hosted exact-source audit execution (research-only)

The isolated CI follow-up runs this **standard-library-only** evidence audit
on GitHub's `ubuntu-slim` runner, where the Python 3.12 runtime was actually
observed in the independent finite-portfolio workflow. It does not require a
GPU, natural pretrained checkpoint, privileged self-hosted runner, or package
installation. Checkout is pinned to the triggering PR Head SHA (or dispatch
SHA), with persisted credentials disabled. A separate step checks that
`git rev-parse HEAD` exactly equals that event SHA **before any validation**.
The full unit suite, syntax compilation, and the no-evidence exit-code-3
fail-closed check remain identical in meaning. Host identity, version and
CI completion are observed from actual logs, not presumed from the workflow
source or a queued job. This hosted check never supersedes the distinct
whole-repository, cross-platform, device, provenance and production gates.

## P0–P7 research and production gates

| Gate | Required external closure (never inferred from this script) |
| --- | --- |
| P0 | Real, independently witnessed single physical Encoder forward reused across a Cell group; exact generation, input/source, feature and physical-cost accounting; applicable exact-head CI. |
| P1 | New task + time-holdout + publisher/entity OOD, calibrated coverage, minority slices, strong linear/retrieval/pooled equal-cost controls, independent outcomes. |
| P2 | Natural image/audio/video as applicable, full decoder/codec outputs, missing/misaligned modality rejection, original source-level isolation and codec quality. |
| P3 | 8–16 observed, causally valid multi-step decisions with Verifier and backtrack; independent verified task score and paired superiority over direct and best-of-N at matched cost. |
| P4 | Trained real-state/outcome NDU Critic, nonzero causally effective risk and covariance term, risk-neutral MPC and fixed-risk comparisons, source-cluster multi-seed confidence intervals and no protected-task regression. |
| P5 | Offline success-trajectory distillation and true novel-cohort gain over frozen Group/Stem controls without retention/OOD/privacy regression; no online unreviewed Stem write. |
| P6 | Independently tested split/merge/retire, multi-generation replay, source withdrawal, failure recovery and rollback, with authentic provenance and owner authorization. |
| P7 | Whole-repository exact-head CI on required platforms, target-device physical p95/p99/energy and 4,096 Cell resource costs, independent source/ledger/CAS/FinalUse governance. |

## Frozen negative baselines must remain negative

- [P37 #3110](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3110): real Encoder/private Head training, but gated-vs-linear accuracy not improved and selective/OOD qualification failed.
- [P39 #3122](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3122): real text/image source-pairing success; missing-modality raw Head unsafe until separately guarded; gating superiority, semantics and target hardware not established.
- [P41 #3227](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3227): 4,096 independently allocated Heads using replicated learned templates; not 4,096 independent learned abilities and not Encoder-inclusive cost.
- [Memory #3125](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3125): sparse routing and evolution work, but baseline improvement, abstention and tiny-student transfer not established.
- [NDU v1 #3213](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3213): 768 test episodes, NDU quality 0.833594 versus best-of-2 0.869010, zero selected risk weight, 2–3 actual decisions and higher wall time; **negative** superiority result.
- [NDU v3 #3370](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3370), [v4 #3393](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3393): limited feedback and four-output finite-mechanism results; natural-data generality and production gates remain open.

This gate intentionally does not manufacture an aggregate `all_blockers_closed=true` value. New evidence must be independently reviewed, signed and promoted by the existing owning governance; do not use this file as authority.
