# P2 train-from-scratch physical FIRE pilot — 2026-10-31

**RESEARCH_ONLY / DENY_ALL / NO_GO**, incremental stacked draft on #4503 exact `0c12e663f3e71d2ddca45f6de6cc2d15d66be39b`; no production, finance P0, old negative evidence, original model source, Rust owner or CI files modified. Before any result, preregistration was committed `499b6cd9a82a0033827dc65cf471eec984fd019a` and then its maximum update count was corrected to 2,000 at `b324665f38260aef34b8aaeb726e8ad1d29de1f1` **before primary runs**.

## New executable training path

`timed_training_budget_pilot.py` constructs actual Brownian first-hit events for each sequence and vectorizes their *ordered physical-time gaps*, with mask-only padding that cannot invent FIRE events. It differentiates through each event/decay/content operation, but **not** through sampling of Brownian FIRE clocks. A shared 5,186-parameter GRU+event-head architecture is newly trained separately using either (a) the old at-observation aggregate count or (b) the actual per-FIRE-time content updates, rather than reusing the old weights as in #4503.

The data, model initial parameters, optimizer, shuffled minibatch index prefix, train task, train/test actor seeds and every exogenous Brownian event stamp are identical within each paired comparison. Unchanged task generator has irregular continuous intervals, Selective Copy and four-key last-write MQAR4. Tests validate bitwise equality with original aggregate data and per-timestamp physical session, plus gradients and invalid-domain refusals.

**Local test evidence:** 62/62 targeted tests passed, no skips, Python 3.13.5 + PyTorch 2.10.0+cpu, using the reconstructed HX reference subset already disclosed in #4499–#4503; **not a full upstream repository checkout or whole-repo CI**. Focused new file has 6/6 tests. Source/test fetched remotely and Git blob digests matched local executed bytes: `0da88a5c294d129e85b572f25c8747eb84d4d8ad` / `4775abfaacb5982588a5e7037524f89cade20f3a`.

## Eight complete independent training runs (retain all negative outcomes)

All arms: 2 tasks × 2 paired seeds × 2 operators; 128 training streams, 128 ID test streams (T16), 128 OOD test streams (T32), 2,000 optimizer steps, Adam lr=.006, 24 actors per update. No tuning on OOD. Each ID/OOD test has 128 Copy queries or 512 MQAR4 queries.

| Task | Seed | Aggregated ID / OOD | Physical-time ID / OOD | CPU train (agg / timed) |
| --- | ---: | ---: | ---: | ---: |
| Copy | 0 | 99.22% / 72.66% | 87.50% / 42.19% | 12.28 / 19.70 s |
| Copy | 1 | 96.88% / 30.47% | 70.31% / 47.66% | 12.30 / 20.43 s |
| MQAR4 | 0 | 61.13% / 58.40% | 54.10% / 57.23% | 11.55 / 19.67 s |
| MQAR4 | 1 | 56.25% / 53.71% | 57.23% / 55.47% | 12.89 / 20.98 s |

Copy ID mean 98.05% agg versus 78.91% physical. MQAR4 ID mean 58.69% versus 55.66%. MQAR4 OOD mean 56.05% versus 56.35%: small, inconsistent and not statistically validated. The physical-time CPU training cost for the same updates was approximately **1.60–1.70×** in these four paired runs.

### Crucial preregistered CPU fairness failure

The plan said consume up to 25 process-CPU seconds per arm, with a 2,000-step cap. **All 8 arms reached the 2,000-step cap before consuming the 25-second budget**: aggregate approximately 11.55–12.89 seconds, physical 19.67–20.98 seconds. Therefore, despite **equal steps and equal trainable parameters**, this batch **does not meet the equal measured CPU training budget condition**. Explicitly reject a CPU-matched superiority or inferiority claim; do not silently equate 2,000 steps with equal resources or relax the tolerance. The next experiment requires a new frozen protocol with untouched seeds and sufficiently high step cap, and independently tested ordinary/SSM/Transformer controls.

Complete, machine-readable, eight-record results including original raw-file SHA-256 seals, model/data digests, train/eval CPU and wall, BCE, step-indexed learning traces and all failed outcomes are in `TIMED_TRAINING_PILOT_8_RECORDS_20261031.json`. This is a **semantically lossless re-encoding** of the original local JSON records, not byte-for-byte the originals; their original digests are kept in every record. CPU timing need not reproduce identically across hosts; labels/model outputs should if the same environment is restored.

## Reproduce

```bash
python -m unittest -v experiments.hcsn_p2_memory.test_timed_training_budget_pilot
python -m experiments.hcsn_p2_memory.timed_training_budget_pilot --task copy --seed 0 --arm aggregate_count --output /tmp/copy_s0_count.json
python -m experiments.hcsn_p2_memory.timed_training_budget_pilot --task copy --seed 0 --arm physical_event_timestamp --output /tmp/copy_s0_physical.json
# Repeat task=copy,mqar4 × seed=0,1 × both arms; inspect all eight records.
```

## Strict gate status

- **P0 OPEN**: coupled global HX financial obstacle / continuum and low-precision active-set gradient proof.
- **P1 OPEN**: unbiased significant Call/Risk/Margin mechanism attribution under matched measured budget.
- **P2 OPEN**: actual equal-CPU comparison, long-memory overwrite/retrieval/OOD, genuine durable crash-journal and full model security. This pilot primarily demonstrates how an optimizer-update cap can invalidate a supposed measured-cost match.
- **P3 OPEN**: independent real four-modal encoder and alignment evidence.
- **P4 OPEN**: native Rust/GPU, 64–4096 Cell p95/p99/RSS/Joules, fault recovery.
- **P5 BLOCKED**: no scaling admission until independently repeatable quality+cost evidence.

`production_activation=false`; `all_scientific_blockers_closed=false`; keep **draft/unmerged**.
