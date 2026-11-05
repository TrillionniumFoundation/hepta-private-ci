# Current H7 production authority

The existing lifecycle-only daemon remains available without an H7 authority
policy. Its bounded local administrative lifecycle operations, including release
upgrade and rollback, use the current PQ Fleet `NodeSoftware` permission and
per-Agent release allowance. That mode cannot admit signed production mutations
or signed production recovery. It does not claim an H7 grant for every local
administrative transition. Removing the H7 policy configuration does not clear
retained signed intents or their external anchors: unresolved or mismatched
history still fences process entry and ordinary mutations.

The separately configured signed production mode requires the
`production-authority` build feature and an explicit
`--production-authority-policy` together with the existing PQ release trust
configuration. The policy contains three distinct ML-DSA-65 keys for grant,
artifact and recovery roles. It is strict bounded JSON, and its original bytes
must be authorized by the current M15 `ProtocolConfiguration` publication.
Parsing a policy or verifying a signature alone does not provide that permission.

The configured production owner rejects legacy grant verifiers. Explicit qualification
registries retain the original Ed25519 constructors and original v1/v2 signing
bytes. A PQ H7 artifact remains a qualification artifact; its production and
promotion flags remain false. A separately signed production grant carries the
original operation scope, CAS fences and fresh supervisor epoch.

## Durable admission and process entry

New grants use schema 2 and recovery decisions use schema 3, with distinct PQ
message domains. They bind the exact policy digest and explicit signing role.
The existing signed-intent journal uses schema 3 for a PQ operation and retains
the original policy bytes, grant and artifact envelope. Recomputing a local
journal hash cannot substitute for those signatures.

Prepared or Queued operations recheck both NodeSoftware and ProtocolConfiguration
under one existing publication-owner lock at the actual process entry and the
release-state CAS. The same fresh trusted clock checks the intersection of grant
and artifact validity. The owner rechecks the original signatures, Agent,
source/target, control revision, lifecycle generation and authority epoch, then
refreshes the current publication check before entry.

A new supervisor instance does not automatically resume a pending grant from an
older epoch. It discovers the exact retained process identities for containment
and leaves unresolved operations quarantined. The current external intent anchor must match the exact retained snapshot. A
local terminal label, transaction hash or matching release name is not an
independent completion witness; these records are all locally recomputable.
True terminal publication binds the original transaction and exact release-state
CAS witness into the existing monotone Fleet publication owner before a later
process entry can treat it as completed history.

Committed, RolledBack and explicitly authorized Aborted records are historical
facts. Later normal starts use current NodeSoftware permission and current release
selection. They do not reuse the old grant or require its expired validity window
to remain open. Matrix startup after the original primary commit belongs to its
existing independent companion lifecycle: it requires the exact committed current
release and a fresh release admission. A revoked release or unresolved signed
intent still refuses a new process.

## Recovery and bounded history

Recovery uses the current explicitly configured recovery role, even when the
original grant policy is retired. An Unknown disposition retains its original
facts; it does not claim a successful commit or rollback. All original nonce,
transaction, observed-release and epoch bindings remain mandatory.

An unresolved legacy operation does not gain original PQ provenance. The
ordinary production owner permits only a freshly authorized PQ Unknown
disposition for such history and refuses Committed/RolledBack recovery before
writing any transaction, intent or external CAS. Explicit qualification keeps
its original legacy recovery behavior. A retired current policy or unavailable
current permission remains a refusal; these component recovery paths do not
claim general liveness under a missing or revoked external authorization root.

The durable journal remains bounded at 262144 bytes and 32 retained Unknown
entries. Its reader opens one bounded regular-file descriptor and refuses FIFO,
symlink and oversized inputs. Existing valid history remains readable. A full
history refuses another disposition and preserves the existing bytes.

Every new snapshot is durable locally before the same Fleet owner's external
CAS. One bounded predecessor snapshot preserves the exact previous external
anchor until that CAS is confirmed. A current file or predecessor match never
automatically resumes an operation. A protected, previously completed transaction
remains present when the next grant is Prepared but has not created its own
transaction. Recovery signs that actual old transaction and current release
state; it must not replace them with an invented absence observation.

An uncertain publication leaves the ordinary registry fenced. The explicit
`--release-intent-recovery` daemon flag requires the normal release trust
configuration and current three-role policy. Startup discovers and contains
existing exact process identities before exposing its control socket. This mode
allows observations and signed recovery ceremonies; it cannot start processes
or accept a new release mutation. Even after a successful publication it remains
fenced until an ordinary authenticated reopen.

The signed recovery operations distinguish these retained facts:

| Operation | Required retained state | Result |
| --- | --- | --- |
| `abandon_unknown` | An unresolved operation, exact external predecessor or explicitly authenticated absence, current source and actual transaction observation | Consume the grant and append one Unknown disposition without claiming success or dispatching an effect |
| `confirm_unknown_publication` | The existing Aborted intent already contains its original PQ Unknown decision | Confirm that exact snapshot without adding a 33rd history entry or changing the original grant provenance |
| `confirm_completion_publication` | An original uncertain proposal from the actual hot owner contains the exact Committed or RolledBack CAS witness | Confirm only that original completion, preserving intent, transaction and history bytes |
| `retry_retained_publication` | One original proposal and one exact retained replacement, including the actual presence or absence of its attempt record | Retry the same expected-to-proposed CAS under a new current signature, with no third proposal and no replacement of the prior signed material |

Confirmation retains bounded public policy and signature material in one current
slot and one predecessor slot. These files are historical verification material,
not live capabilities. Every new publication ceremony verifies its current
signature, daemon/lifecycle fences and exact observations, and binds its signed
window to the owner. The owner reads trusted time again after local durability
work and immediately before the external CAS. An expired decision therefore
cannot gain time merely because serialization, hashing or fsync took longer.

The ordinary control frame remains 65536 bytes. PQ recovery uses the versioned
bounded pagination interface; the old inline mutation rejects before committing
when a safe inline response cannot be guaranteed. Read cursors bind one exact
state and control fence and do not create authority.

The tests use real ML-DSA messages and real M15 publication, clock and external
frontier component fixtures. These fixtures are not production custody, public
network or whole-chain quantum-security qualification.

## Explicit offline signing ceremony

`hepta-authority-signer --sign --profile ml_dsa65_v2 --policy ABSOLUTE_PATH`
requires exactly one `--key-file ABSOLUTE_PATH` or `--key-fd FD` and a bounded
reviewable JSON request. The policy identifies three distinct grant, artifact
and recovery keys. The supplied owned seed must derive the exact canonical
public key for the requested role; a different role's seed is refused.

The offline request covers artifact, grant, normal recovery, explicit Unknown
recovery and the three distinct publication ceremonies above. Every predecessor
or absent-anchor observation must be supplied explicitly in the reviewed request;
the signer does not infer it from local files. It creates no permission to
activate an artifact or process.
Current M15 publication, clock, external frontier and original lifecycle owners
still decide actual use. The key reader does not print or persist key bytes and
zeroizes its input buffer. On Unix it uses one non-following regular descriptor,
checks current-owner and group/world mode restrictions, and enforces its byte
bound before reading. New PQ key-file import refuses unsupported non-Unix owner
permission checks; ordinary supervisor process hosting is already Unix-only.

The retained Ed25519 ceremony must explicitly select
`--profile ed25519_v1_qualification` and refuses a PQ policy option. There is no
automatic algorithm detection or role inheritance in the PQ ceremony.
