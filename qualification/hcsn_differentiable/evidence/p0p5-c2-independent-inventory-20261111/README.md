# HCSN C2: independent read-only structural inventory (2026-11-11)

**DRAFT / HOLD_NO_GO.** This is a new verifier implementation on top of #5936, not an extension, completion or restart of the original desktop C2 job `1a1c74f3308-be2a-75`.

## Exact input and experiment scope

The preserved frozen source is [#5920 FIT-INVENTORY-READONLY.json](../p0p5-c2-terminal-reconcile-20261111/FIT-INVENTORY-READONLY.json), Git blob `5a258598ba60754776902e3f7b58146766c02a74`. Its eight SHA-256/length entries cover four `result.json`, two **zero-length** `interrupted.pt`, and two nonempty `best.pt`. New auditor source is `recovery_v1/c2_independent_inventory.py`; its own regression tests are in `test_c2_independent_inventory.py`. No original training source, weights, logs or checkpoint was edited or re-executed.

The independent read-only desktop invocation re-read **all six expected candidates**, checked observed files against the frozen inventory and semantic structure, counted complete JSONL rows, and retained the corrupted tail as a failure. It does not deserialize model weights, validate `wait4` evidence, prove native program completion, estimate generalization or infer mathematical/scientific benefit.

## New independent output

[READONLY-AUDIT.json](READONLY-AUDIT.json), SHA-256 `4d66f22152cbdf249eac1440b880a5cd2a1e91459004018ac4bef7d8aa5a4481`:

- Six original attempt identities remain the denominator; four are **pinned producer-completed claims**, not independently replayed training terminal evidence.
- `hcsn-s211-lr0.001` and `hcsn-s307-lr0.001` still lack `result.json`; their `interrupted.pt` are `ZERO_INVALID`. Their independent `best.pt` byte identities do not replace a complete interruption checkpoint.
- The original `commands.jsonl` is **28,672 B**, SHA-256 `1405bced8c59a294276616cd7054f2b4068e10d858ab61d78bb578b93992239f`; it contains 16 complete records and a torn 17th. Original controller `RESULT.json` remains absent.
- `all_six_independently_replayed=false`, `full_resource_bill_verified=false`, `scientific_admission=HOLD_NO_GO`.

The four pinned `result.json` producer reports declare `completed_development` and `training_adequacy_established=true` and report development macro-F1 respectively `0.344017, 0.387834, 0.391093, 0.349831` in roster order (s101/.001, s101/.003, s211/.003, s307/.003). These are **declared development measurements**, not independent performance or fully matched seven-architecture comparisons. Energy consumption is reported as null.

## Test provenance and limitations

Native `desktop` isolated project directory: `/home/qian-qi/work/hcsn-c2-independent-inventory-20261111-0729-gpt6/`.

- First suite run `1a1c9868edb-2564-18d`: **1/6 pass; 5 errors**, because the new verifier incorrectly used `stream.fstat()`.
- Corrected `os.fstat(stream.fileno())`; run `1a1c986f526-2564-18e`: **6/6 pass**.
- Extended frozen-root binding and a new test; run `1a1c988c6c1-2564-19f`: **7/7 pass**, `py_compile` and original six-candidate read-only audit asserted **4/6, 16 complete journal rows/torn tail, missing controller, HOLD**. Separate earlier original-producer JSON drilldown: `1a1c982f2e8-2564-172`.
- Exact native-tested source SHA-256: verifier `0f34d8ae0bf9ac5dcafa87a9c5d5a9b00635f4f677b91c807dee8a5d83aea036` (9,257 bytes), tests `ef20267cb5e2d49fc070a3bc991715b2da71bfb47dd7608e1979cb15dbcc2eb7` (5,132 bytes). Readback and GitHub blob identities require verification after publication.
- Existing CI step discovers `test_*.py` in `recovery_v1`; this should add the seven regressions to new-source CI. Native local success does not substitute for hosted CI or a product controller's complete terminal.

**Unclosed:** P0 common-identity full-source reproducibility; P1 actual train-visited posterior/tail/AD numerics; P2 successor runner/controller integration, six new independent replay terminals and all costs under matched controls; P3 independent QVI policy benefit; P4 real asynchronous multimodal plus anti-diffusion controls; P5 only after robust independent benefit.

Do not mark GO/Adopt, merge into production, edit original evidence, or restart unknown-effect original attempts on the basis of this artifact.
