# HCSN PQ owner composition and cancellation qualification

This candidate continues `44e539313e0c54badb4b9b687425dd87ecba6e67`.
Results belong to the exact source and execution receipts retained for this
candidate. A successful configuration test is not a production deployment or
evidence that a learned candidate improves a task.

## Production configuration

On Linux the existing Agentd effect owner recognizes a distinct schema 3:

- `provider`: `hcsn_process_v1`.
- `authority_profile`: `production_ml_dsa65_v2`.
- `deployment`: schema 1, contract ID and authority epoch, provider scope,
  FinalUse scope digest, interpreter path and digest, repository root,
  supervisor digest, exact Python source manifest, durable store root and RPC
  deadline.
- `deployment_key` and `deployment_signature`: pinned ML-DSA-65 public trust
  and a signature over the domain `hepta.hcsn.deployment-contract.pq.v1\0`
  followed by the serialized typed deployment.
- `final_use`: pinned issuer ring, signed revocation distributor/ring/file,
  initial head, protected clock endpoint and independent frontier endpoint.

The interpreter/supervisor pins and all execution configuration are checked
before constructing the owner. Issuer, revocation, deployment, clock and
frontier roles must use distinct public keys. Clock and frontier are distinct
canonical external sockets. Their state must already exist; the loader never
initializes an external frontier from local state. A classical authority store
cannot be reopened as a PQ store. Schema 2 engineering registration remains
available only in the qualification test build. Selecting the production enum
with schema 2 is always rejected; the PQ owner requires schema 3.

Host configuration, signed feed and retained request reads use bounded private
descriptor observations on Linux. Symlinks, hardlinks, unsafe ownership/modes,
special files, growth and a replaced file identity are refused.

The signed source manifest covers every `.py` file recursively below
`qualification/hcsn` and `qualification/hcsn_training`, including test helpers,
and `qualification/__init__.py` if present. The native owner verifies the exact
inventory and file digests before opening authority and before each process
contact, including status queries. Missing, added, changed or aliased source
files refuse contact. The Python repository loader rejects sourceless bytecode,
extension modules and imports outside those source roots. These checks establish
the observed source snapshot; the deployment owner must still keep that snapshot
immutable throughout execution and qualify the installed interpreter/runtime.

## Actual dispatch boundary

1. The existing owner checks the scoped exact payload and reads an already
   durable terminal receipt before requiring a new freshness presentation.
2. A new effect authenticates the signed feed and grant, including expiry and
   epoch agreement, then enters the existing TaskFlow protocol.
3. The actual consumed claim is bound to the previously authenticated head
   after the store waits. The provider cannot substitute or mint a claim.
4. The existing active-effect fence protects the operation. It does not hold
   the owner mutex throughout the driver, so the final callback can safely
   reauthenticate the feed and recheck the original owner.
5. After request retention, pin checks, serialization and stdio preparation,
   the native supervisor checks the signed source inventory, protected time,
   authenticated signed feed and full external frontier immediately before
   spawning its RPC process.
   A newer signed head during an active effect refuses contact. No new nonce
   or replacement authority is created to recover that refusal.
6. Ambiguous contact still requires lookup of the same durable job. A status
   lookup reauthenticates the feed/frontier and rechecks expiry after trust I/O.
   Reconciliation still requires the current TaskFlow fence. Once that fence
   admits recovery, a locally durable terminal needs no further provider lookup.
   Opening a cold host still requires current external trust.

The additional `prepare_claim` driver hook can only reject or bind the existing
claim. A contact guard cannot bypass source pins, change the wire payload or
authorize a worker. The supervisor's default constructor remains a transport
primitive, with authorization supplied by its existing caller.

## Signed cancellation acceptance

`verify_cancel.py` prepares one fresh bounded CPU fixture and invokes the selected
native test `signed_authority_real_worker_cancel_cold_recovery`. Start and Cancel
have separate signed intents, grants and nonces. The fixture preserves deliberately
lost replies, captures the original live process incarnation, cancels that exact
job, and reconciles both effects in a fresh native process.

The raw terminal must confirm the owned worker's SIGKILL exit. Native and Python
observers independently check that the original PID/boot/start-tick incarnation
is no longer live. A receipt alone is insufficient. The final SQLite receipts
are read back exactly, while the original indeterminate observations remain.
Recovery uses status RPCs and never repeats a mutating Start or Cancel.

This fixture can cancel during Python/model import. It reports
`optimizer_entry_proven=false`; process termination is not evidence that a
gradient update was interrupted. A, fixed-grid B and physical-time B each use a
separate bounded acceptance identity. They are unrelated to the existing CUDA
science campaign and do not restart or extend its budget.

Both cancellation wrappers use `cancellation_fixture.py` and retain a separate
one-step proposal through the actual worker admission path before dispatch.
The cancellation process keeps the 64-step ceiling. B uses an explicitly bound
8-bin spatial grid to fit a longer real trace inside the unchanged 1,048,576
working-element and 24-KiB host-wire limits. This fixture is process acceptance,
not a numerical-quality comparison. The default 32-bin graph and checkpoint
representation stays byte-canonical to its historical form: the shared
`graph_spec_dict` omits only the default spatial field. Nondefault resolution
changes graph/model/checkpoint identity and is preserved during grid-to-age
migration; the separate temporal profile retains its original meaning.

## Real worker through the PQ Agentd host

`verify_pq_host.py` invokes the exact ignored Agentd lib test
`automation_effect_host::hcsn_pq::tests::real_worker::pq_host_real_worker_cancel_cold_recovery`.
It opens the actual schema 3 owner, authenticates a deployment signed with a
local ML-DSA test key, uses separately keyed signed clock/frontier services,
and sends distinct Start/Cancel grants through `host.execute` to the real CPU
worker. A fresh native process reopens the owner and SQLite to reconcile the
same effects and read the exact settled receipts.

This acceptance preserves the actual initial responses and reports
`lost_replies_injected=false`. Independent kernel observations bind the original
live worker to its confirmed exit. The final terminal-read check removes the
feed and advances protected time only after recovery has settled both effects.
It proves the already-open owner's durable-read boundary; cold construction
still requires live trust. The fixture exercises host registration, but does
not boot an Agentd daemon, traverse AuthBus ingress, establish independent key
custody or deploy production services.

## Imported code and qualification boundary

The native crypto/FinalUse support is a focused port of the published PQ lineage
at `dd32a0d510cbeb3dfed0554d982c75168a59d95d`, with reviewed local source from
`be6f772a82d5a5057901dee5701e94f02980c4c5` for the shared owner gate. That latter
identity was locally available and was not claimed to be a published upstream
commit. Unrelated Windows owners, release/learning endpoint extensions and the
rest of the diverged branch are not imported. The new full-frontier and
post-I/O expiry checks are separately identified changes.

The original caller checker is unchanged. Its exact caller inventory now covers
the imported PQ constructors and the private owner. Its source-hash fields are
checked separately by the dedicated HCSN workflow; the baseline checker itself
does not enforce those fields.

The normal Agentd tests use real ML-DSA verification, local test-only trust
services and a pinned process peer. The separately invoked acceptance above
connects that same PQ owner to the actual numerical worker. Ordinary AuthBus
ingress on this baseline remains classical;
an end-to-end PQ Agentd ingress claim requires that distinct integration.
Production key custody, independently deployed trust services, physical-host
registration, real model evaluation/adoption, NDU benefit and energy qualification
remain separate acceptance requirements. No production service is switched by
these tests.
