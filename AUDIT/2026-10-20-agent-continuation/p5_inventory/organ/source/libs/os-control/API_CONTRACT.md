# A03 host-model API contract

`os-control` is the Rust control state core for HOS2 0.3. Runtime tests are
host-model evidence. The default `std` backend and experimental
`--no-default-features --features portable-spin` backend share the same
state transitions; the latter uses `core`/`alloc` and compiles for
`x86_64-unknown-none`. It requires an allocator and pointer-width atomics.
Neither backend implements an ioctl, a kernel scheduler, credentials,
copyin/copyout, crash durability, or a second Hepta database. The existing
Hepta owner remains responsible for persistent logical operation identity `K`.
This crate only models the boot-local delivery identity `D`:

```text
D = (BootId, CapSpaceId, sequence)
```

The portable spin mutex is **not a validated Asterinas lock adapter**.
It does not mask IRQs or disable preemption. Same-CPU reentry can deadlock.
The native delivery table prepares storage outside its internal locks;
the host ResourceDomain still has allocating mutation paths. A05/A06 can
instantiate `ControlCoreWith<TheirBackend>` through the public `LockBackend`
and `ControlMutex` contracts, without editing private source. They must validate
that backend, allocator use and their actual owner callbacks against their
kernel lock discipline before production use. This build option
does not establish G1/G2, scheduler enforcement, or kernel integration.

The HOS2 wire layout remains owned by A02 and is not represented by a Rust
memory-layout cast here.

For A05 conversion, `DeliveryStatus::hos2_code` and
`DeliveryState::hos2_code` expose the fixed numeric HOS2 0.3 values without a
dependency on the wire crate. `ParentLimit` maps to wire `Conflict` because
HOS2 0.3 has no separate parent-constraint status. The fallible
`DeliveryObservation::hos2_saved_status_code()` returns `Some(0)` only
for a consistent nonterminal observation with no saved outcome or resource
metadata, `Some(status)` for a terminal whose status and CAS metadata agree,
and `None` for any malformed pair, missing/forged success receipt,
erroneous metadata, invalid D sequence, or terminal `OutOfOrder`/`Retired`.
The last two statuses describe admission before a reservation; they cannot
be saved execution outcomes. A real `DeliveryState::Retired` still encodes
normally with no saved outcome. A05 must refuse to serialize
`None` rather than default it to Ok. A02 independently validates the
actual HOS2 byte layout and payload.

## A05: kernel ioctl and CapSpace

For a native kernel namespace, the constructors and methods below also exist
on `ControlCoreWith<B: LockBackend>`. The existing `ControlCore`, `ReserveToken`,
`DeliveryView`, `OriginalOwnerAuthority` and weak-handle names are concrete
aliases for `DefaultLockBackend`, preserving existing constructor inference.
The corresponding `*With<B>` handles retain the same backend type throughout
reservation, execution, history observation and retirement. Backend types do
not authenticate callers; exact namespace instance checks still apply.

`ReserveAttempt` is a public re-export of the actual
`ReserveAttemptWith<B = DefaultLockBackend>` enum, so either name supports
variant imports such as `use ReserveAttempt::{Existing, Reserved}`. Method
results and typed default values preserve the backend identity. A standalone
`Existing(observation)` carries no token from which Rust can infer B: supply
an expected type, for example `let attempt: ReserveAttempt =
ReserveAttempt::Existing(observation)`. This is a source-inference change in
the experimental generic Rust API, not a HOS2 wire change or a claim of full
source compatibility for untyped enum construction.

1. Construct `ControlCore::try_with_capacity` after trusted boot identity and
   CapSpace binding, or `with_capacity_for_owner` to also mint the non-Clone
   `OriginalOwnerAuthority` for the authenticated original Hepta owner.
   The HOS2 maximum/default is 1024 non-retired writes.
2. Resolve the existing kernel resource owner and pin its actual `Arc` with
   `NativeTarget::from_owner(owner, domain_id, stable_object_id)`. Snapshot
   the authenticated publisher, grant epoch and immediate-parent-to-root
   epoch chain with `NativeGrant::from_owner`. Build a
   `NativeDeliveryRequest::from_wire` with sequence, expected revision, cap and
   exact nonzero HOS2 target slot/generation. Stable target identity, grant
   epoch/ancestry and optional payload digest are also bound. The unbound
   `DeliveryRequest::new` constructor and `ResourceDomain`/`Grant` route are
   host fixtures; native admission requires no shadow ResourceDomain.
   If the original owner uses `ManagementGrantState`, obtain its immutable
   snapshot and use `NativeGrant::from_management(target, snapshot, ancestors)`.
   The library checks target IDs and additionally binds the full delegation
   instance/terms in D. This does not create another authority registry.
3. Call `reserve_native`. Sequence allocation is global across host and native
   requests and all targets. A second
   target, cap, expected revision, grant epoch, or payload digest for the same
   D is `Conflict`; a duplicate pending D is `Busy`; a duplicate terminal D
   cannot allocate a new effect. `reserve_native_or_get` is the native
   copyout-retry helper (`reserve_or_get` serves host requests).
4. Use `execute_native_reserved::<ActualOwner, _>(token, publisher, callback)`
   for native A05/A06 mutation under the reserved entry's independent
   execution gate. Its `NativeExecution` context borrows the actual pinned
   owner and saved full ancestor snapshot; do not re-resolve a handle or use
   a fresh out-of-band grant to select the execution context. The callback checks real grant,
   lease/epoch, target, CAS and settled usage under its resource lock, then
   returns a `PublishOutcome`. `commit` exercises this same seam with the
   host ResourceDomain only; `commit` and the generic `execute_reserved`
   reject native tokens without executing or
   terminalizing them. `publish` is a reconciliation entry after an effect
   has already been safely fenced/established by the trusted adapter.
   Tokens are instance-bound, so colliding identity bytes do not grant rights.
5. Create an exact `DeliveryView` for history observation. Query is read-only;
   it never grants execution. `DeliveryState::Reserved` is pending,
   `NotSeen` is unknown in a live namespace, and `HistoryLost` is an explicit
   loss of proof. `Retired` is a permanent no-replay tombstone.

