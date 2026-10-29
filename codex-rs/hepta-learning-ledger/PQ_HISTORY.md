# PQ learning evidence and durable history candidate

This candidate integrates ML-DSA-65 into the existing learning evidence verifier and
`LedgerWriter`. It does not establish a whole-project post-quantum qualification.

## Trust and authorization

`LearningVerificationKey` and `LearningSignature` have closed `ClassicalV1` and
`MlDsa65V2` variants. A host trust distribution selects one profile; every role,
root, distribution signature and evidence signature must match it. PQ evidence,
root and distribution signing domains differ from the classical domains. The
canonical verifier is the shared `hepta-contracts` ML-DSA-65 implementation.
A new signature over an unchanged PQ statement does not change its logical record
identity. Every presented proof is still verified before an idempotent replay can
be returned.

The distribution root signs the complete trust digest, generation, scope, epoch
and validity bounds. Ordinary rotation requires the same root, generation exactly
one greater and a nondecreasing authority epoch and effective time. Root replacement
requires a separate ceremony. PQ validity windows are half-open; classical windows
retain their original behavior.

A PQ product writer requires an independently retained `LearningTrustFrontier`:
root digest, distribution digest, generation and authority epoch. The owner namespace
is `hepta-learning-trust:<ledger binding as 64 lowercase hexadecimal characters>`.
The current value must exactly match the activated distribution. There is no
production local-file or in-memory fallback. A successful external compare-and-set
precedes local trust rotation; an uncertain response cannot justify continued use
of the old distribution. Cloned verifiers and opaque role evidence retain this
external currentness requirement.

The external store remains a host-provided security boundary. Its durable storage,
rollback isolation and operator separation require deployment qualification. The
unit test in-memory store is not a production implementation. The shared contracts
Unix client additionally authenticates service identity, operation, fresh challenge,
response signature, peer UID and an absolute deadline.

## History profiles

| Object | Classical | PQ |
| --- | --- | --- |
| Durable ledger header | `HEPTLR01` | `HEPTLP02` |
| Witness header | `HEPTLW01` | `HEPTWP02` |
| Segmented history header | `HEPTLS02` | `HEPTSP03` |
| Event/chain digest | Original domains | Separate PQ v2 domains |
| Witness frame checksum | Original domain | Separate PQ v2 domain |
| Segment seal | Original domain | Separate PQ v3 domain |

Recovery receives the profile from host policy and rejects another profile before
repairing an incomplete tail. Changing and resealing a classical header cannot
turn its records into PQ history, because record and chain identities use the PQ
domains. `LedgerWriter` requires the history, witness and activated trust profiles
to agree. Existing classical readers and constructors retain their original
semantics; callers must explicitly select the PQ constructors.

A hash-chained history is an integrity structure, not an external signature on every
record. Product admissions verify the existing generator, observer, evaluator and
other applicable role evidence before the original append/fsync/witness path. Local
native owner facts continue to rely on that named owner's authority. Authentication
of every other Hepta control protocol is outside this crate's qualification.

## Time and retained evidence

Signed root and distribution lifetime is retained in cloned verifiers, dataset
freezes and opaque role evidence. A verifier can retain a protected `AuthorityClock`
using `with_microsecond_authority_clock`; this is the required integration for
ordinary PQ installation, whose time unit is Unix microseconds. The protected clock
supplies authorization time whenever retained, so caller time cannot activate
future evidence early or postpone expiry. The lower-level writer API still requires
its host to supply a trusted time policy; it does not manufacture a clock attestation.

## Verified boundary

The scoped release library suites for contracts, learning ledger and artifacts
passed together: 423 tests passed and 3 pre-existing tests were skipped. The ledger
portion passed 127 tests, including three tests of the
actual durable product writer, evidence rejection before replay, dataset freeze and
expiry, distribution CAS rotation, cold restart against an advanced external floor,
relabelled classical history rejection, and segmented rotation/witness recovery.
The additional protected-clock regression rejects future-issued evidence despite
caller-supplied future time, rejects retained evidence at exact expiry and after
clock rollback, and rechecks opaque actor separation using protected time.
The scoped repository `just fix` also completed with warnings.
These checks do not prove remote CI, a deployed protected frontier service, complete
ordinary installation, PoN quantum work security, or proof-system security.
