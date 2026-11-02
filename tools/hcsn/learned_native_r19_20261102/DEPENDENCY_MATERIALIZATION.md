# Pinned cross-candidate dependencies

This native candidate depends on several frozen trees. Materialize exact paths from these commits before running; do not substitute branch latest. The final integration commit will combine the pinned trees.

- Learned Python task/models and source freeze: `1b465bf73f0aebc74886e638b5cb8906666c51f9`, under `experiments/hcsn_learned_core_r19_20261102/`.
- Actual80 fitted checkpoint bytes and preparation evidence: preconfirm transport commit `c4954a2e67a1ba12fb980472f040a3adaeb325a6`, under that learned directory's `transport_preconfirm/`. These are training artifacts frozen before confirmation, not new native training.
- Independent Rust uniformization `tools/hcsn/native_numeric_r19_20261102/numeric.rs`: pinned source commit `4bf8e0af958d9dc77d9943a58729543431b2df5b`.
- Original R15 owner/law/transitive finite-cell source and `tools/hcsn/native_owner_r18_20261101/common.rs`: inherited integrated R18 base `b25601c9bae257ffb651c8f9354fc380d8333f38`, with exact29dependency digests in the new native `SOURCE_FREEZE.json` (including the16original analytic checkpoint digests).

Restore the preconfirm logical files beneath the learned module directory, rather than beneath the project root:

```sh
python experiments/hcsn_learned_core_r19_20261102/transport_preconfirm/RESTORE.py \
  /absolute/project/experiments/hcsn_learned_core_r19_20261102
```

The transport validates every part, archive and restored logical file. Existing matching files are accepted; mismatches fail. This creates `run_01/weights_*.pt`, `SELECTION_FREEZE.json` and preparation records at the exact paths the native origin checker uses.

Then materialize the native candidate's own frozen source plus actual `profiles_v2/*.model`. Its formal driver checks all source/dependency SHA256, verifies every export against the original checkpoint at original dtype, and requires the native source publication receipt before generating formal owner worlds. Rust1.95 is used; Torch CPU is available in this environment through `PYTHONPATH=/tmp/hcsn-torch-runtime`.

This materialization note was added after the native source freeze as integration guidance; it changes no frozen executable, profile or protocol.
