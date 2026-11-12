# Historical PERC trained-head native ownership qualification

Scientific status: **HOLD / NoUpdate**. Engineering: **PASS_HISTORICAL_HEAD_AND_OWNER_REPLAY_ONLY**.

Six archived trained tanh ranking heads were executed through native inference
and durable Cell ownership: **180 historical cases, 30 reused tasks, six models**.
No new training, capture, OCR, backbone inference, independent source confirmation,
production daemon enrollment, or terminal-task benefit qualification occurred.

## Final observed gates

| Gate | Result |
| --- | --- |
| Actual native boundary tests | 8/8 passed; zero failures, errors, or skips |
| Python/native ranking agreement | 180/180 |
| Maximum absolute FP64 logit difference | 3.5527136788005009e-15 |
| Cold process replay without inference | 180/180 |
| Lost-ACK original readback without inference | 6/6 |
| Expected refusal controls | 2/2 |
| Candidate identity mapping | Validated |
| Diagnostic sparse Cell matches raw MLP top | 0/180 |
| Diagnostic sparse Cell abstentions | 180/180 |
| Inclusive final driver wall time | 113.864243 seconds |

The original FP64 row/head bytes are frozen. Native outputs retain IEEE-754 bit
patterns for exact replay and commit their digest through the owner output.
The auxiliary 32-value prediction channel stores digest bytes and has no
predictive interpretation; calibration remains a hand-authored fixture.
Python/native initial JSON arithmetic parity is measured above; it is not claimed
bit-identical. Sparse Cell/calibration guards retain diagnostic settings. Raw MLP
ranking, sparse selection, and abstention are separate observed quantities; none
establishes product adoption or task benefit.

## Historical identities and failed attempts

The loader verifies the original archive `c57d32d04d3927a5457fec2e4d2a8a8840976df754e90b644b36f0ff414466cf` and reconstructs
TRAIN feature digests for all six heads. Actual historical counts are
60 TRAIN / 20 DEV / 30 confirmation; stale descriptive panel metadata differs.
DEV was not reexecuted. All 180 cases reuse the historical confirmation panel.

`RUN_CLASSIFICATION.json` preserves run-v1 FP64 self-parse failure, run-v2 raw
math success with invalid different-ID Cell comparison, and final run-v3.
The old run-v2 0/180 comparison is invalid, not a negative policy result. Original
TESTS_V1 code_sha256 map-versus-string failure, all four test snapshots, all three
runs, logs, and selected build/source snapshots remain in the verified archive.

## Reproduce and review

Use `.github/workflows/hepta-perc-trained-native.yml` for the isolated native
build and prerequisite pins. With the configured native binary:

```sh
export PYTHONPATH=scripts
export PERC1_SEMANTIC_NATIVE_BINARY=/absolute/path/to/native-binary
python3 -m unittest discover -s scripts -p test_perc_semantic_native.py -v
python3 -m perc1.semantic_native_qualification --native-binary "$PERC1_SEMANTIC_NATIVE_BINARY" --archive qualification/perc-semantic-owner-20261110/raw-evidence-v1.tar.xz --output /absolute/new/run-directory
```

Outputs are create-only. `RAW_FILE_MANIFEST.json` commits every archived original;
`EVIDENCE.json` identifies the archive and verifies all members. No executables,
private FUNSD originals, or earlier unrelated ZIP are included.

Process envelopes and inclusive driver wall overlap; do not add them. Older
inclusive timings describe their own attempts. No product cost saving, energy,
billing, distributed recovery, power-loss, or daemon qualification is established.

Four review stages: bounded model port; owner/output commitment and recovery;
archive loader/replay driver; boundary tests, strict CI, and evidence.
