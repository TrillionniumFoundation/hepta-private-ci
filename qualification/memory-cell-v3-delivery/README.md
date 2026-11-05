# MemoryCell v3: reviewable implementation and exact research history

This draft delivers real parameter training, native Hepta execution, numeric cells, typed composition, version ownership, structural experiments and independently audited evidence. **It does not assert all blockers closed or general memory qualification.**

Read [the measured report](../memory-cell-v3/RESULTS.md), [machine qualification](../memory-cell-v3/QUALIFICATION.json), [all real-source budget measurements](../memory-cell-v3/MEASURED_SUMMARY.json), and [the implementation/runbook](../memory-cell-v3/README.md).

## Formal outcome

Five seeds (307, 311, 313, 317, 331) ran all stages in 236.0132 seconds on CPU after source/protocol freeze. The complete formal seal verifies 4,920 outputs and 229 source/protocol/data files.

- Native parameter reads: 320/320 facts correct, 2,560 logits and 2,560 bits equal to the independent Python reference, 10 fresh native processes and 30 rejected invalid-input/state cases. Native signals still abstain; production calibration admission is inactive.
- Fixed multicell: four declared source/budget conditions pass with at least 5% hidden-MSE improvement in all five seeds. CO2/temperature negative outcomes and maximum-budget reconstruction errors are preserved; there is no new all-domain/all-budget gate.
- Typed graph: explicit-residual composition passes both edge ablations in 20/20 seed-domain cases. Semantic reliability fails in 20/20. Learned layout ties the strong supplied planner. This is not pure-parameter exact composition or autonomous type invention.
- Maintenance: 135,180 stage rows regraded, 15/15 old-exact retention floors, all exact-codec retention and serving revocation, 30 fresh readers. One old-value coincidence remains in raw withdrawn-coordinate parameters; no erasure claim.
- Evolution: only 4/20 strict cases pass. Convergent is 4/5, other flows 0/5. The failed seed 331 remains in means and costs. Ten splits and five consolidations were adopted; zero pair-merge candidates were trained or adopted.
- New economic domain: 348 facts written with zero router/layout updates, but 43.33% correctly accepted known queries and 25% OOD false acceptance on seed means. Reliable general memory is not established.

## Identity: mirror versus original execution

The API-created PR mirror commit is not the executed research commit. This branch exposes byte-exact source, fixed data, reports and compact analysis for review. Large raw result directories, every trained model, source snapshots, failed development attempts, full audits and original commits are stored in the ordered bundle parts.

| Identity | SHA |
| --- | --- |
| Required original repository baseline | `f8c9419df6ddeb36ff8b522a50219981fb8d9345` |
| v1/v2 exact research head required by v3 delta | `57d2b9658839f11aa4685049f90cb7142d59026d` |
| v3 actually executed source/protocol | `66dc3a2ed500a60b8abb6c01eb6fe9d501dc8ea2` |
| v3 final evidence/report commit | `ddd2ec4f9167c5ccf22adb63f4ce7402ebd7ae19` |

The v3 delta preserves **38 additional original commits**. The existing v1/v2 bundle preserves the earlier 35 commits. Both histories, including original commit identities, remain recoverable.

## Recover all source and evidence

Use a clone of this delivery branch containing the original repository baseline. The helper verifies the ordered v3 parts and both reassembled bundle digests before importing refs, and creates a new detached evidence worktree. It refuses an existing output directory or a conflicting destination research ref; it makes no network requests.

```bash
python qualification/memory-cell-v3-delivery/restore_evidence.py \
  --repo /path/to/hepta-private-ci \
  --worktree /path/to/new-hepta-memory-evidence
```

The helper finds the five original v1/v2 parts in `qualification/memory-cell-delivery/bundle-parts/` and the seven v3 parts beside this file. In the downloadable ZIP, it uses the two complete files under `bundles/` instead. `--v1-v2-bundle` and `--v3-bundle` can explicitly select previously downloaded files.

Manual v3 import, after recovering v1/v2 as described in [the prior delivery](../memory-cell-delivery/README.md):

```bash
cat qualification/memory-cell-v3-delivery/bundle-parts/hepta-memory-v3-history-20261026.bundle.part00? > /tmp/hepta-memory-v3-history-20261026.bundle
sha256sum -c <<'EOF'
ed9dc2f129051210b729e01281f16c6b863f17c71d5a474a7e3885509cd4cf3e  /tmp/hepta-memory-v3-history-20261026.bundle
EOF
git bundle verify /tmp/hepta-memory-v3-history-20261026.bundle
git fetch /tmp/hepta-memory-v3-history-20261026.bundle \
  refs/heads/research/memory-cell-v3-20261026:refs/heads/research/memory-cell-v3-exact-evidence
git worktree add --detach ../hepta-memory-v3-evidence ddd2ec4f9167c5ccf22adb63f4ce7402ebd7ae19
```

In the recovered evidence worktree, use the pinned requirements and the exact pretrained base identity described in the runbook. The shared MiniLM base and external runtime dependencies are obtained separately; all newly trained cell/router/layout weights and the actually executed native binary are retained in the evidence. Source verification requires Git history, so an extracted ZIP by itself is not a substitute for importing the bundles into a clone.

```bash
python qualification/memory-cell-v3/verify_evidence.py \
  qualification/memory-cell-v3/results/20261026-v3-frozen
python qualification/memory-cell-v3/audit_capacity.py \
  qualification/memory-cell-v3/results/20261026-v3-frozen --output /tmp/v3-capacity-new-audit.json
python qualification/memory-cell-v3/audit_routing.py \
  qualification/memory-cell-v3/results/20261026-v3-frozen --output /tmp/v3-routing-new-audit.json
python qualification/memory-cell-v3/audit_native_structure.py \
  qualification/memory-cell-v3/results/20261026-v3-frozen --output /tmp/v3-native-structure-new-audit.json
python qualification/memory-cell-v3/analyses/audit_lifecycle.py \
  qualification/memory-cell-v3/results/20261026-v3-frozen --output /tmp/v3-lifecycle-new-audit.json
```

Each auditor requires a new output outside the sealed run. Integrity verification and successful execution do not convert failed scientific gates into passes.

## Archive and asset policy

- V3 bundle: **54,731,928 B**; SHA-256 `ed9dc2f129051210b729e01281f16c6b863f17c71d5a474a7e3885509cd4cf3e`.
- Required v1/v2 bundle: **36,526,176 B**; SHA-256 `283ed9c9c966417c9ac72388e8f22f1f03b46620130e3f193cb31024586fce7d`.
- Formal v3 manifest: `5f52760eebc7407811b7778d09795e843bc73d1bbf9fe48cf27dfa5fad40af42`.
- [DELIVERY.json](DELIVERY.json) binds every ordered part, reviewable source/report byte and original identity. No source/report publication transform was applied.

Only the seven fixed v3 archive-part paths are added to the existing exact-path asset allowlist. The general 512,000-byte threshold, checker, CI workflows, production Cargo manifest and dependency lock remain unchanged. This remains a draft research delivery; no merge or product activation is included.
