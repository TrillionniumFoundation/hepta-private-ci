# Native HIA Cell continuation

This component gives a runtime a real native HIA controller for one Cell
invocation. The checked-in `continuation.hepta` owns invocation, result,
cancellation-request and unknown/recovery decisions. A host cannot obtain a
second `INVOKE_CELL` from a nonempty continuation. It can settle unknown work
using the observed result of the original operation.

The compiler, Core, direct emitter and its closed runtime imports are unchanged
from `f33d8da316de8fdf27b504371f1a5310997ff548`. The hosted compiler builds a
native shared object with the existing borrowed-byte ABI. This is not a
self-hosted compiler or a whole-stack HIA replacement.

## Runtime contract and actual effects

The runtime is the only durable state owner. It must compute and verify the
candidate, Cell, request and input commitments. A digest supplied to HIA is an
observed identity, not authentication of its preimage. The Python transport
checks actual payload SHA256 before and after native execution; the runtime
must separately validate its canonical complete Cell request and its authority.

The runtime must commit pending state and original request identity before
performing an HIA-issued effect through its existing authorized Cell entry.
The component grants no execution permission, model adoption, publication or
write authority. It does not call a model, write an experience record, persist
state or provide an exactly-once external-effect guarantee by itself.

An interrupted pending continuation recovers as `UNKNOWN`. Recovery never
returns `INVOKE_CELL`. The runtime can inspect its retained original Cell
receipt and return it as RESULT. If no receipt exists, effects stay unknown;
there is no implicit inference replay. `CANCEL_REQUEST` is a request to the
existing owner. Only an observed cancelled RESULT produces `CANCELLED`, and
an actual success can still win a cancellation race.

One continuation handles one operation. The runtime retains terminal state
and the result bytes together, and reads its own stored result on duplicate
business requests. Native HIA refuses a second RESULT after a terminal. The
runtime must bind new operations to new state and new request identity.

## C ABI

The exported symbol is:

```c
uint64_t cell_bridge_step(const void *request, uint64_t request_bytes,
                         void *response, uint64_t response_capacity,
                         void *state, uint64_t state_bytes);
```

The existing wrapper returns `ABI_status << 32 | Core_status`. Zero means the
call completed successfully. Native ABI status values 1–4 mean extent, null,
address or alias rejection. The three live allocations must be disjoint, with
exclusive mutable response/state ranges. Numeric range checks do not prove
pointer provenance or prevent a caller from mutating memory concurrently.

Request and response have a 256-byte header followed by at most 65,536 payload
bytes. State is exactly 256 bytes. Every integer is unsigned little-endian u64;
digests are the complete 32 raw SHA256 bytes. Initial state is all zero bytes.

| Offset | Request | Response | State |
| --- | --- | --- | --- |
| 0 | `HCLREQ01` | `HCLRES01` | `HCLSTA01` |
| 8 | version 1 | version 1 | version 1 |
| 16 | event | action | phase |
| 24 | nonzero sequence | same sequence | same sequence |
| 32 | candidate SHA256 | same digest | same digest |
| 64 | Cell SHA256 | same digest | same digest |
| 96 | canonical Cell request SHA256 | same digest | same digest |
| 128 | initial input SHA256 | same digest | same digest |
| 160 | this payload length | this payload length | initial input length |
| 168 | observed result status | resulting phase | admitted result limit |
| 176 | admitted result limit | same limit | terminal payload length |
| 184 | zero | zero | cancellation request issued: 0/1 |
| 192 | this payload SHA256 | same digest | terminal payload SHA256 |
| 224 | 32 zero reserved bytes | same reserved bytes | 32 zero reserved bytes |

For BEGIN the payload is the actual Cell input, and offset 192 equals offset
128. For definitive RESULT, offset 192 is SHA256 of the actual result bytes,
including SHA256(empty) for a known empty result. UNKNOWN, RECOVER and CANCEL
carry no payload and a zero payload digest, distinguishing missing observation
from a known empty result. Input/result limit and every identity field must
match the original continuation on every resumption.

| Event | Code | Effect |
| --- | --- | --- |
| BEGIN | 1 | only zero state; writes pending state; emits full `INVOKE_CELL` payload |
| RESULT | 2 | only pending/unknown/cancel-pending; consumes an observed original result |
| RECOVER | 3 | unfinished state becomes `UNKNOWN`; never dispatches |
| CANCEL | 4 | emits `CANCEL_REQUEST` once, keeps effects unresolved |

