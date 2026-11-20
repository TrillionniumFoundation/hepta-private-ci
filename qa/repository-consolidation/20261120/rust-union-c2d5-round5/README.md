# Rust consolidation: Round 5 source repair evidence

This package records two narrow source repairs and the actual CI observations that motivated them. Its source endpoint is `9eb0137a2b79b80d3c644530757746cc615d00bd`, tree `a6b76427e8e9e470527c102d0a5110dc8df31214`. A later single-parent QA commit adds this package without changing any existing source or QA leaf.

## Exact source chain

| Step | Commit | Parent | Change |
| --- | --- | --- | --- |
| Published baseline | `d0b48bd33cfe920ba944eb321e4767c8e64d83dc` | Earlier Round 4 chain | Baseline tree `f40de2219149ca0c306eea6ba5c575099be0da0f` |
| Formatter patch | `1eb796f6f04058e82ec7449a42dd63d7dbb12fe5` | `d0b48bd33cfe920ba944eb321e4767c8e64d83dc` | Bellman example, tree `33117c45c7ee191946b142a6b7a02da779a38679` |
| Clippy suggestion | `9eb0137a2b79b80d3c644530757746cc615d00bd` | `1eb796f6f04058e82ec7449a42dd63d7dbb12fe5` | Shadow test helper, tree `a6b76427e8e9e470527c102d0a5110dc8df31214` |

The Bellman example change is the exact two-hunk patch from formatter job `136144717102`, artifact `14609572152`. It wraps two calls and adds one legal trailing comma. It does not have strict token identity: that comma is explicitly recorded. Every literal, comment, timing budget, assertion operand, error path and qualification check remains unchanged.

The shadow helper changes only line 358 of `codex-rs/hepta-shadow-qualification/tests/support/tabular_reload.rs`: the capture-free closure `|bytes| bytes.to_vec()` becomes the compiler-suggested `<[u8]>::to_vec`. All eight assertions remain at their original lines and keep their exact text. The existing `FnOnce(&[u8]) -> T` callback and validation path are read-only evidence; no production validation, authority, currentness, persistence or locking code changes.

Both changes have independent source reviews, complete byte-exact inverses, actual forward/reverse Git patch checks, local raw commits and actual official server object receipts. All 59,290 existing leaves are accounted for at every source step. Only the two named source leaves change; all 5,325 older QA leaves remain unchanged. The new source commits have no Rust, formatter, Clippy, native or CI pass claim in this package.

## Actual observations on the published parent

These results belong to `d0b48bd33cfe920ba944eb321e4767c8e64d83dc` and its explicitly identified merge checkouts. They are never transferred to the two new source commits.

| Scope | Observed result | Limits |
| --- | --- | --- |
| Source formatter, job `136144717102` | Failed; exact two-hunk patch retained | The patch supplies the first repair; no after-run is claimed |
| Codespell, job `136144718783` | Passed; 15 original custody tests and 110 archive-path identities verified | Exact PR synthetic checkout and logs retained |
| Neuron execution, job `136144716934` | 1,106 tests, 5 skips, passed | Six former Pillow error cases passed; four skips require an unavailable native binary |
| Research, job `136144716760` | 1,106 tests, 1 skip, passed | This suite overlaps Neuron; the counts are not added |
| Bellman exact source, job `136145846653` | Selected tests passed; strict Clippy then failed | The sole diagnostic is the shadow helper closure; later gates did not execute |
| Bellman deterministic merge, job `136145846647` | Selected tests passed; strict Clippy then failed | Internal merge `0d631c70f9a7b302a1318d9153c812c83a8b6c0c` has the baseline tree |
| Bellman required, job `136158580801` | Failed | Both lane results are failure |
| SDK, job `136145846089` | Jest 5 suites / 47 tests passed; regression gates passed | Original official conformance success remains false, with acknowledged baseline failures |
| Windows owners, job `136144717062` | 98 unique exact native cases in 8 groups passed, no retry or missing case | 43 Python collector tests are separate; final product qualification and production authority remain false |

Bellman default and compatibility modes overlap, as do the exact-source and merge lanes. Their counts are kept separately. On the exact-source lane, the two selected terminal owner tests each pass one case with four name-filtered cases; the second is `clean_agent_recall_replay_training_load_and_source_withdrawal`. `durable_learning_roundtrip` is the Clippy test target, not the identity of that passing selected test. Compatibility Clippy, later formatting, mutation, coverage and scale qualifications are not inferred from earlier successful commands.

The SDK reports keep both values: the regression gate is true and the original official success is false. The 28 acknowledged failures remain byte-identical to the prior baseline, including five official default checks. The old timeout's production cause is not declared fixed, and no diagnostics or timeout policy changes are included.

The Windows owners artifact retains source-before/source-after records, tracked-change and lock identities, all 14 original ZIP entries, exact case names and the original selectors. Its process lane is outside this package's qualification scope.

## Evidence storage and portable verification

There are six groups, 25 independently gzipped fragments and 238 original members containing 19,021,768 bytes. `evidence-index.json` pins each stored fragment, inner archive and member manifest by size, SHA256 and Git blob identity. Each group manifest names every original local input and exact archive member.

Run from this directory with Python 3:

```sh
python3 -B verify_evidence.py
python3 -B verify_source_chain.py
```

The first verifier checks every archived member in memory. The second invokes that verification and reconstructs the complete baseline Git tree from the one included 59,290-leaf inventory, applies the two exact source deltas, checks each complete Merkle root and actual official parent/tree receipt, and binds the final head and tree to the index. Neither extracts files to disk nor executes archive contents or product tests.

Source construction uses explicit reuse: the first source seal has 21 direct members, six exact members in the formatter group and one omitted derived inventory; the second has 28 direct members, ten exact members in existing groups and two omitted derived inventories. Each original seal is included separately. Complete derived inventories are reproducible from the single baseline plus the exact deltas. Their original compressed identities and exact raw reconstruction results are recorded; compressed byte reproduction also depends on the compressor version. No claim is made that every original sealed file is duplicated in an archive.

The follow-up CI group similarly reuses six exact members already archived. Windows source-before and source-after have identical 230-byte contents and an explicit alias; both original ZIP entries remain present. Signed download receipts and private coordination prompts are excluded by identity. Original safe logs, including existing masking and unsuccessful commands, remain unchanged.

## Construction failures and remaining gates

The records retain the first source commit response-shape mismatch: the server returned its SHA, so the existing commit was reconciled with an official GET instead of recreated. They also retain the initial nested-alternate depth failure, the separate strict `write-tree` failure on an unchanged historical blob, the root review's corrected field-name assumption and the portable checker's static endpoint-binding correction. Direct read-only object suppliers and metadata proofs do not imply a complete historical checkout or native build.

The C2D learning-persistence production repair remains stopped after its earlier automatic safety-review rejection. It was not applied, compiled, tested after the change, or retried. The unknown native source-copy job is excluded and is not queried or replayed. The original observed rollback remains unresolved.

This package does not advance main or integration, retire a branch, attach historical branch ancestry or modify HIA branches. Fresh complete official refs and cumulative protection for all HIA names, historical pins and descendants are required before the separate fix-ref update. Native and required CI gates for full consolidation remain outstanding.