The kernel must add real process-start/exec-epoch/session credentials around
this API. Possession of a host-model token is not a kernel credential.

The native constructors are trusted resolver value seams, not authentication.
They retain the actual owner allocation and stable identity without storing
another budget, revision, runtime counter, scheduler or persistent ledger.
Rewrapping the same owner `Arc` dedupes; equal IDs on different allocations
conflict. Host and native requests also conflict under one D even if their
public binding bytes match. Complete ancestor snapshots participate in replay
comparison. The typed execution entry downcasts only the reservation-pinned
owner to the adapter's concrete Rust type and passes a borrowed context. A
wrong type or host/native entry mismatch returns `InvalidRequest` before the
Executing sentinel; the pending D remains available for a correct executor.
The library never calls owner policy itself. The adapter must check the
snapshot against that owner's **current** grant/ancestor/lease state under
its own mutation lock; possession of the snapshot is not authorization.

## A06: CPU scheduler and ResourceDomain

For native use, keep A06's existing owner and call `execute_native_reserved` with a
callback that settles runtime and checks current grant/ancestor epochs,
lease, revision CAS and parent constraints under that owner's actual mutation
lock. Return `PublishOutcome::Success` carrying the exact receipt fields,
or `PublishOutcome::Failure` with the immutable refusal. Revoke and this
commit must share that lock. The synthetic native-owner tests demonstrate
this API shape, not actual A06 integration.

The A06 controller now on main is private to its cgroup module. A06 must
provide an owner-module adapter that invokes the typed entry with its actual
`SubController<CpuController>` type, then takes the existing mutation lock
inside the callback (execution gate before resource lock). A05
passes token/publisher to that adapter; it must not pin a Process or a new
wrapper merely to expose a public type instead of the actual resource owner.

The host `ResourceDomain` exposes stable `ResourceDomainId` and `StableObjectId`, a
revision-CAS budget update, `try_usage`, `revoke`, explicit `user_paused` state,
and the host-model `charge_cpu` primitive. `install_budget_for_host_model` is
the seam to replace with the scheduler's mutation path.

Invariants:

- period is exactly `CPU_PERIOD_NS` (100 ms); cap is within the period;
- expected revision must match and successful updates increment revision;
- cumulative and current-window CPU usage are retained across cap updates;
- successful sampling, CAS and charging advance one shared family BOOTTIME
  floor; rejected operations do not move it, and legacy `usage` clamps to it;
- a same-value update does not reset usage or create budget;
- child cap cannot exceed the parent cap, and parent cap cannot be lowered
  below any registered child cap;
- revoke and commit linearize on the same domain mutation gate; a revoke that
  wins first rejects the grant, while an already admitted commit remains
  terminally successful;
- cap zero is a budget value and never implies `user_paused`.

`charge_cpu` is still a host accounting model. Real tick accounting,
runqueue lock order, timer wakeup, and parent scheduling remain A06/kernel
work.

### Metadata beside the actual CPU owner

`NativeResourceState` is a non-Clone, allocation-free identity and revision
primitive for A06's original owner mutation lock. It stores only trusted domain
and stable-object IDs, revision (initially one) and an irreversible fence.
It contains no budget, usage, parent table, clock, grant registry or ledger.
Keep it beside the sole existing `CpuMax` under the same lock; retain the
actual `SubController<CpuController>` allocation as the native target.

`NativeResourceUpdate::from(binding)` extracts the resource fields. After
current authority, ancestors, parent policy and settled runtime have been
checked, call `apply(update, effective_ns, consumed_ns, &mut mutation)`.
The primitive validates identity, revision CAS, the HOS2 period/cap and every
saved receipt field before invoking the borrowed, infallible mutation once.
Its private valid receipt converts with `into_publish_outcome()` without a
fallible check after the effect. The caller supplies trusted BOOTTIME and
rollback prevention; the primitive does not establish another time domain.

Every configuration writer must share that metadata. Linux `cpu.max` and
lifecycle configuration use `apply_owner_configuration(&mut mutation)` under
the same lock, advancing the same checked revision without inventing D or a
publisher. This entry permits the actual owner's non-HOS2 periods and unlimited
quota after its existing policy validation. A06 must normalize or refuse
incompatible parent periods; comparing raw quota values from different periods
does not establish a parent constraint. Neither entry resets consumed runtime.

A callback panic leaves the metadata permanently `Indeterminate`, blocking
both native and ordinary-owner mutation attempts even after host mutex poison
recovery. There is no reset API or inference that the effect did not occur.
`invalidate()` permanently closes a known detached owner without changing its
budget, accounting, revision or saved D results; invalidation preserves an
existing indeterminate fence. These states do not represent user pause or
management-grant revocation.

A06's subtree-control replacement can publish a new controller allocation.
Its adapter must invalidate the old metadata under the old mutation lock as
part of the actual replacement/commit sequence, or prove that the pinned owner
is still current. An Arc pin alone cannot prove scheduler membership. A new
instance receives fresh trusted identity metadata; do not reset a live instance.
The callback is borrowed so this primitive does not destroy its captures.
Prepare owning captures before taking the owner lock and destroy them after
unlocking, or use callbacks borrowing only the owner's fields.

This is executable host-tested Rust for embedding, not an Asterinas adapter.
The current kernel has QueryAbi and the real A06 CPU controller, but no consumer
of this metadata primitive or mutating HOS2 delivery core is established here.

## A07: Hepta persistent confirmation and retirement

A07 records `K` and its association with this crate's D in the existing Hepta
owner ledger. A03 does not create, reconcile, or persist K. After the owner
has durably confirmed a contiguous terminal prefix, it supplies the digest to
`OriginalOwnerAuthority::history_ack`, which stamps a private namespace-bound
receipt tag, then calls `retire_through(&owner_view, ack,
&original_owner_authority)`. `HistoryAck::from_owner_receipt` remains a
value-only parser for untrusted evidence and can never authorize retirement.
The instance tag is allocated once from a process-local non-reusing counter;
exhaustion rejects namespace creation. It is not an allocation address, so a
copied ACK cannot authenticate a replacement namespace after address reuse.
The namespace validates the private receipt tag, instance, generation, exact
boot/space, owner binding, contiguous terminal state, and monotonic frontier.
Retiring a prefix releases result slots but keeps the frontier so a
late sequence can only return `Retired`.

