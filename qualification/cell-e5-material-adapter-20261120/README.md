# Frozen sixteen-source E5 materials and lossless input admission

## Result and scope

The case-sensitive source prefix was committed before adapter construction at `9dade6e90f6227dded45afa1c8462758a511a699`. The local checker now admits **16/16 retained materials**, reconstructs **17 changed runtime files** byte-for-byte, and rejects **22/22 in-memory evidence-tampering controls**. It reads the same **290 original parameterized testcase identities per variant**: original before failures total 35; original after results are 289 passed and 1 skip. These are readbacks of already retained native executions. This work started **zero new native children, zero model calls and zero gradient updates**.

This is an integrity check within frozen trusted original artifacts. It is not an unforgeable contribution proof, a decentralized verifier, a proof of useful training, or a new independent execution. Git object/SHA256 equality is meaningful only with the independently trusted source commits, original collectors and execution evidence. A future production owner needs its own authenticated trust root and native result verification; derived fields in this package are not authoritative inputs by themselves.

The original four-source trainer, source digests, budget and failed results are untouched. The additional ten complete evidence anchor is immutable commit `b6822f9afe283e1e1b4493173ee98cc2f740ef0a`; the original roster's `1818fde...` field was the then-published code ref. `provenance/REFERENCE_CLARIFICATION.json` preserves that distinction instead of rewriting the earlier freeze. No E1 future task content was read or reused.

## Frozen prefixes and budget boundary

The sort is Python's ordinary case-sensitive `sorted(source_id)`; there is no lowercasing or reranking by results.

- n=1: `github:Delgan/loguru:pull:1541`.
- n=4: loguru, natsort, rich, multimethod, in that exact case-sensitive order.
- n=16: the complete ordered roster in `SOURCE_PREFIX_FREEZE.json`.
- n=64: 48 more admitted project materials are missing. Repeating an existing repair is not a new source.

`ORIGINAL_SOURCE_GROWTH_PROTOCOL.json` is a byte-for-byte copy of the original protocol. It defines a planned unit on one real repair material and 32 units per source, while explicitly leaving coding token/MAC/verifier and other execution bindings unfrozen. Under a **proposed** one-material/one-optimizer-step mapping, the available points would be 32/32/32 updates for fixed-total 1/4/16 and 32/128/512 for fixed-per-source 1/4/16. That mapping is not yet an admitted E5 training protocol. `NEXT_TRAINING_PLAN.json` enumerates the proposed source schedule and every unresolved execution field; it launches nothing.

The new n=1 and n=4 prefixes differ from the old four-project training panel. Its existing weights cannot stand in for these new growth-curve points. At n=64, fixed-total 32 single-material units can expose at most 32 sources; this must not be labeled all 64 sources trained or silently fixed by changing the unit or batch definition.

## Complete byte sizes

These are exact artifact byte lengths, **not token estimates**. Runtime-before counts the complete retained runtime package scope. Changed-before/after count whole changed runtime files. Native-tests count whole original selected test files, preserving every original function/decorator/parameter source; all accompanying retained fixtures remain in the payload. The review patch is a full deterministic unified diff. Exact byte-range replacements, not the review diff, are the authoritative reconstruction transport.

| Project | Runtime before B | Changed before B | Changed after B | Full native test files B | Review patch B | Cases per variant |
|---|---:|---:|---:|---:|---:|---:|
| Delgan/loguru | 228166 | 21974 | 22368 | 10703 | 1653 | 18 |
| SethMMorton/natsort | 110133 | 4881 | 4882 | 1285 | 468 | 1 |
| Textualize/rich | 296907 | 10850 | 12335 | 7760 | 3937 | 24 |
| coady/multimethod | 17358 | 17358 | 17387 | 5835 | 372 | 1 |
| dbader/schedule | 30107 | 30107 | 30205 | 35321 | 866 | 1 |
| erikrose/parsimonious | 56478 | 20342 | 20586 | 26917 | 1745 | 1 |
| jaraco/path | 71288 | 63460 | 63477 | 45458 | 302 | 3 |
| jawah/charset_normalizer | 264127 | 48489 | 48060 | 4099 | 1624 | 10 |
| litl/backoff | 29428 | 4170 | 4038 | 44347 | 1996 | 2 |
| marshmallow-code/marshmallow | 181338 | 75463 | 75524 | 28477 | 498 | 2 |
| pyparsing/pyparsing | 459498 | 41798 | 43014 | 434904 | 2538 | 12 |
| python-attrs/attrs | 194359 | 107159 | 107212 | 18752 | 309 | 5 |
| python-humanize/humanize | 49452 | 21758 | 21684 | 35743 | 294 | 56 |
| python-jsonschema/jsonschema | 271487 | 10642 | 10659 | 8461 | 2178 | 124 |
| tkem/cachetools | 61844 | 23791 | 23821 | 7885 | 638 | 1 |
| tox-dev/platformdirs | 166416 | 20486 | 20658 | 95850 | 986 | 29 |

