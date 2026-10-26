# MemoryCell v1/v2: reviewable source and exact experimental history

This branch is a delivery mirror. The source, fixed data, reports, and analysis figures are visible for review. **Complete raw results, trained tensors, failed development runs, source snapshots, supplemental audit rows, and the original exact commits are inside the Git bundle below (stored as five ordered parts).** They are not duplicated as loose files on this mirror branch.

## Result

All four frozen v2 components ran across seeds 211, 223, 227, 229, and 233. The protocol's scientific acceptance gates did not all pass:

- The real-task single cell scored 100%; the actual-routed multi cell scored 98.9449% on the three-task macro primary. Multi minus single was -1.0551 percentage points, with a seed-bootstrap 95% interval [-2.9874, 0].
- Supplied typed composition depends on the correct edges; autonomous topology was not learned.
- Adaptive structure scored 55.1822% versus 52.7475% for fixed single. Only 2/5 streams met every strict gain and full-cost condition. Final clean accuracy was 32.49%–37.62%.
- Unseen-synonym routing had zero coverage. External Iris/Wine/Digits experiments demonstrate a shared classification interface, not general memory.
- Retention, versioning, lineage, clean retraining, and serving revocation mechanisms have saved evidence. A post-formal audit preserved all 320 deleted-key readout rows; 320/320 serving calls refused. This is not a certified unlearning result.

The full findings and measured costs are in [RESULTS.md](../memory-cell-v2/RESULTS.md), with a [machine-readable qualification](../memory-cell-v2/QUALIFICATION.json). Links into `results/` resolve after the exact evidence checkout below. Open empirical blockers are intentionally retained.

## Recover the exact source and evidence

The bundle contains 35 local research commits after the repository baseline and advertises `refs/heads/research/memory-cell-six-stage-20261025`. It preserves original commit identities; the API-created mirror commit itself was not the executed source.

| Identity | SHA |
| --- | --- |
| Required baseline | `f8c9419df6ddeb36ff8b522a50219981fb8d9345` |
| v1 executed source | `81fbc94963447ecb0e4bf6956d144d77e5a16e13` |
| v2 executed source | `d1204d6108eef75de384c8c8e98304b68984ffd1` |
| Final evidence/report commit | `57d2b9658839f11aa4685049f90cb7142d59026d` |

Run from a clone of this repository that contains the required baseline. These commands create a new evidence branch and worktree:

```bash
cat qualification/memory-cell-delivery/bundle-parts/hepta-memory-v1-v2-history-20261026.bundle.part00? > /tmp/hepta-memory-v1-v2-history-20261026.bundle
sha256sum -c <<'EOF'
283ed9c9c966417c9ac72388e8f22f1f03b46620130e3f193cb31024586fce7d  /tmp/hepta-memory-v1-v2-history-20261026.bundle
EOF
git bundle verify /tmp/hepta-memory-v1-v2-history-20261026.bundle
git fetch /tmp/hepta-memory-v1-v2-history-20261026.bundle \
  refs/heads/research/memory-cell-six-stage-20261025:refs/heads/research/memory-cell-v2-exact-evidence
git worktree add ../hepta-memory-exact-evidence research/memory-cell-v2-exact-evidence
```

In that worktree follow [the reproducibility guide](../memory-cell-v2/README.md). The model base and runtime binaries are restored separately from the pinned `MODEL_SOURCE.json` and dependency files. All trained adapter weights, included source snapshots, and raw predictions are in the bundle.

```bash
python qualification/memory-cell-v2/verify_evidence.py \
  qualification/memory-cell-v2/results/20261026-v2-frozen
python qualification/memory-cell-research/verify_evidence.py \
  qualification/memory-cell-research/results/20261025-six-stage
```

The formal v2 verifier checked 1,641 output files and 72 source/protocol/data files, with exact committed-byte binding. The v1 verifier checked 945 output files and 27 source files. There were 65 passing v2 mechanism tests with the actual pretrained reader enabled before final formatting; 28 source ASTs were unchanged by formatting. Twenty fresh processes reproduced 2,685 predictions. Reproducible loading is measured separately from answer correctness.

## Archive identity

- Bundle bytes: **36,526,176**.
- Bundle SHA-256: `283ed9c9c966417c9ac72388e8f22f1f03b46620130e3f193cb31024586fce7d`.
- Formal v2 MANIFEST SHA-256: `a5cb0b3075a2aff203f88a2e97c8278a4014d5b2d9d229558312270f776529be`.
- Supplemental readout MANIFEST SHA-256: `a557e5266eaee5c76e8e9409b2b71b457c959ba2bec8a8bb4090fef2662624dd`.

The independently verified downloadable ZIP is 64,194,728 bytes and contains 3,946 tracked project/evidence files plus its delivery manifest. Its SHA-256 is `57b81960e0ffd036f8ac4d491a4d6fdedc5832f2e05196465702fe59bc35ea02`. The ZIP is supplied with the local deliverables; this mirror stores the smaller exact-history bundle as five ordered binary parts. Concatenation has been independently checked against the original bundle bytes; the split is only a transport format.

This is a research qualification package. Native Hepta owner integration, production admission, general memory transfer, and autonomous type/topology discovery are not established. The mirror is provided as a draft for review; no merge or product activation is part of this delivery.