`LogicalOperationId` and `OperationBinding` are value-only handoff types for
the K↔D association. They do not create a K index, persistence record, or
execution authority; A07 remains the owner of the existing Hepta K ledger.

`lose_history` models a reboot or namespace-loss boundary. Old views observe
`HistoryLost`, old reserved tokens are fenced, and a new `ControlCore` must
use a new boot/CapSpace identity. This is not a persistence implementation.

## Lock and result invariants

The namespace preallocates a bounded contiguous ring at bootstrap. Ring
reservation failure returns `ResourceExhausted`. A new delivery first checks
admission, releases the table lock to allocate its result slot, then checks
admission again before inserting. A racing loser releases its candidate after
unlocking. Existing D retries, full-window refusals and history reads do not
allocate result slots or grow the table. The invariant is always
`window_len = next_sequence - retired_through - 1` until history is lost;
an index into recycled storage never supplies a new sequence identity.

The namespace mutex reserves a slot and its canonical request before any
resource mutation. Each slot has a separate execution gate and short-lived
state mutex. After taking the execution gate, commit/publish briefly validate
namespace liveness, release the table mutex and use the state mutex to inspect
or mark admission. The external callback holds only the execution gate while
entering its resource mutation lock. No namespace-table operation waits for
that execution gate. Query/retire read only the short state mutex, never the
resource mutation gate; an Executing slot is observable as Reserved. Complete
terminal payload and state are published together, and never regress.

Namespace loss serializes on an independent loss gate: set closing under the
table mutex, release it, wait/fence each slot execution gate, then mark history
lost and clear the table. Closing rejects reserve/execute/publish/retire with
HistoryLost, but existing views can still query pending or terminal results.
An old pending entry may become HistoryLost as it is fenced; complete history
loss is published only after admitted callbacks have finished.

Retirement advances its frontier and removes the terminal prefix atomically
under the table mutex, then releases that mutex before dropping reclaimed
requests/owner pins. Loss similarly publishes loss and empties the table,
then releases both the table and loss gates before destroying owners. An
owner destructor may therefore reenter namespace observation or loss; it is
never invoked by these reclamation paths while their internal locks are held.

Retirement first validates the prefix under the table lock. Duplicate, invalid
and pending acknowledgements return without allocating. It prepares an exactly
bounded reclamation buffer outside the lock, then validates again before
removing entries; allocation failure returns `ResourceExhausted` without
advancing the frontier. Namespace loss closes admission and walks the stable sequence range,
taking only a short table lock to pin each slot before waiting on its execution
gate. It needs no scratch allocation. For native deliveries with a compliant
nonallocating callback, these paths neither allocate nor free heap storage
under an internal table, slot-state, execution or loss lock. Allocations still
occur at bootstrap, before new-slot admission and before retirement. This is
not general OOM recovery: `Arc` creation and external owners remain subject to
the allocator's failure policy. The host ResourceDomain and actual kernel
lock/IRQ adapters are outside this native namespace guarantee.

The Rust tests under `tests/control` are host-model evidence only. They do not
claim native kernel capability, real copyout fault handling, power-loss
durability, scheduler correctness, or A05/A06 integration.

## A03 hardening: namespace loss and view rights

The namespace owns the canonical request **including its publisher**. A
duplicate D from another authorized principal conflicts even when target,
period, revision, cap and digest happen to match.

An observation-only `delivery_view()` may query but cannot retire. The
`delivery_view_for(owner)` host-model view must be minted *only after* A05
verifies an actual history.ack capability, and A07 must validate that the
owner's receipt represents a durable contiguous confirmation. The
`OwnerReceipt` digest is opaque model evidence, **not a cryptographic
signature**. A caller-created receipt is intentionally untrusted; only the
non-Clone original-owner authority can stamp the private namespace-bound tag
required by `retire_through`. The host model still does not implement A07's
persistent K ledger or fsync proof.

`lose_history` fences reserved result slots under the per-slot execution gate
that serializes `commit` and `publish`, without holding the namespace table.
An already admitted callback completes before loss obtains that gate;
a token not yet admitted returns
`HistoryLost` with no new mutation. Any effect handed off to an *external*
kernel executor before `publish` still requires A05's own fencing and
effect-journal discipline: the host model cannot cancel arbitrary external
effects or prove power-loss persistence.

## A06 time and parent hierarchy hardening (host model)

Child registration now takes the same shared resource mutation gate as a
concurrent parent cap reduction. Direct sibling and ancestor ID collisions
are rejected; the kernel integration must guarantee unique IDs across roots
and unrelated branches.

`try_usage(boottime_ns)`, `charge_cpu(delta, now)` and budget CAS reject
BOOTTIME rollback. Compatibility `usage` clamps old timestamps to the last
observed time and returns the effective sample, never a newly credited
earlier window. The budget CAS advances a 100ms window only after a real
period boundary. Reactivation fails closed on epoch overflow.

A06 remains responsible for runtime settlement, exact boundary-crossing
CPU slicing, all scheduler classes, parent gate integration, IRQ lock order
and timer wakeups. `charge_cpu` is **host-only** single-window accounting,
not native scheduler enforcement.

## Hierarchy linearization and identity collisions

Child creation shares the root family's mutation gate with parent cap changes.
Duplicate sibling ResourceDomain IDs or an ID equal to an ancestor are rejected
rather than overwriting the parent's child-cap registry. Installing a budget
in a later 100ms period advances window accounting at apply time; same-window
updates retain already consumed runtime even when the cap value is unchanged.

## Original-owner history retirement authority

For namespaces with retirement, A05 trusted bootstrap creates the pair from
`ControlCore::with_original_owner` or `with_capacity_for_owner`.
The non-Clone `OriginalOwnerAuthority` binds the original owner to the
specific in-memory namespace instance and its generation. The
`retire_through(&view, ack, &authority)` API rejects arbitrary observer
views, invented owner receipts, foreign same-byte namespaces and stale
generations. A07 must *separately* validate its existing durable K ledger
and fsync before invoking retirement; no new persistent database is created.

## Ancestor revocation

