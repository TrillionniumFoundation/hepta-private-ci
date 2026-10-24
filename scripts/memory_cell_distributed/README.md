# Memory cell authority, source boundaries and separate-runner experiment

This extends the existing research `ParametricOwner` and `Worker` paths with
explicit authenticated transport, a durable replicated control plane, live source
admission, and a separately registered two-runner checkpoint experiment. Neither
mechanism tests nor a successful transfer establish general memory quality,
compression advantage, future-task advantage, or production model authority.

## Fixed-membership authority

`authority_contract.py`, `authority_replica.py`, and `authority_client.py` implement
a single trusted writer with 3–7 fixed Ed25519 replica identities. Each replica
durably votes for at most one proposal per scope/sequence. A certificate needs a
majority of distinct valid votes. Publication requires durable majority commit
acknowledgments; reads require a responding majority and choose its highest valid
certificate. Placement changes use stable cell IDs and increasing generations.

An ordinary crash may leave a prepared majority without a completed publisher.
`recover_pending` can complete that exact proposal without obtaining a new writer
signature. `repair` transfers a continuous certified chain to a lagging member.
There is no leader election, Byzantine tolerance, dynamic membership, automatic
split-vote resolution, or unbounded history. Budgets are 64 scopes, 64 placements
per scope, 4,096 roots per list and 4,096 sequence entries per scope.

The SQLite database, owner identity file and independent head fence must be
durable. Losing the database or restoring it below a surviving fence fails
closed. Restoring an entire volume and signing keys to an old state is outside
this fault model. A majority that loses durable votes is not a safe deployment.

## Transport and the source boundary

`tls_wire.py` requires TLS 1.3, a verified server hostname, a client certificate,
and exact certificate grants for operations and scopes. Source-evidence reads
also require the exact source root. No plaintext fallback is provided. An
administrator must provision the CA, certificates, keys and grants; a scope
string or a self-signed data digest is insufficient authorization.

`SourceEvidence` reads current canonical bytes from the existing `SourceStore`.
It refuses old revisions, withdrawal and conflicting sources. It returns an
explicit source-evidence response, never a parameter-generated response.

`SourceBoundAuthority` composes quorum placement with an online source-frontier
read before and after each `ParametricOwner` callback. An unreplicated correction,
withdrawal, conflict, source outage or authority minority prevents delivery. This
keeps the source owner an availability dependency: replicated placement does not
turn the source database into a replicated multi-writer system. The native owner
authorization work is separate from this research SourceStore ingress.

`NetworkClient` and `Worker` retain their legacy default transport, while allowing
an explicit transport, snapshot callback and publication callback. To deploy the
new path, use `distributed_serve.py --config CONFIG --ready READY` with role
`replica`, `source`, or `worker`. The closed configuration contains:

- Common fields: `role`, `root`, `host`, `port`, `credentials`, `grants`.
- Credentials: `ca_file`, `certificate_file`, `key_file`.
- Grant: `certificate_sha256`, `operations`, `scopes`, `evidence_roots`.
- Replica: `member_id`, `membership`, `private_key_file`, `creation`.
- Membership: `authority_id`, `writer_key`, `member_keys`.
- Source: `source_database`, `scope`, `cell_id`, `cell_role`.
- Worker: `node_id`, `membership`, `replicas`, `source_endpoint`, `model`,
  `outbound_credentials`.

The replica signing key is an owner-only PEM file. `creation=genesis` is only for
an explicit new deployment; it does not erase a prior identity or restore a lost
database. Bind hosts are explicit and may be non-loopback. Model files remain
local to each worker. The ready receipt records process and boot identities,
without claiming hardware attestation.

`MeteredRPC` durably reserves each call before dispatch and retains both success
and failure costs across restart. Its byte figures are application payloads;
TCP/TLS overhead, partial failed transfers and energy are not measured. These
receipts must not be presented as complete physical network or monetary costs.

## Separate-runner experiment

`hepta-memory-multihost-relay.yml` runs two independent `ubuntu-24.04` jobs at one
exact source SHA. The protocol constant in `relay_protocol.py` is frozen before
execution. Each job acquires and verifies its own exact 135M base bytes.

The source job creates three fresh random synthetic facts, trains a rank-8
adapter for exactly 256 updates, and performs fresh adapter/base/shuffled reads.
It durably fences its old placement before publishing a signed checkpoint offer.
The target verifies the exact same-run Actions artifact, imports the three
checkpoint files and performs a fresh parameter read, followed by 32 serial
requests with fresh decoder processes. Raw outputs and per-request latency are
retained. The target receives no source database or fact table during inference.

Only after target reads finish does the source fulfill one explicit evidence-root
request and withdraw that source. The target observes the signed withdrawal,
rejects the stale checkpoint before model entry, and refuses the old signed cut
again in a new process using its durable local fence. The delayed evidence is
recognized as withdrawn and cannot become current support.

The authenticated Actions run/artifact is the trust bootstrap for the source key.
The helper never forwards the GitHub token to an artifact storage redirect. It
checks run SHA/attempt, an exact artifact name, ZIP digest when supplied, and an
exact single ZIP member. Signing keys stay outside uploaded evidence.

This is asynchronous artifact relay across runner environments. It is not a
direct cross-host mTLS trial, multi-host quorum trial, physical-machine
attestation, continuous-availability test, or instantaneous withdrawal guarantee
before delivery. Cold-worker load figures use one serial client and a delivered
source cut; they are not end-to-end distributed production service throughput.

The fixed gates test distinct boot/job identities, exact checkpoint identity,
raw output preservation, former-owner refusal, zero model entry on withdrawal
and restart replay, and source locality. Exact recall quality is reported
separately and never repairs or postprocesses a decoder answer. Full source,
target, base, transfer and checkpoint inventories retain physical copies.

## Verification

Install the existing pinned CPU model runtime and this directory's
`requirements.txt`, then run `bash scripts/memory_cell_distributed/run_tests.sh`.
Tests use actual SQLite transactions, signatures, TLS sockets and independent
replica processes. Structural owner callbacks are explicitly labeled and make
no model-quality claim. Run the existing network regression suite after changing
transport injection. Preserve unsuccessful attempts and their exact source pins.
