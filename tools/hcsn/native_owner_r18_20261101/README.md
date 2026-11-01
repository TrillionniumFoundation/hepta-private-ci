# R18 native owner and stateful provider

This opt-in Rust prototype qualifies local durable-mailbox process recovery.
The owner owns its cursor, pending outbox, received inbox, time and fee ledger.
A separate Rust provider performs real persistent billing/counter effects,
binds operation IDs to receipts, and fences old generations. The numerical CTMC
states and fixed actions are controlled replay frames exported from frozen
Python R17. Rust does not evaluate the financial kernel or choose live neural
actions; this is not production `hepta-neuron` activation.

The corrected run02 passed 130 cases and 408 native processes. Read
[REPORT_ZH.md](REPORT_ZH.md), [BLOCKERS.json](BLOCKERS.json),
[SOURCE_HISTORY.json](SOURCE_HISTORY.json) and the independent audits.
The v1 result is retained: independent review found a lease/reply atomicity gap
outside its registered faults. V2 fixes that gap and adds its crash regression.

## Build and reproduce

Use Rust 1.95.0 or a compatible toolchain. No crates or network access are needed.
From the repository root, build into a new path and use a new output directory:

```sh
rustc --edition=2024 -D warnings \
  tools/hcsn/native_owner_r18_20261101/main.rs -o /tmp/hcsn-r18-new-owner
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m tools.hcsn.native_owner_r18_20261101.campaign \
  --binary /tmp/hcsn-r18-new-owner \
  --manifest tools/hcsn/native_owner_r18_20261101/SOURCE_MANIFEST_V2.json \
  --protocol tools/hcsn/native_owner_r18_20261101/PROTOCOL_V2.json \
  --output /tmp/hcsn-r18-new-results
python -m tools.hcsn.native_owner_r18_20261101.audit \
  /tmp/hcsn-r18-new-results --output /tmp/hcsn-r18-new-audit.json
```

`main.rs` accepts owner/provider roles, a frozen job, a private state file and a
private mailbox directory. State ownership is single-host and file-lock scoped.
Mailbox request IDs bind the complete request checksum and exact reply;
LEASE generation, provider effect and request reply are committed atomically.
Any storage uncertainty fails the provider process closed. State uses FNV64 for
accidental corruption detection, not cryptographic authentication of hostile
local writers; source and delivery identities use SHA256.

The actual mutable provider effects are purchase count and microcredit charge.
Observation tokens are the declared replay fixture, not real media acquisition.
Identical already-committed requests may return their prior receipt even after
an owner is stale; all new effects require the current generation.

## Complete raw evidence

[delivery_small/README.md](delivery_small/README.md) explains how to reconstruct
all raw results, including original v1 results, native state files, request/reply
caches, process receipts, fault markers and Python numerical reference frames.
[delivery_small/MANIFEST.json](delivery_small/MANIFEST.json) binds the small parts.
The included RAW_EVIDENCE_INDEX.json verifies every retained raw byte.