Child grant issuance and child budget CAS both check the liveness of every
ResourceDomain ancestor under the shared family mutation gate. If any
ancestor revoke precedes admission, child mutation publishes terminal
`Revoked`; if the child mutation wins, its already published result remains
immutable after ancestor revoke. The real A05/A06 kernel must bind this to
its actual grant epoch, capability lifetime and scheduler domain lock order.

## Family-wide resource identity retention

ResourceDomain family members now share a mutation-gate-protected set of
stable domain IDs and stable object IDs. A child cannot register a duplicate
ID **anywhere in its root family**, including a cousin in another subtree.
IDs are retained for the life of the family instead of being reused after a
handle drops. This is a bounded-by-object-creation **host-model** registry,
not a duplicate Hepta ledger or a new global kernel object database. The
actual kernel must use its preexisting stable object owner/registry to enforce
uniqueness **across distinct root families** and to bound/retire the registry
safely during namespace destruction. The family gate serializes simultaneous
cousin registration and parent budget changes.

## Atomic host ancestry charging

`charge_cpu(delta_ns, now_ns)` now uses a two-phase, family-gate-serialized
transaction: stage current-window, cumulative and event-sequence changes
against **every ancestor**, rejecting overflow, revoked/exhausted ancestor or
clock rollback before touching any node; then publish the validated updates.
This closes an observable failure mode where a rejected parent's quota left a
child window/time advanced, blocking a legitimate earlier later retry and
claiming false progress. The 3-level rejection and 64-thread sibling quota
races are in Rust tests. Unlike a real scheduler, this compatibility host
method places the entire delta in the window of `now_ns`, so A06 still needs
exact CPU interval slicing at true boundary-crossing runtime settlement.

## Instance-bound D target and ancestor creation fence

Global D replay compares both canonical resource identity fields and the
original in-memory ResourceDomain instance. An independently created root
with colliding public identity bytes conflicts rather than retrieving the
other object's terminal result. The bounded slot holds the instance until
retirement. Descendant creation checks every ancestor's liveness; a revoked
grandparent cannot be bypassed through a still-live parent. A05 must still
guarantee global stable IDs for real kernel resources across distinct roots.

## Exact cross-period host model seam for A06

`ResourceDomain::charge_interval_for_host_model(start_ns, end_ns)` accepts a
strict non-empty monotonic CPU execution span `[start, end)`, correctly
splits it at fixed 100ms boundaries, checks the consumed first window, any
complete intermediate windows, and the final partial window against the
resource and every ancestor. The entire interval is atomic: invalid,
clock-reversed, over-limit or overflowing intervals change no resource,
cumulative accounting, event counter or BOOTTIME floor. A full intermediate
window can only be consumed at a full-period cap, so no unused quota credit
is carried into the next window. Exact endpoint boundaries and near-u64-max
arithmetic are tested. The older `charge_cpu(delta, now)` method remains for
legacy caller compatibility but **does not slice intervals**. Neither one is
actual scheduler enforcement; A06 must settle real per-CPU runtime before
calling into a shared resource gate and implement timer preemption/recovery.

## Pre-reservation validation

A05 must parse/check the HOS2 transport and static InstallBudget payload
before reserving D. The host core also rejects invalid expected revision
(0 or u64::MAX), non-100ms period, or out-of-range cap via
`DeliveryError::InvalidRequest`, without consuming the next sequence or
allocating a result slot. Post-reservation grant/CAS/parent/clock denials
are stored as immutable terminal outcomes. A05 maps structural validation
to its protocol error path, not to an invented terminal effect.

## Bounded resource-family identity namespace

The host-model family ID and stable-object-ID tombstone registry now has an
explicit default limit of `DEFAULT_FAMILY_ID_CAPACITY = 65_536` including
the root. Attempts to create another domain fail with `ResourceError::Exhausted`
without overwriting an existing child or consuming an identity. For adversarial
tests, `ResourceDomain::root_with_capacity_for_host_model(..., family_capacity)`
can use a tiny limit. Dropped resource handles do not revive a previously
used stable ID: unlike transient slot numbers, a stable identity is never
silently reassigned. **This is only a host-model lifetime bound**; an actual
kernel requires bounded residual-domain reclamation and a globally scoped
object-ID registry across roots. A03 does not implement a new persistent
ledger or substitute its in-memory registry for A05/A06's lifecycle owner.

## Ancestor authorization epoch / reactivation ABA fencing

A grant captures the immutable epoch chain from its ResourceDomain through
its ancestors at issuance. A revoke followed by trusted reactivation of any
ancestor changes that chain, so an *old child grant remains invalid* even if
the ancestor is now alive again and its numeric CPU cap is unchanged.
`install_budget_for_host_model` compares each saved ancestor epoch under
the shared mutation gate and publishes a terminal `Revoked` result on stale
D submission. The reservation slot additionally binds the saved epoch chain:
a fresh grant cannot claim the *same* previously reserved D even when all
public HOS2 request bytes are equal; it returns `Conflict`. A genuinely new
post-recovery action must use a new D and fresh Hepta K authorization as
appropriate. No new wire field or independent K ledger is introduced.

## A02 wire-success equivalence (cross-crate hardening)

The independent A02 HOS2 decoder rejects an allegedly successful
`QueryDelivery` result when `consumed_ns > effective_ns % CPU_PERIOD_NS`,
even when object identity and revision CAS metadata match. A03 now applies
the same fail-closed predicate in both
`DeliveryObservation::hos2_saved_status_code() -> Option<u16>` and external
`publish(..., PublishOutcome::Success)`. A05 must reject `None`, never
substitute a success code.

`ResourceDomain::apply_budget` also preflights the current period elapsed
time before any revision/window mutation. If the simplified legacy host
`charge_cpu` has produced impossible running-time accounting, the reserved
D publishes an immutable `Indeterminate` refusal rather than a wire-invalid
success. It does not refund prior consumption, advance CAS or turn the
original D into a later success. A subsequent **new** D may be evaluated at
a later consistent sample. A06 must supply settled real runtime in the
actual kernel and A07 must preserve original K history.

## Pinned durable Hepta K identity (A07 handoff)

