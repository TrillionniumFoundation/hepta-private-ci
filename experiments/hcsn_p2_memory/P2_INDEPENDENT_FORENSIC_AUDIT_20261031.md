# P2 canonical evidence audit and create-only recorder — 2026-10-31

**RESEARCH_ONLY / DENY_ALL / NO_GO.** Based on draft PR #4505 exact parent 2d426c50fd25b2996440339f49ed6425161bf8c6. No production, historical observations, original training weights, Rust service or CI changed.

## Independent, source-readable increment

- audit_cpu_matched_v2.py is an independent Python stdlib validator of a lossless canonical 12-run archive. It rejects missing/duplicate/nonpaired observations, mismatched initialization or train/ID/OOD physical data, CPU caps, forged metrics and authority upgrades; recomputes all six paired accuracies without importing the model implementation.
- TIMED_CPU_MATCHED_FOLLOWUP_12_RAW_20261031.json.gz.b64 contains all final-snapshot training records, loss traces and paired comparisons. The uncompressed canonical JSON SHA-256 is e1dafffc43f22e2ed774b414be860d36ab2e17fcb9a16d1b332f80c3e45e471f (Git blob 88c6c3ffe9d7f30e051ec27533b605007c3540cb). **This structured reserialization does NOT independently authenticate the byte-exact original output files.**
- sealed_run_records_v1.py is a **future-run** local recorder: explicit safe run ID, fsync of staged file, atomic create-only hard-link, read-back SHA-256 receipt, collision/tamper/invalid-input denial, real new-Python-process readback. Not host signing, kernel crash recovery, distributed WAL or protection against a hostile local administrator. A new, separately versioned timed_cpu_sealed_entry_v1.py now invokes the actual v2 25s runner and publishes its result through this recorder, with per-source SHA256 seals and runtime version stamps. The new entry was exercised with mocked training and real filesystem/new-process receipt checks, **not yet with another 25s full live training**. The historical mutable v2 entry remains untouched and must not be used for future evidence.
- Fourteen independent auditor/recorder/sealed-entry/original-byte audit test methods cover missing/duplicate records, adversarial metric/budget/authority changes, same-path overwrite denial, symlink directory refusal, new-process readback and post-publication byte mutation.

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
- Total **80/80 locally targeted PASS**, zero skips. No claim of full CI, Rust, GPU, power-loss, physical energy or independent training replication.

To reproduce from an appropriate project checkout:

    python -m unittest -v experiments.hcsn_p2_memory.test_audit_cpu_matched_v2 experiments.hcsn_p2_memory.test_sealed_run_records_v1
    python -m experiments.hcsn_p2_memory.audit_cpu_matched_v2 experiments/hcsn_p2_memory/TIMED_CPU_MATCHED_FOLLOWUP_12_RAW_20261031.json.gz.b64

Remotely re-fetched exact Git blobs, matched to the locally executed sources:
auditor cd104118043fb10774ae4a834fbc730b76ee8cc5;
auditor tests 3af73712cc817a2fb725aa6dc88c54267968bc0e;
recorder e587cf58abefa809c0f792e21c9b7486cb2c7242;
recorder tests 28d8c16991cf2f307dc3f8036bf2416151376533;
new sealed runner 2a5f5d95c7562fd8752d611dea407de7cc953103;
sealed-runner contract tests a894cb8dd284c66dd5cd608212b21583c878754b;
original-byte smoke verifier 2b91d8cd0ff03bf0cf794f35b8ab7c6364f49adb and tests 4f1c6741ddbbdf2001edfd07e03b7aa96e3483f0.


## New executed two-arm sealed CPU smoke (not independent learning confirmation)

- Ran the new versioned CLI against the **actual 25-second process-CPU learner** (one Copy T16/T32 arm pair, seed 2), after the prior 12-run snapshot; the learned model was retrained from identical weights and the same event-stream SHA. Aggregate: **25.004470207 CPU s, 4,132 updates, OOD 100%**; real-timestamp FIRE: **25.013919455 CPU s, 2,434 updates, OOD 58.59375%**. Within-pair CPU relative gap **0.0378%**, Copy OOD signed difference **-41.40625 pp** (negative evidence independently repeated once, not a new population or blinded study).
- The first attempted timed process was interrupted by the execution wrapper's timeout after the aggregate arm had completed. It left an empty timed stdout file and **no successful sealed timed record**; it is explicitly excluded from the completed-run numerator. A separately labeled timed smoke02 was then actually executed and sealed. The interruption is NOT evidence of genuine host crash recovery.
- Two original result JSON bytes plus their two exact stdout receipt bytes have been archived losslessly as SEALED_2PAIR_SMOKE_RAW_20261031.tar.gz.b64. Compressed archive SHA-256: **344eca3b2b2242a99b3c2c42e01e2031f167a47078df04a1ab0989054a99966d**; Git blob **a0d609bc1f718d47469cbb8e1645664dbb990044**. Actual receipt SHA-256: aggregate **5e49459f835ab20ef39aba8af97117ec8fd186488113989c4b94285f4b43b1f8**, timed **8d97ec08c2c383800f4a5a78ce7c46d6dc086c4718d30e555ef97fca4e8466c2**. The stand-alone stdlib archive auditor recomputed these and refused tampered/missing files in 3/3 tests.
- Retrying the already sealed aggregate run ID was rejected **before training** and did not replace the prior file; readback in a fresh Python process agreed with the independently retained receipt. The recorder is not authenticated, nor proven under power loss.

## Hard admission remains unchanged

P0 **OPEN**: coupled financial HX equilibrium, global obstacle/continuum and interval proof, native precision/implicit-gradient safety.
P1 **OPEN**: independent equal-total-compute Call/Risk/Margin causal OOD advantage.
P2 **OPEN**: native host-crash journal, retirement of the old mutable writer, reproducibility and independent replication; complete provenance, robust overwrite/MQAR/long-memory, real host-crash journal and independent blinded confirmation.
P3 **OPEN**: four real pretrained encoders and cross-modal OOD.
P4 **OPEN**: native Rust/GPU 64–4096 Cell, CPU/RSS/p95/p99/Joules/restart.
P5 **BLOCKED**: matched-backbone net-value scaling only if P0–P4 close.

production_activation=false; all_scientific_blockers_closed=false. Keep Draft NO_GO.
