# cognitive.types performance, fuzz and identity closure — 2026-09-30

## Scope and claim boundary

This supplement records source changes for request-scoped canonical-byte reuse,
typed digest identities, target-specific fuzz campaigns, explicit semantic-ID
policy and one stale cross-platform test correction. It does **not** claim that
any product consumer has completed owner-authenticated cutover, compatibility
retirement, independent acceptance, activation or release.

The immutable candidate and evidence rules are defined in
[`IMMUTABLE_CANDIDATE_POLICY.md`](IMMUTABLE_CANDIDATE_POLICY.md). All source
changes are ordinary commits. Qualification workflows have read-only repository
permissions and may not create commits, update refs or push source changes.

## 1. Request-scoped canonical payload

`wire::ValidatedCanonicalPayload<T>` owns four inseparable values:

1. a `Validated<T>` produced by the complete type-local validator;
2. the exact bounded canonical payload bytes produced from that value;
3. a `FrozenContractDigestV1` computed from those exact bytes; and
4. a `SchemaBoundContractDigestV1` computed from the same bytes.

Construction retains the allocation-free bounded-serialization preflight, then
performs validation and one canonical materialization. Subsequent envelope
encoding and both digest reads reuse the retained bytes; they do not serialize
or validate the payload again. Strict wire decode similarly retains the one
canonical payload materialization used to prove that the received envelope was
already canonical.

The type deliberately does not implement `Clone`. It is an owned value intended
to move through one request. It contains no owner identity, source freshness,
revocation observation, authorization, promotion, activation or release result.
There is no global mutable cache and no cache keyed only by payload digest.

The historical byte representation and both digest framings remain frozen.
Existing functions returning `Digest32` remain available for compatibility;
new typed wrappers prevent new code from accidentally interchanging the frozen
and schema-bound profiles.

## 2. Consumer integration

`prepared_consumer` adds checked constructors for the three registered canonical
payload families:

- `MemoryEventV1`;
- `RecallPacketV1`; and
- `ForgetPropagationReceiptV1`.

These constructors reuse the frozen digest held by a
`ValidatedCanonicalPayload<T>` and preserve the existing consumer/payload
matrix, migration-registry authorization, compatibility-digest shape, source
identity, source snapshot, currentness marker and frozen binding digest. Tests
require byte-for-byte and field-for-field equality with the historical
constructor path.

This optimization does not close final use. Each product owner must still read
its current epoch, source/snapshot identity and revocation state at the physical
use boundary and complete use within the same owner synchronization scope.

## 3. Typed digest identities

The source now distinguishes:

- `FrozenContractDigestV1`, the historical contract-name plus canonical-payload
  identity; and
- `SchemaBoundContractDigestV1`, which additionally binds schema, wire version,
  contract and canonicalization algorithm.

Both wrappers have private constructors. Only checked canonical payload paths
can create them. Explicit conversion to `Digest32` is available for frozen V1
wire and compatibility surfaces, but the two wrappers cannot be compared or
substituted implicitly.

## 4. Attributable fuzz campaigns

The original aggregate decoder target remains only for compatibility with the
closed-world HNMF verifier. Product qualification is split into five campaigns:

| Target | Scope |
| --- | --- |
| `hnmf_base` | multimodal span, event and cross-modal binding contracts |
| `hnmf_learning` | engram, synapse, cue, recall, outcome, replay, plasticity, topology and forgetting contracts |
| `shared_experience_v2` | publication, snapshot, use and revocation contracts |
| `consumer_handoff` | prepared binding, typed projection equality and current-binding rejection surface |
| `canonical_json_grammar` | all registered contracts plus malformed JSON/canonical framing |

`prepare_fuzz_corpus.py` derives deterministic, SHA-256-named target corpora
only from checked-in qualification vectors and fixed malformed framing seeds.
It rejects symlinks, empty corpora and filename/content digest disagreement.

`run_fuzz_campaign.py` records, for each target independently:

- exact source commit and tree;
- clean source state before and after execution;
- target, campaign class, duration and RSS limit;
- corpus digest, seed count and corpus bytes;
- executions, coverage edges and feature count when emitted by libFuzzer;
- peak child RSS observation;
- bounded stdout/stderr plus full-stream digests and truncation state;
- crash filenames, sizes and digests;
- generated dependency lock digest and captured resolved lockfile;
- cargo, rustc, cargo-fuzz, Python and platform identity; and
- a sealed receipt digest.

A campaign fails qualification on timeout, non-zero exit, zero executions,
missing resolved lock, any crash, dirty source, or truncated output. Pull
requests execute a bounded exact-head smoke matrix; scheduled/manual runs form
the separate sustained campaign class. These receipts are decoder evidence,
not product activation evidence.

## 5. Unicode and semantic identity

Wire V1 continues to preserve the caller's exact Unicode scalar sequence. The
generic codec does not perform NFC/NFD rewriting and therefore does not claim
that byte-distinct spellings are one logical identity.

`identity_policy` registers an explicit policy for each of the five canonical
consumers. All current consumers select the repository `StableId` grammar,
which is ASCII bounded, and prohibit free text from serving as an identity key.
Tests reject composed/decomposed non-ASCII spellings, confusable Cyrillic code
points and whitespace-bearing identifiers. A future owner-normalized policy
must name its profile and provide owner-local evidence; the generic contract
crate cannot manufacture that proof.

## 6. Cross-platform regression correction

The Windows Lane D failure was a stale assertion in
`hepta-objective::source_envelope_json_tests`: the test expected an empty
`legalActionClasses` collection to fail structural validation even though the
production structure contract deliberately permits the empty set for intrinsic
abstention. The test now keeps all actual count, text and duplicate-key
rejections and explicitly asserts that an empty caller action set survives JSON
decoding. No production validation was weakened.

## 7. Remaining qualification and product obligations

The following remain open until immutable receipts exist for the same exact
candidate:

1. exact-head and deterministic synthetic-merge format, build, test and strict
   Clippy matrices on all required operating systems;
2. passing smoke and sustained receipts for all five fuzz targets;
3. selected-host allocation, latency and sustained-load observations;
4. owner-authenticated final-use observations for every deployed consumer,
   including queue delay, revocation race, epoch drift, stale clone and restart;
5. compatibility retirement and rollback rehearsal;
6. Shared Experience V2 cross-host transport, longitudinal transfer and complete
   influence-removal evidence; and
7. independent acceptance, canary, activation and release governance.