The pinned real `hepta-private-ci@f8c9419df6ddeb36ff8b522a50219981fb8d9345`
`codex-rs/hepta-operations/src/durable_model.rs::OperationIntentV1`
has `scope_id: StableId` and `operation_id: StableId` as the persistent
operation identity. The production `durable_store.rs` loads and tombstones
rows with `WHERE scope_id = ? AND operation_id = ?`; `payload_digest`,
`expected_predecessor`, and `owner_generation` are **not part of K's
lookup key** (the owner still checks semantic digests and fences generations).
This is distinct from the non-durable *reference* `OperationKey` type.

A03 `LogicalOperationId::new(scope_id, operation_id)` therefore stores the
entire independent StableId strings losslessly (each 1..=128 ASCII bytes,
letters/digits/`.`/`_`/`-`/`:`) rather than truncating them into two
16-byte integers or hashing away collisions. It is a value-only carrier,
not an owner ledger and not authority to dispatch. `OperationBinding(K,D)`
continues to tie it to one boot-local kernel delivery without ever
replacing the original owner. Public namespace and D fields are
constructor-validated and accessed read-only; neither value proves
kernel boot entropy, credentials, or the rights of its caller.

## Publisher immutability and revoked-vs-exhausted status

The host `Grant.principal` value is no longer externally mutable; callers
can only inspect `Grant::principal()`. A05 must still authenticate the
publisher and authorize the grant against the actual kernel session.
Host `charge_cpu` and `charge_interval_for_host_model` now return
`ResourceError::Revoked` for a revoked leaf or ancestor, reserving
`Exhausted` for genuine CPU cap exhaustion. Both failures are atomic and
leave all cumulative usage/event counters unchanged.

## Fail-closed namespace window bootstrap

For HOS2 0.3 the maximum in-memory unretired delivery window is 1024.
`ControlCore::try_with_capacity(boot, space, capacity)` rejects zero
identities and capacities outside `1..=DEFAULT_WINDOW_CAPACITY` before
creating a namespace, returning `InvalidIdentity` or `InvalidCapacity`.
The owner-bearing `with_capacity_for_owner` now propagates the same
validation instead of panicking. Legacy `with_capacity` remains a trusted
compatibility constructor; configurable A05 callers must use the fallible
entry point. The reservation path still returns `ResourceExhausted`
without consuming the next D when the valid bounded window fills.

## End-of-range rollover (host model)

The final allowed write D is `sequence=u64::MAX-1`, after which
`next_sequence=u64::MAX` is a non-writeable exhausted sentinel and must
never wrap to 1. Retiring the last terminal result preserves that frontier.
The last legal revision CAS is `previous=u64::MAX-1` to
`saved_revision=u64::MAX`, whose terminal outcome remains immutable on
retry; attempts to propose `expected_revision=u64::MAX` are structurally
invalid and do not consume another D. Unit tests construct synthetic
late-life private frontiers to verify the arithmetic without simulating
2^64 operations or pretending to prove real kernel persistence.

## A02 independent codec compatibility tests (A03 dev-only dependency)

The A03 Cargo crate has a **dev-only path dependency** on A02's separately
owned `hos2-os-abi` no_std codec. New Rust integration tests in
`tests/control/control_conformance.rs` convert actual A03 Reserved,
Terminal/Ok, Terminal/Revoked, NotSeen, Retired and HistoryLost observations
to A02's typed `QueryDeliveryResponse` and require successful
`encode_response` + `decode_response`. The negative test demonstrates
that both A03's fallible status conversion and A02's *independent* encoder
reject an impossible elapsed-CPU success; zero previous revision is also
rejected. This adds no wire layout of A03's own, no generated golden edits,
and no production dependency on the wire crate. The lockfile pins the dev
dependency and optional spin backend. Exact-head Cargo execution is still required; test source
presence is not a passed result.

## A02 history-sequence MAX compatibility

HOS2 InstallBudget uses strictly executable D sequences
`1..=u64::MAX-1`; write `u64::MAX` is permanently reserved as the
non-executable next-sequence sentinel and never allocates a slot. The
**separate history QueryDelivery/RetireThrough wire payload** permits any
nonzero sequence, including `u64::MAX`. A read-only QueryDelivery for
this sentinel returns `NotSeen` in a live namespace or `HistoryLost`
after namespace loss, *not* a terminal/retired result. A03's fallible
wire observation converter permits these two states at MAX but refuses
to serialize forged Reserved/Terminal/Retired MAX observations. A02's
independent no_std codec is the test oracle for the MAX history response.

## Executable bounded-window invariant audit (host only)

`ControlCore::validate_invariants_for_host_model()` inspects the live
namespace and each result slot with the same namespace->slot lock order as
query/retire. It checks monotonic `next_sequence` and `retired_through`,
the **complete contiguous** unretired window (no missing sequence hidden by
result reclamation), bounded slot count, publisher/request binding, terminal
HOS2 result metadata shape, and absence of fenced slots in a still-live
namespace. After explicit history loss, no slots may remain. Errors use
`DeliveryInvariantError`; the check never creates new authority, touches a
Hepta K ledger, or performs a resource effect.

New Rust tests exercise the diagnostic across a permanently pending first
sequence + exhausted eight-slot window, its eventual contiguous retirement,
a 10,000-delivery bounded sequence, and an observer concurrently auditing
512 producer CAS commits/retirements. This is **O(window)** host diagnostic
work, not an IRQ-safe or production scheduler operation and not loom proof.

## Pre-reservation status and invalid publisher classification

The HOS2 `OutOfOrder` and `Retired` status values are decisions by the
CapSpace namespace **before** a new sequence is reserved; a writer must not
store either as a fabricated terminal publication after reservation.
`PublishOutcome::Failure` now rejects those two values (and `Ok`), leaving
the slot `Reserved` for a legitimate terminal result. When a real terminal
is already committed, subsequent publisher calls only re-observe the exact
immutable original result. Zero publisher IDs return `InvalidIdentity`
without consuming a sequence, separate from invalid sequence parsing.
`Busy` remains eligible as a saved semantic refusal for integrations
where an already-reserved resource mutation has a terminal busy result.

## Ancestor BOOTTIME floor