The largest retained before snapshot is jsonschema at 2,992,560 B. Its full after fixture scope is 2,761,386 B. Source snapshots are the original retained execution scope, not a claim to contain every file in every upstream repository. No source text, fixture or parameter group was shortened for this adapter. The charset_normalizer repair includes both `cd.py` and `cd.pyx`; the checker rejects omission of the Cython counterpart. The jaraco/path original archive carries a separately retained PR-head license notice because the merged tree generates it through coherent.licensed; its exact Git blob and revision remain explicit.

## Existing codec and missing interfaces

The original `closed_python_function_v1` codec is catalog-bound to four projects and has a 32,768-byte raw-answer limit. An unchanged pure parser was invoked with the frozen original four target bindings; each complete reference payload reconstructed the exact after file. This did not call the native guard, verifier or any model and does not qualify a newly substituted target catalog.

- **Delgan/loguru**: New class-method transport/binding for ExceptionFormatter.
- **SethMMorton/natsort**: New module-level binding inside the original try block; preserve stub-ICU scope.
- **Textualize/rich**: Existing bound complete-function codec; reference payload 3,409 B.
- **coady/multimethod**: New class-method binding for subtype; corrected original buggy commit retained.
- **dbader/schedule**: New class-method binding for Job.
- **erikrose/parsimonious**: New multi-region binding: two classes and a module assignment.
- **jaraco/path**: New class-method binding for TempDir; exact separate PR-head license notice retained.
- **jawah/charset_normalizer**: New two-file binding: complete Python and Cython corrections must remain linked.
- **litl/backoff**: New two-function binding in _sync.py; preserve both native sync/async tests.
- **marshmallow-code/marshmallow**: New class-method binding for Pluck.
- **pyparsing/pyparsing**: Single top-level function transport shape is reusable; new project/native binding still required. Full after function 2,517 B; closed payload 2,531 B.
- **python-attrs/attrs**: Existing bound complete-function codec; reference payload 546 B.
- **python-humanize/humanize**: Existing bound complete-function codec; reference payload 315 B.
- **python-jsonschema/jsonschema**: New changed-function plus new helper binding; 124 generated original cases and JSON suite fixtures retained.
- **tkem/cachetools**: New class-method binding for TTLCache.
- **tox-dev/platformdirs**: Existing complete-function plus specific optional-constant codec; reference payload 1,367 B.

Every new project still needs an explicit candidate/native binding, a complete deterministic renderer, and exact tokenizer admission. A small patch does not make its surrounding code/context fit the original sequence budget. The 434,904-byte pyparsing test file and 459,498-byte runtime package must not be inserted wholesale into an old 3584/4096-token sequence. Full material bytes remain retained even when a future renderer exposes complete bounded functions and dependencies. Oversized complete examples must block execution; truncation, parameter reduction and source reselection are not recovery mechanisms.

## What the checker verifies

`lossless_admission.py` verifies the prospective identity/prefix, original Git blob and SHA256 bindings, complete retained snapshot inventories, original runtime scope and native selector, every runtime change including file existence, exact patch reconstruction, complete test/decorator spans, all required license notices, original replay stages, original stdout/stderr/JUnit, fixture/runtime execution manifests and complete ordered case identities. It verifies reported byte sizes independently. It refuses fabricated trajectories/features and any claim that this material gate admits training execution.

The owner receipt independently binds the checker/build/control/codec/unpack sources, material index, source prefix, source evidence anchors, archive-part manifest and complete input-tree manifest. It reassembles the archive into a new directory and verifies all 1,645 members against that frozen input tree, then checks source hashes again after all stages. The checker tests include coherently renamed JUnit/EXIT parameter evidence as well as missing files, changed patches/fixtures/limits, omitted notices and invented learning fields.

## Reproduce without a model or native test execution

From this directory, choose a new output directory and run:

```sh
python -B unpack_materials.py --manifest PAYLOAD_MANIFEST.json --output /tmp/e5-material-readback-new
python -B lossless_admission.py --root /tmp/e5-material-readback-new --prefix SOURCE_PREFIX_FREEZE.json --output /tmp/e5-admission-new.json
python -B test_lossless_admission.py --root /tmp/e5-material-readback-new --prefix SOURCE_PREFIX_FREEZE.json --output /tmp/e5-controls-new.json
python -B check_existing_codec.py --root /tmp/e5-material-readback-new --provenance provenance --output /tmp/e5-codec-new.json
```

The payload has 1,628 content-addressed byte objects plus 16 material records and one material index: 14,013,639 uncompressed bytes. Its deterministic gzip archive is 2,995,743 B, SHA256 `73504304a1c6e220f085d91845f3b585b73bfb649dd829b38a06e62ee7e8c2f9`, split into 8 parts of at most 393,216 B. `BOUND_INPUT_ROOT.json` has SHA256 `5f9fb9747b20b4f2645a1eff0add7d30108df02d4b5cba5510594cd24c25374b`. The original owner output, source, complete stage stdout/stderr, positive/control/codec reports and freeze are retained under `execution/` and at the directory root.

The measured local readback owner wall time was 2.771106201 seconds. It is administrative integrity-check cost, not model training, and must not be added to nested native costs. Full physical/energy/network/money accounting remains unknown. No source-growth performance, authenticated user growth, online learning or foundation-model result follows from material admission.
