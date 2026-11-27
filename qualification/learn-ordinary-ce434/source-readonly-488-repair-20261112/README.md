# Repair actual 488 Source/read-only QA failures

This change is based on the original 488 source-suite failure excerpts, not on a new execution. The source is `48844493c046fdd79734ddd2c1866314023a15cb`; the original manifest is `7df13b4c965af0a6e1c93989075b173fd1ff8db5`.

## Repairs

- The six evidence-dispatch subtests failed before mutation because the same path now legitimately has two complete protected records. The QA helper verifies both records and preserves the private Model export restriction.
- A duplicate error literal in the new Source operation function hid deletion from the original capture function. The QA now checks each actual, function-local Source missing-value expression. Comments, strings, nested helpers and other functions cannot supply that expression. The original Rust remains unchanged.
- The native training owner has two valid permanent fences. Physical-CURRENT mutation now targets its actual `if result.is_err()` branch, while the existing Source-operation test independently removes the cancellation fence.
- Three Source functions had one-element function-order sequences, which the original verifier rejects. Each sequence now retains its complete original expression and adds the actual receiver parameter; the original expression must also remain at function top level.
- Two training owner boundaries still expected the pre-Arc field spelling. Only that definition marker is updated to the actual `source: Some(Arc::new(source))`; caller sets and authority remain unchanged.

## Preservation and validation

The manifest still contains 686 boundaries and 463 complete protected records. Four whole records are replaced explicitly; all 1,145 unowned raw records and boundary ID order are preserved. No path deduplication is performed. All 29 original test methods in the four edited modules remain; no test method is removed or added. No production Rust, verifier, key, grant, lease or policy changes.

A V8 projection checked 14 relevant complete records, 40 functions, 308 sequence markers and 54 top-level guards. It rejected 25 targeted deletions and eight comment/string/nested/outside-function literal decoys. This is not execution of the Python verifier, Rust or native suite. The independent Model wire top-level one-marker repair is outside this commit and still needed in the combined source.

[repair-contract.json](repair-contract.json) contains complete before/after records and methods, original trace blob pins, the narrow projection and all mutation results. Root must run the original source suite after merging the fixed candidate. Ordinary acceptance remains zero.
