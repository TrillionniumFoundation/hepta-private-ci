# Checked decoding and complete evidence-file integrity

Implementation increment prepared against source `1a6ae24bede692272f41e2e91ae1469cbee0f65d` on `codex/cognitive-types-full-closure-20260927`. The containing Git commit identifies this increment; the base above is a navigation anchor, not a passing qualification receipt. The existing implementation map remains the only product-status authority.

## Preserved contracts and authority boundaries

The actual registered consumers are `cognitive.read`, `cognitive.store`, `memory.retrieval`, `compact.engine`, and `intelligence.control`. This increment neither introduces a second writer nor promotes their shadow/pending-cutover registrations. Complete operation/consumer/source/snapshot/payload/compatibility bindings, independent expected projections, and final current-owner revalidation remain mandatory. Frozen and schema-bound digest domains, canonical bytes, historical receipt interpretation, and the handoff receipt format are unchanged.

The current crate uses `CognitiveWireError` and `ContractViolationV1`. This increment does not claim a `RejectionInfo.cascade_id` repair; that earlier review description was not corroborated in this crate. Existing shared consumer constructors and refusal mapping are retained rather than replaced.

## Checked decoder, profiles, and refusal diagnostics

`wire.rs` now obtains the immutable validated payload and its exact canonical bytes through one private strict-decoder result. Existing public decoders delegate to that result. The existing handoff uses a crate-private combined decode/digest helper, eliminating repeated serialization of the received payload and its redundant type-local validation. Its independent expected projection is still separately checked. No bytes or authorization conclusions are cached across requests. The existing checked paired-digest calculation is exposed as an additive pure API; its byte-level helpers remain private.

The bound digest streams the original framed components through the existing `Digest32::of_parts` implementation, instead of allocating a second payload-sized concatenation. The schema, envelope version, contract identity, canonicalization algorithm, lengths and payload order remain unchanged. New Rust regression assertions compare the exact old concatenation and count validation/serialization calls; they were not executed in the local environment described below. No latency, allocation-count or production-throughput improvement is asserted without measurement.

The handoff previously checked the generic type's contract name but not its schema or encoded-byte ceiling. A transparent wrapper could retain the frozen digest while supplying a different profile. It now checks both constants against the actual registered payload type. `handoff_profile_tests.rs`, included by the existing contract suite, covers both substitutions for all five consumer families and checks that a subsequent legitimate call still uses the same public handoff. These are contract fixtures, not authenticated normal-product integrations or a sandbox for hostile Rust trait implementations.

Error construction and audit mapping move internally to `wire_error.rs`, with the existing `wire::CognitiveWireError` public path re-exported. JSON `violation()` diagnostics retain stable error category, field path and parser coordinates but do not echo input-bearing Serde text. Historical `Display` and `source()` diagnostics remain unchanged and are not claimed to be payload-free. Audit consumers should use the structured violation. The public decoder regression checks a malformed version containing an input marker.

## Check-plan version 2: retain actual result files

Previously the six-receipt verifier checked command logs but did not bind auxiliary JSON or nested mutation logs. A local, explicitly synthetic verifier fixture reproduced acceptance after modifying `quality-receipt.json`. This is an evidence-integrity counterexample, not evidence of a production compromise.

`evidence_inventory.py` now records sorted relative paths, byte lengths and SHA-256 digests of every regular evidence file. Only the root `receipt.json` and `receipt.sha256` are excluded to avoid a digest cycle; their existing verification remains mandatory. The native group additionally requires `quality-receipt.json` and `mutations/mutation-receipt.json`. Missing, added or modified files, unsafe names, symlinks, special files, duplicate/unsorted inventory entries and boolean-as-integer metadata reject. The runner cannot seal a pass when mandatory files are absent. The six-receipt verifier independently rebuilds the inventory and includes it in the aggregate report.

The scan has explicit engineering ceilings: 1,024 non-sidecar entries, depth 16, 512 UTF-8 bytes per relative path, and 2 GiB total file bytes. Hashing uses at most a 1 MiB read chunk and checks for observed file changes while reading. Exceeding a ceiling fails; it never silently truncates evidence. These are integrity-resource bounds, not measured production capacity. The verifier is not an independent trust root for candidate-controlled code or a hostile-filesystem sandbox.

The existing mutation runner now receives a separate external evidence directory through the normal qualification command plan. Its sibling build targets and temporary source worktrees therefore do not enter the upload directory. A separately recorded archive command copies the completed evidence back, verifies exact bytes before/after copying, and refuses an existing destination. `CARGO_TARGET_DIR` is explicitly placed outside the source and upload directories and recorded in each execution receipt. Source/evidence/scratch overlap, including resolved scratch aliases, rejects. Reusing a nonempty evidence output rejects rather than overwriting a previous attempt.

No command is removed or weakened. The existing exact-head/synthetic-merge by native/consumer/owner matrix and read-only workflow remain in use. Missing tools, timeouts, failed builds and invalid experiments are not converted into passes or killed mutants. Failed archive or inventory checks leave qualification false. Older check-plan receipts cannot qualify the new plan.

## Executed local checks and remaining acceptance

The local workspace contained a SHA-verified subset of files fetched from the base above, not a complete repository checkout. Python 3.13.5 actually ran the following scoped suite against the changed runner, verifier and inventory implementation:

```sh
PYTHONPATH=qualification/cognitive-types-v1 PYTHONDONTWRITEBYTECODE=1 \
  python -m unittest -v test_run_qualification test_verify_receipts test_evidence_inventory
```

Result: **39 tests passed**. The suite includes deterministic synthetic Git fixtures, process-group timeout cleanup, complete six-artifact fixtures, required-file omissions, resealed receipt substitutions, nested-file tampering, exact byte-budget edges, FIFO/link refusal, archive separation, and stale-output/overlap rejection. Fixture successes do not report Rust execution. Test-log SHA-256: `dd3fe5928e947433d8a9e73e0a492b05b937dabd5dfb9cda31a0750091c4f580`.

Python AST parsing and changed-file whitespace checks were also performed. The existing runner tests are unchanged. Other repository Python suites were not executed in this partial local workspace.

Rust compilation, rustfmt, strict Clippy, package/consumer/owner tests, actual Rust/Node differential execution, actual mutant kills, the repository's pinned-base synthetic merge, sustained fuzzing, selected-host measurements, and authenticated default-profile composition of all five consumers remain unestablished locally. They must be resolved by the containing commit's real remote qualification and owner evidence. No implementation-map acceptance, convergence, activation or release flag is promoted by this document or these fixtures.
