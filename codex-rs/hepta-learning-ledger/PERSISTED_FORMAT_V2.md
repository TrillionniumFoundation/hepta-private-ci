# Additive persisted event/header codec, not an activated store

The reserved encodings are journal `HEPTLR02`, segment `HEPTLS03`, and event
domain `hepta.learning-ledger.event.v2`. These strings were absent in both exact
historical source trees (integration6000 and operatorc322); live ledger PR1325
remained d421 with no codec changes beyond6000. Runtime bridge work confirmed no
conflicting reservations. Existing V1 journal/V2 segment writers and recovery
continue unchanged. No existing file is rewritten or automatically transcoded.

## Event bytes

`event.v2 domain || kind:u16be || body_length:u32be || body` is bounded to 65536
bytes including its envelope. SHA-256 over those complete bytes is the new event
identity. Kinds0..8 retain their explicit legacy body grammar; kind9 is named
`LegacyRetrievalAssignment` and remains an old owner-asserted exposure fact.
New kinds0x0100/0x0101/0x0102 mean preparation, assignment intent and host-write
confirmation, respectively. Unknown kinds and body/length/version mismatch reject.

The preparation and old assignment can share body bytes yet have different
meaning and V2 digests. Dispatch is selected solely by the explicit new kind;
there is no trial decoding. A new kind/checksum is a syntax discriminator, not
proof that the asserted event happened. Source preparation is never inferred to
be a host write, and confirmation remains distinct from peer/model consumption.

Bodies are structurally parsed using the exact bounded legacy grammar helpers.
This does not perform stateful causal replay, authenticate evidence, or make
arbitrary caller-provided bodies appendable. In particular, confirmation's intent
reference is retained exactly; encoding a new intent changes its digest and does
not silently rewrite an old confirmation or other historical reference.

## Fixed 192-byte header

Offsets, all integers big-endian:
-0..8: magic;8..10: header layout2;10..12: event codec2
-12..16: flags, only0(new history) or1(legacy manifest present)
-16..48: nonzero store binding
-48..56: nonzero owner generation;56..64: nonzero writer fence
-64..72: segment index (journal0; segment less than1024)
-72..80: predecessor sequence;80..112: predecessor chain digest
-112..144: legacy manifest digest (zero iff flag0)
-144..152: record bound1..8192;152..160: byte bound4096..8388608
-160..192: SHA-256 of bytes0..160

Sequence zero and zero predecessor digest must agree. An initial header without
legacy manifest cannot invent a nonzero predecessor. Later segment lineage,
exclusive fencing, an authenticated whole legacy inventory/profile, and witnessed
activation require the owner-controlled preparation/recovery stage. A caller can
construct a different valid header and checksum: codec success authenticates
neither the plan nor a generation/fence claim.

## Validation and remaining stages

The actual original writers generated the preparation/intent/confirmation fixture
bytes, whose original identities remain in PROVENANCE.json. Pure codec tests
exercise independent Python header/event vectors, both historical tag10 meanings,
all three new retrieval kinds, truncation, trailing bytes, kind/version/length
substitution, corrupt headers and invalid bounded contexts.

Full ledger tests after this codec stage:143 passed, one existing opt-in growth
case skipped. Strict all-target Clippy and format passed. These are structural
source tests, not target-host durability, recovery or production acceptance.
The subsequent frame/chain codec and owner-authorized migration preparation remain
separate work. No live migration, witness reset, post-expiry re-signing, writer
switch, default bootstrap, activation, merge or deployment is added here.
