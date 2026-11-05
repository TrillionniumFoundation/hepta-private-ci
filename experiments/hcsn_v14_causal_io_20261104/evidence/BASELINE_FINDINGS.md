# Read-only source audit for multimodal Hepta integration

## Exact current baseline

- Repository: `TrillionniumFoundation/hepta-private-ci`.
- V13 source PR #4619: `1a8f0b22e318bf919050f76b52a9c5feb5521ce9`, branch `research/hcsn-v13-followup-20261102`.
- V13 final evidence PR #4658: `3b9a136c56e9e743d7ecba852d621e1ecabf6bba`, branch `research/hcsn-v13-results-20261102`, root tree `a73135f913999aeb4012e6e5a8e6abb111cad10a`.
- Both remain open drafts. Newer HCSN search did not find a successor AV implementation after V13. PR #4708 archives historical source only and explicitly excludes weights/data; it does not close the missing original-v6 assets.
- Distinct v9/v10 closure lineage (#4579/#4598) has different source identities. It must not be silently combined with this source lineage.

## Existing implementation and limits

1. `joint_core/data.py` produces 55-dimensional rows using accepted audio/video prefixes. `row_from_cache` retains source time, modality event markers and fresh/cached feature vectors. IDs and labels are excluded from model rows.
2. `joint_core/model.py` has `ROW=55, STEPS=6, HIDDEN=32, CELLS=8`. Its content head has six padded history slots. `classify` rejects a seventh history row. No text/image encoder, arbitrary addressable memory or long-context content query exists in this path.
3. HX functions are real fixed-law financial functions; asset encoder and content model are trained. Reset is a sampled source-tick internal state transition with a 0.5-second refractory rule. It is not externally requested RESET, continuous first-passage propagation or all-financial-parameter training.
4. `control/runtime.py` supplies new-head value prediction to the inherited READ/WAIT/STOP scheduler. Value forecasts accept at most two ordered future READs. No externally requested RESET action is present in that executor.
5. V13's official pretrained audio representations are separate from the joint 55-dimensional corpus. `QUALIFICATION_CLARIFICATION.json` explicitly disallows cross-qualification. Merely making their descriptor shapes match would not establish task/data equivalence.
6. Training uses equal batches and 128 updates per fit, not matched CPU/effective capacity. The three retrieved seed13301 emotion candidates have HX31430 / GRU32550 / SSM29382 parameters.
7. All old TEST results are exposed historical development. The primary full-history source roster is only 24 TRAIN recordings (four actors), expanded to 240 correlated six-step schedules. Repetition is not a new-world cohort.

## Evidence that must remain negative/unknown

- Fixed V13 value-controller HX minus GRU utility: emotion -0.1400008333; binding -0.0027785417.
- Actual joint models: 36; optimizer updates: 4608; value readers: 36; policy episodes: 1944. These counts describe prior execution, not new execution in this audit.
- Original-v6 authenticated assets/task equivalence, semantic binding strong reference, complete historical exclusion ledger, new independent recordings and qualified common strong frontend remain missing.
- Complete project CPU, new-model process-family RSS, attributable device joules and historical preparation cost remain null.
- `all_blockers_closed=false`, `production_activation=false` in immutable V13 ACCEPTANCE.

## Reconstructed local inputs

`repo/` is a partial exact-byte reconstruction, not a full clone. All 21 joint-core PLAN source hashes and 29 control PLAN source hashes match. The original `AGENTS.md` is present; there is no `experiments/AGENTS.md` at this commit.

The selected read-only checkpoint set is the first declared seed 13301, task `async_av`, families `hx_full`, `gru`, `ssm`. Each retains original `weights.pt`, `NORMALIZATION.npz`, `TRAIN.json`; original TRAIN tensors and causal packets are retained. No training or quality experiment was run by this audit. Binary bytes are checked by expected size and Git blob SHA.

Reconstruction metadata is in `RECONSTRUCTION.json`; raw PR metadata and tree slices are siblings. Source files remain untouched for a future additive bridge.
