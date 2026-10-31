# P2 canonical evidence audit and create-only recorder — 2026-10-31

**RESEARCH_ONLY / DENY_ALL / NO_GO.** Based on draft PR #4505 exact parent 2d426c50fd25b2996440339f49ed6425161bf8c6. No production, historical observations, original training weights, Rust service or CI changed.

## Independent, source-readable increment

- audit_cpu_matched_v2.py is an independent Python stdlib validator of a lossless canonical 12-run archive. It rejects missing/duplicate/nonpaired observations, mismatched initialization or train/ID/OOD physical data, CPU caps, forged metrics and authority upgrades; recomputes all six paired accuracies without importing the model implementation.
- TIMED_CPU_MATCHED_FOLLOWUP_12_RAW_20261031.json.gz.b64 contains all final-snapshot training records, loss traces and paired comparisons. The uncompressed canonical JSON SHA-256 is e1dafffc43f22e2ed774b414be860d36ab2e17fcb9a16d1b332f80c3e45e471f (Git blob 88c6c3ffe9d7f30e051ec27533b605007c3540cb). **This structured reserialization does NOT independently authenticate the byte-exact original output files.**
- sealed_run_records_v1.py is a **future-run** local recorder: explicit safe run ID, fsync of staged file, atomic create-only hard-link, read-back SHA-256 receipt, collision/tamper/invalid-input denial, real new-Python-process readback. Not host signing, kernel crash recovery, distributed WAL or protection against a hostile local administrator. It is NOT yet wired into the training CLI.
- Eight independent auditor/recorder test methods cover missing/duplicate records, adversarial metric/budget/authority changes, same-path overwrite denial, symlink directory refusal, new-process readback and post-publication byte mutation.

## Results inherited from upstream #4505; NOT retrained here

12 CPU-matched exploratory runs; all six pairs within 0.0284% in observed process-CPU, 25.000–25.009 seconds. Averages over three paired seeds:

| Task | Split | Aggregate | Real-timestamp FIRE | FIRE minus aggregate |
| --- | --- | ---: | ---: | ---: |
| Copy | ID T16 | 99.219% | 93.229% | -5.990 pp |
| Copy | OOD T32 | 94.531% | 67.969% | **-26.563 pp** |
| MQAR4 | ID T16 | 56.706% | 56.185% | -0.521 pp |
| MQAR4 | OOD T32 | 55.339% | 55.924% | +0.586 pp |

**Important unresolved provenance defect:** upstream #4505 explicitly records three mutable output paths whose originally printed SHA/steps/CPU differed from the later frozen file snapshot, in TIMED_V2_OUTPUT_DISAGREEMENT_20261031.json. Earlier displaced byte content is unavailable. This audit can check current internally consistent final-snapshot records, but cannot retroactively recover or authenticate the earlier files or exclude tampering.

## Actual targeted local execution

Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0 and PyTorch 2.10.0 CPU, reconstructed HX subset, **not full byte-identical repository checkout**:

- P0 bounded numerical mathematics: **39/39 PASS**.
- P1/P2: **35/35 PASS**, including all 8 new audit/recorder methods.
- Total **74/74 locally targeted PASS**, zero skips. No claim of full CI, Rust, GPU, power-loss, physical energy or independent training replication.

To reproduce from an appropriate project checkout:

    python -m unittest -v experiments.hcsn_p2_memory.test_audit_cpu_matched_v2 experiments.hcsn_p2_memory.test_sealed_run_records_v1
    python -m experiments.hcsn_p2_memory.audit_cpu_matched_v2 experiments/hcsn_p2_memory/TIMED_CPU_MATCHED_FOLLOWUP_12_RAW_20261031.json.gz.b64

Remotely re-fetched exact Git blobs, matched to the locally executed sources:
auditor cd104118043fb10774ae4a834fbc730b76ee8cc5;
auditor tests 3af73712cc817a2fb725aa6dc88c54267968bc0e;
recorder e587cf58abefa809c0f792e21c9b7486cb2c7242;
recorder tests 28d8c16991cf2f307dc3f8036bf2416151376533.

## Hard admission remains unchanged

P0 **OPEN**: coupled financial HX equilibrium, global obstacle/continuum and interval proof, native precision/implicit-gradient safety.
P1 **OPEN**: independent equal-total-compute Call/Risk/Margin causal OOD advantage.
P2 **OPEN**: recorder integrated into actual training; complete provenance, robust overwrite/MQAR/long-memory, real host-crash journal and independent blinded confirmation.
P3 **OPEN**: four real pretrained encoders and cross-modal OOD.
P4 **OPEN**: native Rust/GPU 64–4096 Cell, CPU/RSS/p95/p99/Joules/restart.
P5 **BLOCKED**: matched-backbone net-value scaling only if P0–P4 close.

production_activation=false; all_scientific_blockers_closed=false. Keep Draft NO_GO.
