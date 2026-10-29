# App-server schema regeneration receipt

The official Rust generator regenerated the stable and experimental embedded exports from the current protocol source. The stable map now contains 688 TypeScript files, 294 JSON schemas and one internal JSON schema; the experimental map contains 816 TypeScript files and 414 JSON schemas. `BEFORE.json` and `AFTER.json` retain the exact inventories and changed paths.

`just test -p codex-app-server-protocol --locked --offline` passed all 303 executed tests. The single default-skipped generator entry point was explicitly executed by the official generation commands. All four source/fixture/precomputed consistency tests passed. Mandatory `just fmt --all` also passed.

The generated diff is two compressed export files plus the existing Rust `completed` execution-state variant in `TurnRecoverResponse.json`. No Rust source, comparison predicate or test expectation was changed.

The initial missing OpenSSL-discovery utility and subsequent disk-exhaustion attempt are preserved with their full logs and resource receipts. After a successful direct generation, 120 experimental JSON files were observed outside the generated stable map in the shared workspace; their cause was not established. The official generator was rerun into a private output directory. Its stable compressed output was byte-identical to the first successful output. Completed fixture trees were verified against that map and atomically transferred; `TRANSFER.json` retains every output hash and the paths/hashes removed from the live tree.

`RESULT.json` gives command results, measured subprocess costs and the validation boundary. These local Linux checks do not substitute for the parent task's hosted cross-platform CI.
