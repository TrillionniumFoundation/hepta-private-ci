# Content-addressed contracts for a finite research queue

This source-only study checks identity and cost accounting for one externally
supplied, immutable qualification queue. It performs no neural forward,
CTMC computation, matrix exponential, training, live service access or
production mutation. Private models, schedules, traces, arrays, caches and
result receipts are not part of this source publication.

## Object identity

A fixed linear operator is keyed by complete generator bytes, exact F64
duration bits, checkpoint/source provenance, state basis, output layout and
arithmetic contract. A full-history result additionally binds the entire
initial joint state, full public schedule, every action/observation/owner
state, finite horizon and decoder. Equal tensor shapes never prove reuse.
The key encoder distinguishes signed zero and integer versus floating type.

The isolated single-writer byte store requires an independently supplied
expected payload digest. It rejects missing identity fields, unknown object
kinds, payload corruption, wrong external pins and partial entries. This
checks integrity against a pin, not numerical truth. It makes no production
concurrency, complete environment closure or crash-durability guarantee.

## Offline source qualification

Run `python offline_controls.py` in this directory. Its sixteen controls
use a synthetic byte payload and require only Python's standard library.
They do not read any model or execute the receipt-based scientific audit.

## Private replay configuration

The receipt auditor requires separate `QUEUE_FROZEN.json`, the upstream
protocol and its explicitly pinned source/input files, and complete original
oracle/array/trace/resource receipts. These are external dependencies. This
publication alone is not a standalone reproduction of a scientific result.

The queue supplies absolute paths only in the caller's private configuration;
none are embedded in this source. Freeze with
`python freeze_protocol.py --expected-queue-sha256 <independently-reviewed-sha256>`.
The expected checksum must come from an authorized source. The freeze then
verifies all declared source/input checksums. The queue identifies the fit
set; it is not hard-coded from a private checkpoint population in this copy.
The fixed qualification profile remains five source inputs, two histories
per input and six intervals per history, with separately counted controls.
Run `python supervise.py` only when those already-authorized raw receipts are
available. This executes one audit and one independently written reader,
with a finite CPU/wall/memory budget and no automatic performance retry.

## Cost and decision scope

A predeclared KEEP/STOP decision is retained when there is no newly avoided
computation in the actual queue. Existing upstream operator reuse is not
credited again as a new cache benefit. Cold restoration, identity checks,
serialization, controls, reader and supervision costs are charged. Short
zero CPU readings remain in raw records and process totals provide grouped
accounting; unmeasured costs remain unknown. Missing production demand,
independent benefit labels, utility conversion or future resource bounds
keep general NDU at KEEP_ORIGINAL_AND_STOP.

The integrity reader independently rebuilds content identities and counts
from original receipts and array bytes, cold-reads full payloads, and checks
the cost ledger without importing the producer. It does not supply a new
numerical oracle or infer financial performance.

## Publication provenance

The publisher retains checksums and a configuration/documentation-only diff
between these files and the separately frozen private research source.
Only the external expected queue checksum and fit identifiers are parameterized;
cache semantics, arithmetic identity, validation logic, resource limits and
independent reader are unchanged. The preserved private originals, not this
configuration copy, are the bytes pinned by the original execution receipt.
