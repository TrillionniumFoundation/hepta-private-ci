# Evidence and replay index

This directory preserves the frozen experiment, the completed evaluations, and the operational failures that preceded completion. Numerical success, learning success, and execution completion are separate claims.

## Readable results

- [Training summary](summary/RESULTS_TRAINING.md) and [machine-readable summary](summary/SUMMARY.json): all 72 training slots, all 24 groups, the original learning gates, paired ablations, and scoped costs.
- [Independent training metric reconstruction](INDEPENDENT_METRICS_VERIFICATION.json): 72 saved prediction pairs checked with NumPy, without importing the model or trainer.
- [Independent adaptation metric reconstruction](INDEPENDENT_ADAPTATION_VERIFICATION.json): 45 candidates, each on the old and new holdouts.
- [Adaptation final-test audit](ADAPTATION_FINAL_TEST_AUDIT.json) and [development audit](ADAPTATION_DEVELOPMENT_AUDIT.json): selections, retention, per-source metrics, and cost attribution. Their original download scope is preserved; the later independent reconstruction is a separate record.
- [Transfer records](transfer/): nine independently selected parent checkpoints, five known-interface positive controls each, and the copied-delta negative control.
- [Frozen training protocol](PROTOCOL_FROZEN.json), [adaptation protocol](ADAPTATION_PROTOCOL_FROZEN.json), and [transfer protocol](TRANSFER_PROTOCOL_FROZEN.json).

## Complete raw artifacts

[ARCHIVE_INDEX.json](archives/ARCHIVE_INDEX.json) enumerates 82 deterministic gzip/tar archives and records the SHA256 of every original member. [GIT_PUBLICATION_MANIFEST.json](archives/GIT_PUBLICATION_MANIFEST.json) records both the archive SHA256 and the independently computed Git blob SHA1 used to verify publication.

There are 72 `training--*.tar.gz` archives, nine `adaptation--*.tar.gz` archives, and one `run-metadata-and-source.tar.gz`. Together they preserve all selected and initial checkpoints, development histories, saved prefix predictions, final results, logs, frozen source dependencies, seals, the recovery records, and analysis/verification provenance. All member paths are relative to the formal run root. Extracting the archives into one new directory reconstructs that run; it does not restart any training.

[preflight-evidence.tar.gz](preflight-evidence.tar.gz) separately preserves the earlier numerical failures and fixes, smoke runs, runtime diagnostics, fixed-law cache measurements, FP32 backend comparison, formatter/clone failures, and their source snapshots. Its paths are rooted at the development evidence capsule. The readable `audit/*.json` files are copies of the principal records.

[PREFLIGHT_ARCHIVE_INDEX.json](PREFLIGHT_ARCHIVE_INDEX.json) binds the development archive and its members. [The publication verification](FORMAL_ARCHIVE_BLOB_VERIFICATION.json) and [transport ledger](FORMAL_ARCHIVE_BLOB_PUBLICATION.json) retain the completed main-archive transfer checks and the resolved transport interruption.

The exact signed-message-only control is a separate, explicitly post-results experiment: [results and scope](../../hcsn_signed_control_20261124/evidence/RESULTS_SIGNED_ONLY.md), [raw archive manifest](../../hcsn_signed_control_20261124/evidence/archives/ARCHIVE_MANIFEST.json), and [complete supplemental archive](../../hcsn_signed_control_20261124/evidence/archives/signed-control-v1.raw.tar.gz). Its nine fits do not replace any main-study slot, and the 45 adaptation candidates still belong to the original qvi_full parents.

## Interrupted evaluation and continuation

The original finalizer timed out with exit 124 after 63 complete training-test pairs and all nine adaptation-test workers. Its total CPU accounting could not be recovered. [The timeout record](audit/final_stage_timeout.json) retains that limitation.

[RESUME_CLAIM.json](training/RESUME_CLAIM.json) binds the unchanged seals, source, data, and 63 completed pairs. [RESUME_RECEIPT.json](training/RESUME_RECEIPT.json) records the nine missing slots run in fresh workers and checks that prior complete outputs remained byte-identical. [FINAL_STAGE_RECEIPT.json](FINAL_STAGE_RECEIPT.json) reports ten completed logical evaluation units while explicitly preserving the original failed process and successful continuation. It does not assert that the original coordinator exited successfully.

Nested CPU and wall measurements must not be added indiscriminately. The continuation's child-process CPU includes its nine evaluation bodies, and those bodies are also included in the 72-case body sum. Energy and unmeasured discovery costs remain unknown.

## Independent metric replay

After extracting the raw archives, run the supplied verifier against the reconstructed training directory and write a new output name:

```bash
python qualification/hcsn_smallnet_20261124/verify_predictions.py \
  --training /path/to/reconstructed-run/training \
  --output /path/to/new-training-verification.json

python qualification/hcsn_smallnet_20261124/verify_adaptation_predictions.py \
  --run-root /path/to/reconstructed-run \
  --output /path/to/new-adaptation-verification.json
```

These commands reconstruct metrics from stored logits. They do not independently replay the physical dynamics. Existing claims and results are intentionally create-only; use a new run directory for a new experiment instead of deleting claims or overwriting the recorded evaluation.
