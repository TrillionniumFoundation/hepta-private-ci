# Consumer binding hardening — 2026-09-29

This supplement describes the source changes through
`dd95b2cf1feb2389b4558d4a3a295c462fc47825` on
`codex/cognitive-types-full-closure-20260927` (PR #1134). It does not
supersede the module's normative contract, technical guide, implementation map,
or qualification policy. Source implementation and test definitions are not
execution evidence or authorization for product cutover.

## Source increments

| Commit | Source change |
| --- | --- |
| `2747f96cd68a8fdf3d3330012d1f3462c1623429` | Add exhaustive, payload-free refusal projection regressions in `codex-rs/hepta-cognitive-types/src/consumer_error.rs`. |
| `8bbff1299c8d7a92d08322ecc6d01da1d4936e9c` | Introduce private frozen-framing implementation and parity regressions in `codex-rs/hepta-cognitive-types/src/consumer_digest.rs`. |
| `dd95b2cf1feb2389b4558d4a3a295c462fc47825` | Connect the existing public binding digest method to the private streaming implementation in `codex-rs/hepta-cognitive-types/src/consumer.rs`. |

## Preserved boundaries

The existing public constructors, binding fields, consumer/payload matrix,
migration authorization, mandatory final-use revalidation marker and historical
validation remain in place. The private digest module does not create another
consumer execution path, registry, wire protocol, persistence owner or source
of authority. It cannot authenticate a source observation or authorize a write.

A binding digest commits to the supplied source identity and snapshot digests;
it is not proof that those supplied values came from a current authenticated
owner observation. Existing owners must still validate complete source identity,
scope, revocation/currentness and the actual output at their normal use boundary.
Historical validation does not authorize a new use or revive retired compatibility.

## Refusal projection

The existing exhaustive `CanonicalConsumerBindingError::violation()` mapping is
retained. Three new tests establish the intended regression obligations:

- `every_binding_refusal_preserves_its_stable_code_and_field` exercises all ten
  variants and compares borrowed and owned conversion results.
- `untyped_messages_cannot_inject_audit_categories_or_payloads` checks that
  untrusted error text cannot inject a typed audit category or copy private,
  control-character or bidirectional-control text into the structured projection.
- `audit_projection_size_does_not_scale_with_untrusted_error_text` compares the
  projection of a short message with a one-MiB message.

These obligations apply to the structured projection, not every possible use of
the public error's `Display` implementation. The historical untyped
`CanonicalContract(String)` variant is deliberately not parsed to invent a more
specific machine-readable category. Consumers must use the structured audit
projection rather than treating arbitrary diagnostic strings as trusted fields.

## Frozen V1 digest framing

The pre-existing SHA-256 input is preserved as raw concatenation, in order:

1. `hepta.cognitive.consumer-binding.v1` followed by one NUL byte.
2. The operation ID's byte length as an unsigned 32-bit big-endian integer.
3. The operation ID bytes.
4. One consumer tag and one payload-family tag.
5. The canonical payload, source identity and source snapshot digests, each 32 bytes.
6. One optional-compatibility presence tag; when present, its 32-byte digest.
7. One migration-posture tag and one final-use-revalidation marker.

`compute_binding_sha256()` delegates to a private function using
`Digest32::of_parts`. Each call hashes the supplied fields again. The change removes
the explicit concatenate-into-`Vec` step; it does not cache an authorization,
source-validity decision, migration state or prior binding result. No profile,
domain separator, field order, length encoding or optional-field tag is changed.

The allocation claim is narrowly about removal of this explicit concatenation
buffer. End-to-end latency, allocator behavior, throughput, peak memory and product
performance have not been benchmarked by these increments. No speedup percentage
is claimed. The independent concatenating implementation exists only under
`#[cfg(test)]` as a frozen reference, not as a second production path.

## Regression inventory and limits

`streamed_digest_matches_frozen_reference_for_all_tag_combinations` compares the
private streaming implementation and the existing public method against the
independent concatenating reference. Its 540 combinations are:

`3 operation IDs × 5 consumers × 3 payload families × 3 migration postures × 2
compatibility-presence states × 2 revalidation-marker states`.

Some combinations are intentionally invalid bindings. Digest parity for such
inputs does not imply that validators must accept them. Validation remains a
separate obligation.

`changed_identity_output_or_marker_never_reuses_a_previous_digest` mutates ten
individual fields of a valid historical binding. Each mutation must change the
computed digest and make the original sealed binding fail historical validation.
This does not claim detection of an attacker who recomputes an unkeyed digest;
owner authentication and current-use checks remain required.

`frozen_digest_matches_independent_python_sha256_vector` checks a fixed,
independently reproducible vector through both the private helper and public
method. Reproduce its expected value with Python's standard library:

```python
import hashlib

operation = b"operation-1"
parts = [
    b"hepta.cognitive.consumer-binding.v1\0",
    len(operation).to_bytes(4, "big"),
    operation,
    bytes([0, 0]),  # CognitiveRead, MemoryEvent
    hashlib.sha256(b"canonical-payload").digest(),
    hashlib.sha256(b"root-identity").digest(),
    hashlib.sha256(b"root-snapshot").digest(),
    b"\x01",
    hashlib.sha256(b"legacy-payload").digest(),
    bytes([1, 1]),  # CompatibilityBound, revalidation required
]
expected = "1b34018fdc4ea4353d65f798915dc54dc63d82cd750bc03ff3b5fd8d089b12e7"
assert hashlib.sha256(b"".join(parts)).hexdigest() == expected
streaming = hashlib.sha256()
for part in parts:
    streaming.update(part)
assert streaming.hexdigest() == expected
```

## Execution evidence and acceptance

The independent Python vector above was executed successfully during this change.
That check is not execution of the Rust implementation. The local editing runtime
has no Rust toolchain; it did not execute Cargo tests, Clippy, rustfmt, WASM,
FFI, actual product-consumer entrypoints or performance benchmarks.

At the last observation of source head `dd95b2cf1feb2389b4558d4a3a295c462fc47825`,
`cognitive-types-qualification` run `36530165627` and `hnmf-qualification` run
`36530165496` were pending. This is an observation, not a promise of completion or
a successful result. Later documentation commits require their own applicable
qualification; results must not be silently transferred to a different head.

Focused checks for the Rust additions, from the repository root, are:

```sh
just test -p codex-hepta-cognitive-types --locked consumer::error_mapping::tests
just test -p codex-hepta-cognitive-types --locked consumer::digest_encoding::tests
just test -p codex-hepta-cognitive-types --locked
cargo clippy --manifest-path codex-rs/Cargo.toml -p codex-hepta-cognitive-types --locked --all-targets -- -D warnings
```

These commands do not replace the existing full exact-head and pinned-base merge
qualification workflows. Preserve locked dependency resolution. A lockfile,
compiler, fixture, timeout or infrastructure failure is not a passing test and
must retain its failure classification and diagnostics.

## Remaining scope

This increment is not closure of all requested module work. The five real
consumer product paths (`cognitive.read`, `cognitive.store`, `memory.retrieval`,
`compact.engine`, `intelligence.control`) still require current authenticated
normal-entrypoint evidence, actual output binding and rejection propagation.
A five-tag hashing loop does not establish five-consumer product composition.

FFI/WASM execution parity, the broader hostile-codec and numeric-boundary suite,
compatibility retirement, current exact-head/merge acceptance and measured
performance remain governed by the existing qualification obligations. This
supplement does not promote implementation-map status, enable a feature, retire a
legacy path, weaken a gate, or claim production readiness.