A03's ResourceDomain ancestry shares one boot-local monotonic timebase.
A newly created child inherits its parent's last observed BOOTTIME and
current window start, **without inheriting CPU consumption or credit**.
Budget CAS rejects `now_ns` older than *any* ancestor's last observed
sample under the family mutation gate, even if the child itself has not
observed that later time. This prevents stale queued policy updates from
committing a retroactive effective timestamp. The check is host-model
only: A06 must sample and settle real boot-clock time atomically in the
actual scheduler.

## ReadUsage elapsed-time fail-closed boundary (A00 #74 integrated)

The A02 no_std codec independently rejects a successful ReadUsage frame
with `window_consumed_ns > sample_boottime_ns - window_start_ns`. Because
A03's simplified `charge_cpu` point helper is a **host model** that can
temporarily record physically impossible consumption, the A05-facing
`ResourceDomain::try_usage(now_ns)` now validates the current-window
elapsed-time bound under the family mutex before changing any sampled time
or rolling its window. It returns `ResourceError::InconsistentAccounting`
on failure, not an apparently valid HOS2 response. The legacy infallible
`usage` remains strictly a local diagnostic; **A05 must never use it for
wire ReadUsage**. Negative Rust tests reject the impossible host sample,
preserve a recoverable later sample and verify A02's *independent*
encoder rejects it. No A02 wire or Hepta durable store is changed.

## Exact HOS2 target handle bytes belong in canonical D

The published HOS2 request header carries both `target_slot:u64` and
`target_generation:u64`. These bytes were previously absent from the A03
`RequestBinding`: two requests using different handle aliases (or a slot
reused with a new generation) but resolving to the same stable ResourceDomain
could incorrectly dedupe under one D. A03 now binds **both** fields into
the global reservation fingerprint.

A05 **must** construct genuine native InstallBudget requests using
`NativeDeliveryRequest::from_wire(sequence, grant, expected_revision, cap_ns,
target_slot, target_generation)`, with nonzero slot and generation obtained
from a validated original HOS2 request header after stable object/capability
resolution. Host fixtures use `DeliveryRequest::from_wire` or its
`with_wire_target(slot, generation)` structural validator. The legacy
four-argument host `new` leaves
both fields zero **only for host-only model fixtures**; no real kernel
adapter may treat that sentinel as a valid HOS2 management handle.

Tests check same-D exact-handle idempotency versus different slot,
recycled generation, and structural-zero denial without consuming D. This
does not itself implement A05's FD/session validation, generation security
or kernel handle lifetime rules.

## New descendant's full ancestry BOOTTIME floor

A ResourceDomain created below a stale intermediate parent derives its initial
monotonic BOOTTIME floor from the **maximum sampled time of every ancestor**
under the family's existing mutation gate, not just the immediate parent.
It derives the 100ms window start from that maximum, but inherits **zero**
CPU consumption and no extra budget credit. Thus a child born after its
root's newer sample cannot accept a retroactive usage read or budget CAS.
A three-level Rust negative test covers root sampled in period 3, parent
sampled only in period 1, new child creation, stale rollback rejection,
future CAS, and retained zero usage. This is still host-model semantics;
A06 owns the actual in-kernel clock and scheduler admission.

### Concurrent registration versus ancestor sample

A 64-run host test deliberately races a grandchild registration with a
newer root BOOTTIME sample. The family mutation gate permits either
serial order: a child created first starts at the old floor, while a
child created second inherits the new root time. Once both complete,
**neither** schedule can commit a descendant CAS dated before the
root's newer sample. CPU cumulative usage remains zero in both cases.
This is an interleaving stress regression, not loom state-space coverage
or a real Asterinas runqueue/IRQ memory-order proof.

## Executable invariant auditor corruption-detection regressions

The host-only `validate_invariants_for_host_model()` now also checks
the exact HOS2 wire handle pair (both zero only in explicit host fixtures,
otherwise both nonzero) and that the canonical binding matches the complete
retained host/native request. It obtains locks in namespace -> result slot
order and never enters an external owner's policy or resource mutation gate.
Native identity assignment remains the trusted resolver's responsibility.

Two internal Rust unit tests deliberately corrupt otherwise private
namespace fixtures to prove that the auditor **rejects**, rather than
silently blessing, a partial wire handle pair, forged stable target,
impossible terminal success, fenced live slot, retained slots after
history loss, and a missing unretired sequence. The corruption hooks
exist only under `#[cfg(test)]`; normal callers still cannot mutate
the private reservation table or result slot. This is not an IRQ-safe
kernel invariant checker or comprehensive state-space proof.

## A05 ReadUsage ancestor time preflight

The fallible A05-facing `ResourceDomain::try_usage(sample_boottime_ns)`
rejects `ClockRollback` when **any ancestor** has observed a later
kernel BOOTTIME; it no longer checks only the sampled leaf's local clock.
This is serialized with all family mutations using the existing gate,
so a concurrent root sample versus descendant ReadUsage has one clear
linearization order. The infallible `usage` remains explicitly a host
*diagnostic* and is not a wire-serving entry point. Rust tests cover
three-level stale observations and 64 two-thread race schedules without
claiming loom or real SMP/IRQ verification.

## One-shot mutation handoff

```text
fn execute_reserved<F>(
    &self,
    token: &ReserveToken,
    publisher: PublisherId,
    execute: F,
) -> Result<DeliveryObservation, DeliveryError>
where F: FnMut(RequestBinding) -> PublishOutcome;

fn execute_native_reserved<T, F>(
    &self,
    token: &ReserveToken,
    publisher: PublisherId,
    execute: F,
) -> Result<DeliveryObservation, DeliveryError>
where
    T: core::any::Any + Send + Sync,
    F: FnMut(NativeExecution<'_, T>) -> PublishOutcome;
```

The generic entry accepts host requests only. The typed native entry supplies
`context.owner() -> &T`, `context.binding() -> RequestBinding`,
`context.ancestor_epochs() -> &[u64]` and `context.id() -> DeliveryId`
from the exact immutable stored request. Neither asks a queue worker to keep
another owner handle or reconstruct authorization context from public IDs.
Public generic native execution is rejected before callback admission, closing
the accidental wrong-instance/fresh-ancestor execution route. Trusted code can
still misuse a callback or manufacture a reconciliation result; this seam
does not authenticate compromised privileged code.

