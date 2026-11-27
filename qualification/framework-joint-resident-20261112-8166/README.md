# Explicit resident Joint execution on the current owner chain

This candidate is stacked on the independently qualified generation-journal
source `21d2699b7ac7831f355f5acb9570a90da077dbe3` (#6034). Its new resident
code needs its own qualification; #6034's 96 passing tests are not transferred.

The resident transport, framing helper and original regression cases originate
from #4938, exact source `f09dea504916d551e13fe36752dd1e833bcaa51b`. That
branch's common ancestor with current owner assembly #6006 is
`7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75`. This is a selective adaptation;
the old proposal file is not substituted for the current observed V2 kernel.

## Actual entry and ownership

The existing Agentd main reads the pinned generation bootstrap descriptor.
`load_neuron_generation_process_bootstrap_v1` selects the resident constructor
only for `joint-generator-resident-linux-v1` or
`joint-generator-resident-linux-v2`. Existing one-shot profiles retain their
default transport. The same no-follow asset opening, inode-alias checks, actual
file digests, device identity and held executable descriptor remain in force.

The selected worker enters the existing `ControlledCellGenerationPortV2`.
The original control journal, one-use dispatch proof, Cell journal, witness,
acknowledgement and output owners remain authoritative. A helper receives no
owner paths, publication destination or new grant.

Each worker retains one immutable weights/public pair and deterministic initial
encoding. A successful resident binds its complete manifest digest; another
bundle/manifest is refused without discarding the original cache. Every Cell
request still supplies its own complete predecessor, prefix, owner delivery
contract and request digest. The current V2 portfolio, live budget, planning
receipt and autoregressive text-state checks remain on the original proposal
path. A checked transport clock sample refreshes V2 budget after contention.

## Bounds and failure

One exchange holds the transport. Frames and capacity-one pipe channels remain
bounded. Waiting callers check their own cancellation/deadline. Cancellation or
failure after submission poisons the session; no automatic respawn or replay is
introduced. A known terminal outcome requires bounded child/pipe termination;
unconfirmed termination or transport errors remain unresolved at the owner.

The current mounted-procfs descriptor resolver is retained. Zero clock samples
are refused at native entry and on the observed V2 payload path. The V2 payload
check explicitly returns Unavailable through the worker instead of allowing
invalid-clock uncertainty to become a terminal Rejected proposal.

## Qualification and limits

The branch enables the existing Cell framework native workflow without changing
its commands or gates. It also retains ordinary PR CI. New-source results are
pending. The local executor is unavailable; no local build, format, lint or
native pass is claimed.

Tests retain the original resident parity, IPC, concurrent-Cell isolation,
cancellation, deadline and poison cases. Added cases cover changed manifests,
invalid clocks, current V2 budget/portfolio/planning/text behavior, and the real
descriptor-to-service cold reopen retaining an original result without dispatch.

This supports the existing Linux FP64 width32/depth1/dual/direct helper. Synthetic
legal tensors establish software behavior, not trained-model quality, adoption,
production activation, throughput or energy savings. The default main still
constructs one worker per explicit descriptor. Automatic cross-Agent pooling,
fair global scheduling, Joint tensor microbatching and production asset adoption
are separate work. Resident RSS is not metered or reserved for its full lifetime
by this slice, and no globally fair memory pool is introduced. Control journal
native headroom is serialized journal/result capacity, not a resident RAM budget.
Per-event journal durability and full cold replay remain.
