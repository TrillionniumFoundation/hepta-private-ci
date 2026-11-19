# Independent source and saved-result review

## Decision

PASS for publication as a bounded, single-run saved128 engineering diagnostic with mixed timing. This is not approval for production integration, deployment, training, 256-step execution, or a strict aggregate budget claim. Publication must retain the limits below and the distinction between independently checked child evidence and the invoking agent's outer-tool transcript.

Reviewed candidate: `strict-history-equality-candidate-v1`.

- Freeze SHA256: `5a1a726f3db9e892b72aea9941413a8544a37244d276b5f827c3891825ceb8ab`.
- RESULT SHA256: `a36315f00ee8b453afd2711c5d29adaff725074f46e09b015c62ffda710a1806`.
- WAIT4_RECEIPT SHA256: `4c5de6aa40b7aff99fda27c05a49dbc7d78a9007a9f293d3cd8067413a3e81d1`.

This review did not import or execute the candidate, original history implementation, model, optimizer, or tests. It read source and saved artifacts and used an independent standard-library verifier for hashes, JSON-chain reconstruction, ledger checks, and arithmetic. No candidate or historical file was changed. Only this external review directory was written.

## Source review and pre-run corrections

The frozen AST transformation extracts the original `history`, `bytes_get`, and four stage helpers without importing their original modules. It replaces exactly two canonical-JSON inequality sites. Boundary hashing, history references, full-chain traversal, payload lengths and hashes, and fresh file opens remain in the original code. No across-call cache or filesystem-metadata shortcut was introduced.

Strict builtin-type matching preserves bool/int/float distinctions, finite floating-point equality, and the sign of floating zero. Two semantic boundary issues were identified and corrected before execution:

1. Default ASCII JSON serialization can equate an astral Unicode scalar and its explicit surrogate pair, including dictionary keys. Unequal strings and differing dictionary-key sets now fall back to the original serialization comparison.
2. Recursive Python comparison can exhaust its stack earlier than the JSON implementation. An outer wrapper now catches RecursionError after unwinding and falls back to the original canonical comparison.

The tip-hash negative originally hit the terminal boundary check before reading a history leaf. Its terminal checkpoint was removed before the run, so the saved case exercises actual history-reference comparison. These were pre-run source revisions, not post-result tuning or repeated experimental runs.

## Independent saved-byte and correctness checks

- All five candidate files match the admitted freeze, whose hash matches the wait4 receipt.
- All 392 pinned input files match their saved SHA256 values: 2,406,239 bytes in total.
- An independent forward reconstruction verified all 128 saved history leaves, their before/after linkage and references, and all 256 opaque payload lengths and SHA256 values. Payload arrays were not decoded.
- A complete walk logically reads 1,680,512 payload bytes. The tail of 64 leaves reads 840,256 bytes.
- The retained qualification record reports 676 literal pairs, 128 saved equal pairs, 256 counter/type mutations, six nonfinite refusals, and one depth450 equal pair. The frozen assertion paths and successful completion support this record; the reviewer did not rerun these tests independently.
- All 22 retained history calls were checked individually for their expected mode, success or rejection message, and exact work counters. Original and candidate negative messages agree on the six specified cases.
- All four timing blocks retain their prespecified AB, BA, AB, BA order.
- The publication snapshot's six frozen source/provenance files are byte-identical to the candidate. Its SUMMARY contains JSON objects equal to the original result, freeze, and child receipt.

Absolute work totals match the pre-run source prediction, not merely pairwise parity:

- 18 history walks.
- 1,668 validated leaves.
- 3,328 payload reads.
- 21,846,656 logical payload bytes.

The four invalid job/cursor calls reject before incrementing the walk counter. These counters are source-defined logical operations. They exclude history-file bytes and hash-barrier reads and do not measure physical disk traffic or prove that filesystem caches were cold.

The six negative cases alter in-memory state or boundary arguments. No historical file or payload was deliberately corrupted in this diagnostic. Preservation of file-change detection rests on unchanged source checks and fresh-read positive evidence, not a newly executed disk-corruption test.

## Timing evidence

The original's four recorded calls total 64.000860 ms and the candidate's total 59.854436 ms. The ratio is 0.935212995575372, a recorded difference of 4.146424 ms or 6.4787%. Therefore the frozen arithmetic criterion, candidate/original <= 0.95, is satisfied.

Per-block candidate/original ratios and candidate-minus-original differences are:

1. 1.321028932348208; +3.852900 ms, slower.
2. 0.7974256492759025; -4.064328 ms, faster.
3. 1.0039508927927125; +0.062963 ms, slower.
4. 0.750117426638118; -3.997959 ms, faster.

Two blocks are slower and two are faster. Eight short rejection calls report 0 ns, while several longer calls cluster near 12, 16, and 20 ms. The run does not record an independently established effective timing resolution. These observations raise timing-granularity or noise concerns; they do not establish an exact clock quantum. Zero readings are not evidence of zero cost, and displaying nanoseconds does not establish nanosecond measurement accuracy.

This is a small, mixed, single-run local timing result. It does not establish stable or statistically significant acceleration, cold-disk performance, whole-controller improvement, natural-data benefit, or a 256-step budget guarantee. Qualification calls occurred before timing. No extra repetition, setting, or retry was selected after seeing the result.

## Process and cost evidence

The independently read WAIT4_RECEIPT binds the reviewed result and freeze. It records complete child wait4, raw wait status 0, exit code 0, and no automatic retry. User CPU 0.220105 s plus system CPU 0.065142 s equals whole-child CPU 0.285247 s. Recorded wall duration is 0.28664290299639106 s and peak RSS is 14,400 KiB. Child stdout and stderr are empty.

The additional outer CPU prefix is 0.041751895 s. The known invocation CPU lower bound is therefore 0.326998895 s, plus an unknown nonzero outer tail. Preparation, review, and historical work remain additional. The 0.195132031 s sum of retained operation samples and the worker prefix are already contained in whole-child cost and must not be added again.

The child receipt alone does not establish outer-wrapper termination. The saved `OUTER_TOOL_TRANSCRIPT.json`, supplied by the invoking agent and independently read during this review, records the original exec_command response, chunk `b50f5d`, with exit_code 0, no session_id, and completed execution. Its stdout JSON equals the child receipt. Its SHA256 is `9a2fdf868f7f3083a7b1c064a4774f4804354c5c3321be300ca33c6a0a58d944`. That outer evidence is a relayed tool-transcript statement, not a second independently measured wait4 receipt. Any persisted excerpt must be labeled as copied after the run and must not be presented as a pre-frozen or independently generated terminal receipt.

The worker owns the shared benchmark lock; the operating system releases it when the worker exits, before the outer wrapper necessarily finishes. Both terminal states must therefore be established externally before declaring the operation fully finished.

Child 4 CPU seconds / 45 wall seconds and outer 6 CPU seconds / 60 wall seconds are per-process limits. Address-space and per-file bounds are 256 MiB and 2 MiB. These do not resolve complete-subtree enforcement, unknown-tail accounting, or the outstanding strict256 budget proof.

## Publication boundary

The result may be published as this exact engineering evidence snapshot, retaining all mixed block results, timing caveats, cost exclusions, and provenance. Its runner depends on the original sibling saved128 layout and existing shared lock; the snapshot is not a standalone portable test. Original payload/model files are not repackaged by this review. Publication provides no authority to rerun, integrate, train, merge, deploy, change permissions, or relax any existing hold or access restriction.
