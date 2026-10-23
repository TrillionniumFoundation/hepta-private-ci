# Strict probe observations and actual output parity

Prepared against `1aaa2cf7a1c4f7899782bcbf82dac66f38f5a4f9` on `codex/cognitive-types-full-closure-20260927`. The containing commit identifies this increment; the base is not a passing receipt. The existing implementation map remains the only completion authority.

## Preserved owner and protocol boundaries

The registered consumers remain `cognitive.read`, `cognitive.store`, `memory.retrieval`, `compact.engine`, and `intelligence.control`. There is no new owner, executor, write capability, cross-request cache, migration promotion or fallback success path. Existing complete bindings, independent expected projections, frozen/schema-bound digest profiles and current-owner revalidation remain intact. This increment does not claim a `RejectionInfo.cascade_id` repair; the current crate uses `CognitiveWireError` and `ContractViolationV1`, as the preceding supplement explains.

## Match both the typed value and its actual canonical output

The public generic handoff previously selected `Matched` from Rust equality alone, although it separately computed both schema-bound output digests. A lawful `Eq` implementation may be coarser than serialization. The existing handoff now requires both typed equality and equality of those already computed digests. No new serialization, digest domain or receipt format is introduced. A mismatch remains inspectable but cannot release the payload through `require_match_for_current_binding`.

The existing included `handoff_profile_tests.rs` adds a transparent fixture whose equality is reflexive, symmetric and transitive but ignores payload differences. The regression exercises the public handoff for all five consumer families, checks differing actual output digests, structured refusal and subsequent legitimate use. It delegates validation and serialization to the real payload types. These are contract-level fixtures, not authenticated product executions or a sandbox for malicious Rust implementations. Rust execution of the added regression has not been established locally.

## Strict, bounded execution of the existing qualification probe

Two baseline counterexamples were actually reproduced against the SHA-verified original `quality_checks.py`: `encoded_bytes: true` matched an expected integer `1`, and floating-point/string/boolean performance fields were coerced with `int()` into a valid-looking measurement. Both now reject through the existing entry points.

`quality_checks.invoke` delegates to the private qualification helper `probe_execution.py`. It executes the configured Rust or Node command, never a replacement codec. Expected fields compare recursively with exact JSON value types. Reports must be UTF-8 JSON objects with recognized outcomes; duplicate keys, non-integer JSON numbers, nonfinite values, excess integer range and malformed roots reject. Semantic rejection requires exit code 2 and the rejected outcome together. Crashes, invalid reports, resource limits and timeouts are infrastructure-invalid, not passing negative cases or killed mutants.

On the qualified POSIX host, stdin, stdout and stderr are serviced concurrently with a monotonic deadline. Input is capped at 1,049,601 bytes: the existing probe ceiling plus one byte to permit an oversize-input regression. Stdout is capped at 64 KiB and stderr at 256 KiB. The 60-second deadline covers pipe draining and process completion. Cleanup terminates the invocation's process group, including descendants that retain inherited pipes. Only complete captured outputs receive complete-output hashes; a truncated prefix cannot count as success. The displayed stderr tail remains bounded. This is bounded qualification process management, not a hostile-code operating-system sandbox or general Windows executor.

Performance observations now require exactly three successful, ordered Rust samples of the declared maximum-collection MemoryEvent workload, with repeat count 256, matching input/observed wire hashes, unchanged frozen and bound digests, and consistent encoded sizes. The Rust probe's existing `elapsed_ns` decimal-string representation is preserved and validated as a canonical positive u128 string; repeat and size remain strict JSON integers. Missing values, booleans, floats, numeric coercion, leading signs/zeros, changed workloads, incomplete samples and changed output identities reject. The statistical output remains observation-only, with no invented latency threshold or allocation measurement.

The existing command plan already discovers `test_*.py` in this directory and runs the real differential-quality command. The new executor tests enter that same plan without deleting or weakening any command, native package check, consumer/owner group, mutation run, six-artifact verifier or source/merge identity check. The handoff regression enters the existing included contract suite; no new build-time data file is added.

## Actual local execution and limitations

The local workspace was a partial source mirror, not a full repository checkout. Baseline copies were checked against Git blob identities before editing. Python 3.13.5 on Linux actually executed:

```sh
PYTHONPATH=qualification/cognitive-types-v1 PYTHONDONTWRITEBYTECODE=1 \
  python -m unittest -v test_probe_execution
```

Result: **16 tests passed**. These include real synthetic child processes, exact output-limit boundaries, simultaneous input/output, ambiguous JSON, inconsistent exit outcomes and a Linux grandchild/pipe timeout cleanup check. Synthetic processes are verifier fixtures, not Rust execution. Log SHA-256: `3ee481c8417d06a0243c1645dc1b2084e478aecea01be55ce6311320399286f8`.

Four additional local checks used the unchanged, SHA-verified `verify_lossless_wire.mjs` under Node v22.16.0 through the modified `quality_checks.invoke`: frozen/bound golden digests, full-width u64 boundaries, distinct Unicode representations and six noncanonical-input variants. All four passed against independently computed Python expectations. This was a scoped local harness, not the full repository `test_quality_checks` suite or a Rust/Node differential run. Log SHA-256: `1dd9a971f5bb13b6ac10ed08519a03a7817b47a9cd1ef771907d01e62439506d`.

Python AST parsing and changed-file whitespace checks were also performed. No Cargo or rustfmt executable was available locally. Native build, strict Clippy, Rust tests, WASM/FFI checks, full repository Python checks, the pinned-base synthetic merge, actual Rust differential and mutation execution, authenticated default-product composition of all five consumers and selected-host performance remain unestablished by these local results. Remote qualification must bind the containing commit and its actual outcomes. No acceptance, convergence, activation or release flag is promoted here.
