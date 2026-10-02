# Read-only legacy format inspection

This additive API inspects bytes; it does not recover a store, authenticate
provenance, repair a tail, append, migrate, activate a writer or issue authority.
Its caller-selected profile is explicitly unauthenticated. A successful result
means bounded structural parsing and checksum/sequence consistency, not causal
ledger replay, witnessed durability or independent semantic admission.

The actual source profiles are:
- integration `6000e4068ce9c3c215346cd81686a37932fa53a1`: tag10 is
  RetrievalPrepared, encoded using the old assignment body shape;
- operator `c3228764172df19e37894053b54d3a8b5a1a6520`: tag10 is
  RetrievalAssignmentIntentV2 and tag11 is publication confirmation.

Both use event.v1, HEPTLR01 and HEPTLS02. No profile is inferred from a successful
decoder, branch name, payload length or checksum. Missing profile rejects before
parsing; a known profile invokes exactly its grammar. The preparation parser
checks the original wire state before interpreting exposure-shaped fields as
preparation. It never returns a publication or consumer-acceptance claim.

`InspectedLegacyEventV1` retains original bytes and their original digest.
`inspect_legacy_container_v1` checks one bounded complete journal/segment and
reports its original digest, sequence and seal facts. The inspector bounds each
input to 8 MiB and 8192 records; it does not promise to accept every historical
store or a concatenated multi-segment history. A complete unsealed frame tail is
structurally valid, while a partial frame/footer rejects. Incomplete tails reject
without repair. A valid empty/prefix container can inspect successfully, but
cannot satisfy an independently retained later witness by itself. Cross-segment
inventory completeness, causal replay and authentic provenance are owner duties.

The durable codec's assignment-body parser is mechanically extracted for reuse;
its original tag9 writer/decoder semantics remain unchanged. Existing durable
creation/recovery/append paths do not call the new inspector.

## Source-generated fixtures and tests

`tests/fixtures/legacy-format/PROVENANCE.json` records exact source commits and
SHA-256/lengths. Two isolated workspaces compiled the actual original ledger,
types, intuition, memory-retrieval and cognitive-types source. A test-only helper
invoked the original encode_event, DurableLedger and SegmentedLedger to create
fixtures. The helper texts are retained. Their minimized workspace manifests
omit unused workspace members and patch entries; these runs prove fixture origin,
not whole original-workspace qualification. No production encoder was altered.

Both generators passed. New inspection regressions use their frozen event,
journal and sealed-segment bytes, exercise both tag10 meanings, wrong/missing
profiles, bounds, unknown tags, truncation, and a frame whose altered predecessor
has a newly recomputed checksum. Original buffers remain unchanged.

The full operator-lineage ledger suite ran 138 passed, one existing opt-in
performance case skipped. This does not inherit the other branch's 139-test
results or solve its distinct post-expiry one-event-lag recovery problem.
A new checksummed discriminator still needs an independently authorized migration
plan and an equal witnessed cut before any future writer switch.