`FnMut` permits the core to borrow the callback for its single invocation.
It does not permit a second effect for the same D. The public entry retains
the callback object until the execution gate has been released, including
when the body unwinds. Owned captures are therefore destroyed outside that
gate. A consuming `FnOnce` call would instead run their implicit destructors
under the gate even if the body did not allocate or reenter. A caller whose
callback captures a borrowed object still owns that object's lifetime.

After a valid outcome is published, capture cleanup can observe the terminal
result or begin history loss. A panic in capture cleanup cannot change that
saved result back into a pending operation. If the callback body panics or
returns malformed metadata, cleanup runs after the gate is released while
the D remains pending until trusted reconciliation or history loss.

A05/A06 supply one callback which checks actual kernel authority and
performs the resource CAS under the real resource mutation lock. This callback
runs under the reserved entry's execution gate, with neither the namespace
table mutex nor result-state mutex held. It must not reenter this namespace,
copy user memory, allocate or acquire the namespace table lock. The callback's
locks must follow execution gate -> resource; no resource path may reverse
into that execution gate or namespace table. Observation uses the independent
short state mutex, so a delayed callback does not block unrelated delivery
operations or its own Reserved observation. The portable-spin backend
still requires a validated interrupt/preemption adapter before kernel use.

The core marks the slot internally Executing **before** the callback. A
terminal retry returns its immutable saved result without invoking the
callback again. If the callback unwinds on the host or returns malformed
metadata, the slot remains pending (wire `Reserved`) and subsequent execution
returns `Busy`. Retirement cannot cross it. This does not fabricate a terminal
refusal for an effect whose result is unknown. Only the trusted adapter, after
fencing the original executor and establishing the outcome, may reconcile
with `publish`. Host mutex poison recovery cannot cause a second effect.

Namespace loss uses the same execution gate: it fences before a callback
starts or waits for that callback and its complete result, without holding
the namespace table during the wait. It cannot complete in the middle of a
synchronous effect/publication. This is an in-memory guarantee,
not atomicity with Hepta fsync or physical devices. Actual process death,
crash/reboot and asynchronous external executor fencing remain A05/A07 work.

## Shared family BOOTTIME floor

Successful `try_usage`, diagnostic `usage`, budget CAS and CPU charges advance
one monotonic floor shared by every descendant, ancestor and sibling in a root
family. Old read/CAS/point-charge timestamps and interval starts are rejected
before mutation. New children inherit the family floor even when the newest
observation was in a cousin. Failed CAS, exhausted charge and inconsistent
accounting do not advance it. `usage` clamps its diagnostic timestamp to the
floor and preserves cumulative usage. Independent root families still require
the actual kernel's trusted global clock.

The N0 model requires runtime settlement before observation. A caller cannot
sample ahead and later insert unsettled CPU intervals into the past. This
shared clock rule is not an SMP metering algorithm; A06 must settle real CPU
slices and observations under its scheduler's lock discipline.

`tests/control/run-validation.sh OUTPUT_DIR` repeats both host backend test
suites, formatting, strict Clippy, the x86_64-unknown-none library check,
the separate bounded Loom harness and the native lock-allocation probe.
`kernel_handoff` tests use a synthetic external callback; they do not call
an actual kernel driver or the persistent Hepta owner.


## Resource lifetime and bounded hierarchy

An active child cap constraint follows the **last strong reference** to its
ResourceDomainInner. Dropping an ordinary cloned ResourceDomain does not
remove it: grants, descendants and retained result slots can still preserve
the domain. A token alone does not retain a retired result or domain. Once
the final reference disappears, Drop
removes only the corresponding entry from the immediate parent's active-child
cap map. It briefly reads its ID under self state, releases that guard, then
takes the parent's short map lock, never the family mutation gate.
Identity tombstones, parent CPU usage and family clock are never refunded or
removed. Thus a dead child cannot permanently prevent a lower parent cap,
while a retained child still constrains the parent.

MAX_RESOURCE_DEPTH is 64 including the root. Creation at the limit returns
ResourceError::Exhausted before consuming IDs, changing child metadata or
advancing clocks. This bounds ancestry walks and recursive parent-handle drop.
A host 64KiB-stack regression exercises destruction at the permitted depth;
it is not a native-kernel stack, IRQ or deferred-reclamation proof. A05/A06
must verify their actual object ownership, residual charges and kernel stack.

## Retired token ownership

The bounded namespace window owns each complete request, grant and result
slot. ReserveToken caches immutable delivery metadata and holds only a weak
namespace reference; it holds neither Arc nor Weak to a result slot. This
also avoids retaining the slot's backing allocation through obsolete Weak
handles. Each operation resolves the token against the exact namespace
instance/generation, non-reusing sequence and complete request binding, pins
the live slot transiently, then rechecks it after taking the execution gate.

Retirement, explicit history loss or destruction of the last namespace owner
releases namespace-held result slots and owner pins even if old tokens remain
in caller memory. An already admitted operation's transient pin or an external
owner Arc can still preserve the object until its own lifetime ends.
Those tokens cannot execute or publish again; their cached ID/binding remain
readable. A DeliveryView or original-owner authority still intentionally
retains namespace history. Callers must bound their own collections of token
metadata; the window quota is not a quota on arbitrary caller allocations.

## Management-only revocation and lease state

`ManagementGrantState` is a non-Clone state value embedded **once** in the
existing resource owner's mutation lock. It holds one delegation's identity,
publisher, target/object, management delegation epoch, validity interval and cap ceiling.
It holds no resource budget, runtime counter, revision, global clock, registry
or persistent ledger. It is an available primitive for A05/A06 to adopt;
the native kernel and the old host `Grant` do not automatically use it.

Trusted bootstrap constructs `ManagementGrantState::new(ManagementGrantConfig)`.
Nonzero IDs/epoch, `issued_at_ns < expires_at_ns` and a cap ceiling within
the fixed CPU period are checked. `snapshot()` captures terms, not current
rights. Native `context.management_snapshot()` returns the exact saved snapshot
when the reservation used `from_management`; `from_owner` leaves it None.
None does not grant rights or imply lease validation: that path still requires
the actual owner's existing authority checks.

