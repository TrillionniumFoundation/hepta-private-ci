# Bounded forensic iterables - P0 resource-contract correction (2026-11-12)

**Status:** SHADOW_ONLY / DENY_ALL / HOLD_NO_GO. This is a read-only reference input-budget fix, not a model improvement, native Owner attestation, scientific effect, or release qualification.

## Source and reproducibility

- Parent: PR #6086, exact commit a539605950228181dd5b903cc11f7ec88e020d9d, tree 80b5968a790818ce7ba9cd8b828423ca0ce21a81.
- Base study.py Git blob: 3eaf7308fa9f7789675e2c40db96872dceedb6f2. The original RED host study.py was byte-exact: git hash-object matched this blob.
- Modified study.py SHA-256 cbc54b3c276875a5aa0ac238d224cd6771d98b8c3f1150e3f446fd938bb36ded; new test SHA-256 a8af7f0aa7a641a2c2fa933b3a5d48bb1e40c5750cc03826db8d41e21a732cc3.
- Sixteen unchanged test files were fetched from this precise parent. See BOUNDED_ITERABLE_FILE_SHA256.txt for host SHA-256 of the entire executed test selection.
- Actual operator alias ai395; Python 3.14.4, Linux x86_64. Environment readback: BOUNDED_ITERABLE_ENVIRONMENT.log. No GPU device observed, and Colab/Kaggle were not tested.

## New defect and change

The existing time_aligned_credit materializes the complete actions and feedback iterables with list() before checking the 65,536-element size bound. The same flaw exists for select_replay records and paired_evidence trial rows. One-shot or infinite iterators can force unbounded enumeration and allocation before the post-hoc gate.

The repair uses itertools.islice to consume at most limit+1 elements and rejects over-budget inputs before ordinary identity validation. Caps: 65,536 raw action events; 65,536 raw feedback events; 65,536 raw memory records; 400,000 paired trial rows (the existing 100,000 four-arm blocks multiplied by four).

The test generator emits the cap+1 elements and throws an AssertionError on any over-read. It is an adversarial reference test, **not** real owner event data.

## Original observed RED and corrected GREEN

| Gate | Raw observed result |
| --- | --- |
| Byte-exact parent source plus four new tests (RED) | All 4 fail as expected from iterator over-read. Test time 0.028 seconds, exit 1 |
| Corrected focused suite (GREEN) | 4/4 passed, wall 0.11 seconds, user CPU 0.09 seconds, peak RSS 25,584 KiB |
| Corrected complete shadow suite (GREEN) | 95/95 passed, wall 0.26 seconds, user CPU 0.23 seconds, peak RSS 25,860 KiB, exit 0 |
| This new HEAD native Owner/Q24 training | NOT_RUN |
| Independent future B, different task C, actual model benefit | NOT_RUN |

Verbatim source-aware artifacts: BOUNDED_ITERABLE_RED.log, BOUNDED_ITERABLE_GREEN.log, BOUNDED_ITERABLE_FULL_GREEN.log; resource and environment observations in BOUNDED_ITERABLE_ENVIRONMENT.log. The native 101/101 Rust CI success on parent PR #6086 belongs to that separate source and is not a new native result for this commit.

## Explicit limitations and remaining blockers

This only bounds **number of iterable items**, not bytes, per-item execution cost, upstream I/O, or external effects. Caller-supplied action/feedback times and hashes remain untrusted. This is **not** a Root signature, Agentd Owner result, independent evaluator, training proof, version adoption, signed deletion, retention result, seven-lineage cost-matched comparison, or Core x NDU 2x2 attribution. Complete GitHub CI for the successor HEAD remains pending until separately read at terminal state. No merge, auto-adopt or deployment is authorized.