| Result status | Code | Action / state phase |
| --- | --- | --- |
| success | 1 | COMPLETE / 2 |
| failure | 2 | FAILED / 3 |
| cancelled | 3 | CANCELLED / 4 |
| unknown | 4 | UNKNOWN / 5 |

`INVOKE_CELL` is action/phase 1 and `CANCEL_REQUEST` action/phase 6. Native HIA
checks all headers, bounds, identities and permitted phase transitions before
writing either output or state. Every protocol rejection leaves both byte
regions unchanged. Core statuses 1–12 identify request extent, state extent,
payload extent, output capacity, header, identity, result limit, event, state,
resumption binding, observation semantics and duplicate cancellation.

## Build and use

From the pinned Hepta checkout with this component:

```python
from pathlib import Path
from tools.cell_bridge_native import NativeCellBridge, build_native_bridge

root = Path("/absolute/Hepta")
build = build_native_bridge(root, Path("/absolute/new-build-directory"))
bridge = NativeCellBridge(root, build["image_path"], build["image_sha256"],
                          expected_source_sha256=build["source_sha256"])
step = bridge.begin(bytes(256), candidate_sha256=candidate_sha256,
                    cell_sha256=cell_sha256, request_sha256=request_sha256,
                    input_bytes=actual_input, sequence=1)
# Durably commit step.state + original binding before authorized dispatch.
# If step.action is INVOKE_CELL, execute the original Cell request once.
done = bridge.resume(step.state, binding=step.binding,
                     outcome="success", result_bytes=actual_retained_result)
# Durably commit done.state + exact result/experience through the same owner.
bridge.close()
```

`BridgeBinding.to_dict()` and `bridge.binding_from_dict()` serialize the same
binding across processes. `recover()` and `cancel()` take the retained state
and binding. `NativeStep` includes exact response/state/payload bytes, the
native return and native-call wall nanoseconds. The build record retains
compiler/source/Core/object/text/image/linker identities and build wall time.

The Linux loader captures a regular image file without following a final
symlink, verifies the complete captured bytes, then copies them into a new
`memfd`. It installs write, grow, shrink and further-seal protections, reads the
sealed bytes back and verifies their digest before loading. A later rewrite,
replacement or removal of the supplied source file cannot change the loaded
image. Every new constructor checks the supplied file again, including a cache
hit; a changed source file is refused when its expected digest no longer matches.

One thread-safe, process-wide registry retains each successfully loaded image's
sealed descriptor and library for the entire process, keyed by its SHA256.
It also survives independent imports of this wrapper. This prevents a closed
descriptor number from being reused as a `dlopen` name for different bytes.
`close()` revokes the current instance after its admitted call completes; other
instances and later instances of the same image keep working. It does not
unload an image or release registry capacity.

The registry admits at most **16 distinct loaded images and 64 MiB of retained
image bytes**, with an individual-file bound of 64 MiB. New unique images beyond
either limit raise `BridgeCapacityError`; already admitted images remain usable.
A successfully loaded image missing the required entry stays retained and
consumes capacity, so its loader name cannot be recycled. Malformed images that
fail to load and nonregular files are refused without retaining descriptors.
These are image-custody bounds, not a bound on all native process memory.
Compiler, linker, loader, libc, Linux sealing support and host hardware remain
explicit dependencies. Callers still supply the trusted expected image digest;
the loader does not establish that trust on their behalf.

## Component controls

```sh
python -m tools.qualify_cell_bridge_continuation --output /absolute/new-evidence
```

The runner records the complete fixed native test population, every method
terminal, all subtests, before/after source identities, the fresh build and the
original unittest transcript. Controls execute the actual .so at payload sizes
0, 1, 257 and 65,536; each of the 128 request identity bytes; pending/terminal
replay; unknown and cancellation races; malformed headers/state; original ABI
alias guards; and a fresh process resuming the original state. Their scope is
this continuation component. Loader controls additionally compile three native
ABI probes and exercise distinct return values across close/reopen and
simultaneous handles, 64 parallel constructions, immutable image seals, source
file changes, independent module imports, count/byte bounds, missing entries,
invalid ELF and nonblocking FIFO rejection. Their source, images, compiler
receipts and child-process transcripts are retained under `build/loader-fixtures`.
Real Cell execution, durable runtime recovery,
trained-weight benefit and whole-system cost require separate joint tests.