Inside the same lock as budget CAS/runtime settlement and revoke, call
`state.check(snapshot, context.binding(), actual_boottime_ns)`. This checks
the original state instance and all terms, publisher/target/object/delegation epoch,
fixed period, cap ceiling and `[issued_at_ns, expires_at_ns)` validity.
The caller must sample trusted current BOOTTIME and reject rollback; this
predicate does not keep another clock or enforce lock ordering itself. Do not
check, unlock and later commit. These semantic checks happen after reservation;
expiry, revocation or cap-envelope denial becomes an immutable terminal refusal.
`ManagementError::delivery_status()` maps them to existing HOS2 statuses.

`revoke()` only closes this management delegation. It returns an idempotent
`ManagementRevokeReceipt`, advances its epoch once (saturating at MAX) and never
reactivates it. Applications may keep running/accounting under their already
admitted budget, and an independent manager remains usable. Revoke does not
change a budget, refund usage, imply user pause, invalidate history or prove
hardware quiescence. `ResourceDomain::revoke()` retains its distinct host-model
whole-domain semantics. Reason-dependent recovery policy, timers and actual
process-exit handling remain the real owner's responsibilities.

State instances mint private Arc identity tags; Snapshot is Clone but not Copy.
Tag equality plus complete terms prevents a new state with identical public
configuration from accepting an old snapshot, even after the original state
was destroyed. Tags are instance identity, not liveness or kernel credentials.
Creating a replacement state cannot reopen an old D: native dedupe distinguishes
the new origin, changed terms, and Some/None paths. New authorization needs a
fresh D and the original Hepta K policy; no durable ledger is added.

## Weak native-owner back-references

An owner retained by a native result slot must use
`ControlCore::downgrade() -> WeakControlCore` for a namespace back-reference,
then `WeakControlCore::upgrade() -> Option<ControlCore>` for observation.
The weak handle retains no history or retirement authority. Upgrade returns
None after the last strong namespace/history owner disappears, even if old
tokens survive. An active DeliveryView or OriginalOwnerAuthority deliberately
keeps history alive; explicit history loss still fences every old token.

This avoids the concrete namespace -> slot -> native owner -> namespace
strong-reference cycle. It does not automatically break arbitrary caller-created
Arc cycles; existing strong back-links must be migrated by their owner. Owner
Drop can upgrade a weak link during explicit retirement/loss after internal
locks are released. During final namespace destruction it cannot resurrect
that namespace. Tests cover both cases with bounded, joined helper threads.

## Public native namespace synchronization

`LockBackend` supplies one `ControlMutex` for each protected value. Its GAT
guard borrows the lock and implements `DerefMut`; it has no `Send` or `Sync`
requirement, so an IRQ/preemption guard may remain on the acquiring CPU/thread.
The backend type itself and its locks are `Send + Sync`. No unsafe code,
erased guard, new scheduler owner or persistent store is needed in the core.

| `LockRole` | Protected state / held across |
| --- | --- |
| `NamespaceTable` | Short admission, lookup and frontier transitions |
| `SlotState` | Short pending/executing/terminal state transitions |
| `SlotExecution` | One delivery's callback, reconciliation or loss fence |
| `HistoryLoss` | Serialization of a whole namespace loss operation |

Roles describe use, not an IRQ policy. Execution callbacks and a loss fence can
take time or wait for another gate. A native backend must choose suitable lock
classes and preserve the documented order; blindly IRQ-masking every role is
not validated by this API. Each lock must serialize access to the same retained
value, publish writes on unlock and observe them on subsequent lock, with no
allocation or external destructor inside its lock/guard operations. As with any
safe synchronization abstraction, Rust type checking does not prove that a
consumer's custom backend implements these semantics correctly.

The namespace uses the supplied backend for all four roles. `NativeTarget`,
`NativeGrant`, `NativeExecution`, `ManagementGrantState` and `NativeResourceState`
remain independent of the namespace lock type. The host-only `ResourceDomain`
family retains its default host mutex. The `commit` simulation still uses
the selected namespace backend around that host resource operation; it does
not create a native CPU owner. A no_std consumer currently enables
`portable-spin` to compile these default aliases and host fixtures, while
explicitly instantiating its native namespace with its own backend.

Storage preflight and reclamation rules remain in force with an injected
backend. Construct locks before entering namespace guards; callbacks take
execution gate before the actual resource lock, avoid namespace reentry,
allocation and usercopy, and return only after the effect is established.
Kernel IRQ/SMP behavior, lock latency, allocator safety and actual owner lock
ordering require A05/A06 integration evidence.

## Bounded transition models

`python3 tests/control/loom/run-models.py OUTPUT_DIR` uses pinned Loom 0.7.2
and its own Cargo.lock under tests/control. Two temporary-crate variants check
before/after source hashes. The original thirteen fixtures replace only sync.rs
with the tracked Loom Mutex adapter. Six native fixtures use an external public
`LockBackend` and copy every production module, including sync.rs, byte-for-byte
without substitutions. No second state machine, production feature or production
dependency is introduced.

Thirteen fixtures cover same-D reservation/effect, revoke/commit, retire/query,
publish/observe, loss/callback, typed native execution, three-way loss/retirement,
two-D resource CAS, post-effect invalid receipt/reconciliation and management
revocation with independent authorization, reserve/loss revalidation,
overlapping retirement, and native CAS/compatibility writes/owner invalidation.
Each explores up to three workers
plus main, with preemption_bound=3 and
max_branches=10000. No time/permutation cutoff is set; exceeding a branch
limit or any assertion/deadlock fails the command. The runner requires all
nineteen positive schedule counts, fmt and strict Clippy to pass. Public-backend
fixtures cover simultaneous same-D reservation, same-token execution,
revoke/commit, retire/query, publish/observe and loss/execution fencing.

This verifies bounded lock-protected transitions with Loom threads/atomics;
std/alloc Arc/Weak reference-count atomics and finalization are not instrumented.
Allocation failure, actual IRQ/preemption/SMP locks, scheduler/usercopy,
Hepta durability and executions beyond these fixtures/bounds remain unverified.
Default std and portable-spin thread tests still run separately.
Loom 0.7.2's internal Mutex poison handling cannot verify unwind recovery;
the poison/Drop-panic regressions use real host threads instead.
