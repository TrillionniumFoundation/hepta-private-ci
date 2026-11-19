# HCSN P2 actual CPU-matched FIRE-content follow-up (2026-10-31)

**RESEARCH_ONLY / DENY_ALL / NO_GO.** Research branch stacked on draft #4504 HEAD d07405a4d4582ca763a517d7828170c49121e498. No production activation or claim of scientific gate closure.

## Why this experiment is separate

PR #4504's original eight runs all hit the 2,000-update limit before the allotted 25 process-CPU seconds. This distinct, non-blind exploratory follow-up uses seeds 2/3/4 and a safety cap of 8,000 steps, and requires actual 25-second consumption before accepting a run. This was not a prospective publicly timestamped preregistration or independent heldout confirmation.

Same 5,186 trainable parameters, initial weights, Brownian event trains, physical timestamps, train/evaluation examples, Adam settings and minibatch RNG within each pair. Task-specific dataset generation plus optimization, but not model construction or heldout inference, is charged to the 25 process-CPU-second training budget. Heldout inference CPU is separately recorded. Every candidate reaches the CPU budget before the cap.

## Delivered source and evidence

- timed_cpu_matched_v2.py: fixed two-arm, two-task, three-seed execution and exact paired-budget validator.
- test_timed_cpu_matched_v2.py: CPU overshoot, missing initialization/input hashes, unregistered seeds, forbidden authority checks.
- audit_cpu_matched_v2.py: independent stdlib verifier, decodes lossless raw bundle, checks all twelve rows and recomputes paired differences without importing the learner.
- test_audit_cpu_matched_v2.py: tampered metric, missing/duplicate run, changed input hashes and false scientific admission refusals.
- TIMED_CPU_MATCHED_FOLLOWUP_12_RAW_20261031.json.gz.b64: deterministic gzip+base64 lossless canonical JSON for all twelve records and six comparisons. Uncompressed 20,219 bytes, SHA256 e1dafffc43f22e2ed774b414be860d36ab2e17fcb9a16d1b332f80c3e45e471f.

The first nine run records were present before this continuation; the three missing MQAR4 records (seed3 physical-time; seed4 both arms) were newly executed. Existing records were audited and not misrepresented as re-executed. Maximum observed within-pair training CPU gap 0.0284%; each of 12 actual training CPU measurements lies between 25.0000 and 25.0094 s.

## All paired outcomes, with negative evidence

Accuracy mean over three paired seeds. Difference = physical-time FIRE minus aggregate-count model, in percentage points.

| Task | Split | Aggregate | Physical FIRE | Difference |
| --- | --- | ---: | ---: | ---: |
| Copy | ID T16 | 99.219% | 93.229% | -5.990 pp |
| Copy | OOD T32 | 94.531% | 67.969% | **-26.562 pp** |
| MQAR4 | ID T16 | 56.706% | 56.185% | -0.521 pp |
| MQAR4 | OOD T32 | 55.339% | 55.924% | +0.586 pp |

Average updates under the same CPU allowance: aggregate ~4,343; physical-event timestamp ~2,451. Copy OOD negative differences for seeds 2/3/4 are -41.406/-10.938/-27.344 pp. MQAR4 OOD differences are -2.734/+3.320/+1.172 pp: no stable sign, no significant positive mechanism inference.

Single-pass summed heldout inference CPU for six runs per arm was aggregate 0.0421 s versus physical-time 0.0732 s. Not robust timing, not p95/p99, hardware Joules or end-to-end service cost. Trained tensor weights were not archived, only model-weight SHA256; environment and CPU time cutoff affect exact rerun steps.

## Local validation and reproduction

On local Python 3.13.5 / PyTorch / NumPy / SciPy CPU: **26/26 P2 targeted test methods PASS**, zero skips, covering existing event content, physical timestamp replay, previous budget pilot, and both new test modules. Upstream P2 source blobs exactly matched GitHub; the local HX subset is reconstructed, not a full upstream checkout. **No full repository CI, native Rust/GPU, host crash journal, energy or 4,096 Cell measurement.**

~~~sh
python -m unittest -v experiments.hcsn_p2_memory.test_timed_cpu_matched_v2 experiments.hcsn_p2_memory.test_audit_cpu_matched_v2
python -m experiments.hcsn_p2_memory.audit_cpu_matched_v2 experiments/hcsn_p2_memory/TIMED_CPU_MATCHED_FOLLOWUP_12_RAW_20261031.json.gz.b64
python -m experiments.hcsn_p2_memory.timed_cpu_matched_v2 --task copy --seed 2 --arm aggregate_count --output /tmp/copy_seed2_aggregate.json
~~~

Remote blob SHA-1 readback identities, all equal to locally executed sources: runner a62d8e5056cd9c66947815b4eb8b5af9cf3a84de; tests fdc270e55e894d9018314218c18679d75246afc4; independent auditor cd104118043fb10774ae4a834fbc730b76ee8cc5; auditor tests 3af73712cc817a2fb725aa6dc88c54267968bc0e; lossless raw archive 88c6c3ffe9d7f30e051ec27533b605007c3540cb.

## P0-P5 strict acceptance

| Gate | Status | Still missing |
| --- | --- | --- |
| P0 | OPEN | Whole-admissible-domain coupled HX obstacle, continuum and interval rounding, real low-precision active-set gradients |
| P1 | OPEN | Independent matched Call/Risk/Margin causal positive utility with total compute and OOD correction |
| P2 | OPEN; one cost-accounting gap addressed | Durable host recovery, learned clock, robust overwrite/MQAR/long retrieval, tuned equal-cost baseline superiority, independent confirmation |
| P3 | OPEN | Real paired text/image/audio/video and OOD/temporal robustness |
| P4 | OPEN | Native Rust/GPU 64/256/1024/4096 Cell, CPU/GPU/RSS/p95/p99/Joules/restart |
| P5 | BLOCKED | Prespecified equal data/tokens/total compute benefit against tuned Transformer/SSM/gates |

production_activation=false; all_scientific_blockers_closed=false. Keep as draft; historical negative evidence is not removed or reclassified.
