# MemoryCell: exact original Git-source cross-cut gate (2026-10-13)

**Source acquisition succeeded; independent evaluation and memory promotion remain NO-GO.** This receipt combines *a read-only inventory comparison*, not the source populations, task questions, model outputs or target labels. The source cuts were registered at **2026-10-12 09:45 UTC** and **16:05 UTC**, so they are NOT a new jointly precommitted, prospectively blinded experiment.

## Original completed runs, not simulations

The original four-project run [38320754756](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38320754756) completed successfully. Its GitHub artifact `11779111741` (ZIP SHA-256 `0dd31ed0101c0125ee2c5f9ffe82ae71d083dcf4a00206eb65fdcc7cf75959e3`) retains 80 SHA-1-validated Git blobs from Rust, Kubernetes, NumPy and Ruff, with all 142 in-ZIP manifest files validated. The registered source-cut SHA-256 is `ef2a46ce037db4a91affddd2498eb8e089771ae5734bc13c56cb8a97b840a463`. There are also a first-parent byte comparison and an unresolved 31-reference two-parent merge comparison. Neither is a complete PR-base diff.

The separate six-project run [38320847158](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38320847158) completed with **both source acquisition and independent binary reopen successful**. Artifact `11778273351` (ZIP SHA-256 `a4c7b9868461c11558546bd582796255cbca682c938a1704d62cd93a556406b4`) contains 32 original Git blobs from CPython, pandas, Prometheus, scikit-learn, Tokio and Deno; the separately executed reopen artifact `11779107585` is pinned by SHA-256 `59dee0a84099f6fb101dbfd5420c569f10c44a2d8a7b67c984e381edf4db9d36`. Source-cut manifest SHA-256 is `cf2b783325d0f1b483953336041476e61877cdb547ad173adcd402f578bf3277`. One Deno blob contains raw non-UTF-8 bytes, **preserved and verified**, not silently decoded/replaced.

## Actual offline independent census

`project_two_cut_source_gate.py` verifies all **184 SHA256SUMS-listed file members** across the three original ZIPs (142 + 40 + 2), original generating commits, exact cut pins, all **112 original Git blob SHA-1** values, raw SHA-256 and sizes, per-project source partition exclusivity and the separate six-project binary reopen status. It independently re-reads 8,061,564 source bytes. It **does not** execute this untrusted code, run a Reader, open gold answers or issue reviewer credentials.

| Frozen batch | Repository-family proxies | Original Git files | Bytes |
| --- | ---: | ---: | ---: |
| Four projects (Rust, Kubernetes, NumPy, Ruff) | 4 | 80 | 6,503,104 |
| Six projects (CPython, pandas, Prometheus, scikit-learn, Tokio, Deno) | 6 | 32 | 1,558,460 |
| **Separate batches audited together** | **10 distinct repositories** | **112** | **8,061,564** |

Across the two existing cuts, **three** repositories are registered as training-source families, **two** as policy-selection families and **five** as evaluation-source families, with **zero repository-name overlap between cuts**. This is an identity census only. The original authored questions exist only for the four-project subset; there is no jointly pre-registered test/target population, and repository names are independence **proxies**, not a confidence interval's authenticated independent N.

## What does not pass

These bytes show that an external source corpus can be bound without faking generated evidence. They **do not** authenticate historical human PR discussion, prior branch-base diffs, source sufficiency for a particular question, reviewer identity or consent, pretraining contamination, fresh production events, revocation/rollback, full lifecycle cost or ≥99% semantic citation precision. In the four-project first-parent comparison, **31 merge-parent rows** required separate two-parent analysis and **one renamed path** lacks a preregistered predecessor. The supplementary two-parent sidecar records divergence or missing context, not a verified pre-PR patch.

The completed [40+72 Qwen trial](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38224780900) and the [160-call three-cohort read-only gate](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38366221868) remain **NO-GO** for incremental complex-graph answer/citation accuracy or parameter memory promotion. Do **not** treat those previously exposed tasks, the two independent cut timestamps, or these 112 byte bindings as new task-success evidence.

**Next authorized evidence stage:** separately freeze a single joint source-family/task protocol *before* reading answers; preserve exact source diffs and point-in-time review comments; obtain actual independent source-first sufficiency and citation judgments through a trusted reviewer owner; then compare the same frozen Reader across calibrated strong RAG, single hop, full-path filter and organizer using identical permissions, budgets and independent repository groups. Keep missing reviews in the denominator. Until then, `training_on_unreviewed_proposals_qualified=false` and `production_accepted=false`.

### Reproduction from immutable Actions ZIPs

```bash
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_project_two_cut_source_gate.py' -v
python3 scripts/memory_cell/project_two_cut_source_gate.py \
  original-four-project-artifact-11779111741.zip \
  original-six-project-artifact-11778273351.zip \
  separate-six-project-reopen-11779107585.zip \
  --output NEW_TWO_CUT_SOURCE_DISPOSITION.json
```

This is a model-free source-byte admission gate, **not** proof of substantive MemoryCell capability.
