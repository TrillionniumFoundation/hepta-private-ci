# Original owner publication and synchronous effect entry

## Problem and implementation

A physically read-only SQLite connection does not acquire the intended writer
exclusion through `BEGIN IMMEDIATE`. Actual competing Notes writes committed
while the old retirement callback was held. The former exclusion qualification
is withdrawn; its original failures remain published.

The original State configuration now supplies a private lock-only transaction
in [sqlite_read_barrier.rs](../state/src/sqlite_read_barrier.rs). It opens the
same original owner database with write-capable locking, installs an always
false commit hook, acquires the real writer transaction, then enables
`query_only`. Cancellation closes the connection rather than returning an
intermediate write-capable connection to a pool. The opaque transaction is not
a new grant, state ledger or writable owner factory.

[cognitive_store_barrier.rs](src/cognitive_store_barrier.rs) binds this physical
transaction to the original CognitiveStore and commit gate. It bypasses the
normal mutation checkout hook only to acquire publication exclusion: an
observation must not itself dirty Current. Its database/owner identity still
comes from the original retained configuration. No public wire chooses a
database or supplies SQL. All normal writer/fence rules remain in force.

## Publication, retirement and effect flow

Notes/HOS2 metadata retirement holds this exact owner transaction while
capturing the complete terminal prefix, obtaining its independently bound
whole-owner Current acknowledgement, rechecking the original live authority
and entering the original synchronous metadata callback. The original receipt
is retained when acknowledgement is lost, cancelled or mismatched.

Managed Notes/HOS2 dispatch uses the same transaction for its pre-effect
boundary. It retains the original Entered facts and acknowledges their exact
Current before original FinalUse claim/enter and synchronous channel entry.
[production_effect_entry.rs](src/production_effect_entry.rs),
[operation_claim_entry.rs](src/operation_claim_entry.rs) and
[local_effect_entry.rs](src/local_effect_entry.rs) preserve the original claim,
nonce, request, reconciliation and settlement owners. Missing capability,
revocation, expiry, cancellation or unknown acknowledgement cannot call the
effect channel or create a new rejection/reauthorization proof.

Known FinalUse rejection drops the physical lock before original durable
settlement. A previously checked-out competing transaction can still be
rejected by the original permanent commit gate; a fresh valid admission is a
separate operation. The synchronous entry contract in
[production_writer.rs](src/production_writer.rs) does not cover arbitrary
adapters that postpone the effect until a returned Future is polled.

## Verification and remaining integration

Frozen2ff0a02710 passed74/74 without retry, including every original67 case in
that same run. The9 real SIGKILL cases finished in23.521s under the original60s
watchdog. Tests directly observe SQLite BUSY during retirement and effect
entry, refuse COMMIT even with query_only disabled, preserve Current/token on
ordinary polling and fence a managed owner lacking the serialization capability.

The actual pre-effect negative entered the channel once when zero entries were
required. The original66/67 missing-fence failure,73/74 stale-checkout fixture
failure and final74/74 are preserved, together with source/test ELF identities.
Scoped fix made no source change; committed-range formatting/check passed.
These original-owner and explicit issuer/checkpoint/channel fixture results
qualify this component only. They do not establish installed Root, physical
image durability, real-device effects, a cold writer or persistent CPU G2.

The next integration must use these same original owners with the Root material
publisher, exact-cut recovery factory and actual Host/Session process handoff,
then execute original native time limits and real two-generation crash cases.
No default CLI setting activates authority based on these component receipts.

See [the original success/failure records](acceptance/2026-10-23-owner-barrier-effect-entry/README.md)
and [the old exclusion counterexample](acceptance/2026-10-23-retirement-counterexample/README.md).
