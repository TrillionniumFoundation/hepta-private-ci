# Actual Windows private-state component matrix

The three original Windows jobs are preserved in full as gzip-compressed
GitHub job-log content. `readback.json` binds the exact source commits, run/job
identities, original UTF-8 bytes and compressed archive hashes. Every job ran
the same original six package targets, without a test filter or cached test
result, under the existing 60-minute limit. Failures remain failures.

The `9c53f8e62037f5c8d1346810549ee018150dd446` run completed the original
path-utils, state, hepta-memory and hepta-prompt-registry targets successfully.
It exercised the retained-directory native rename correction, safe Windows
path spelling comparison, private recovery identity controls, directory flush
handles, and original manifest migration lifecycle.

The intelligence target did not execute in that run: its segmented tests had
implicitly inherited `std::fs` from the neighboring test module. Changing the
neighbor to inspect exclusively locked ledger bytes through the retained file
object removed that incidental import. This follow-up adds the segmented
module's explicit `std::fs` import, with no change to its cases or assertions.
Actual `just fmt` completed successfully on the Mac Rust 1.96.1 toolchain.

The agentd target still exposed the Windows FleetRegistry private-root
provisioning gap and its original test-handle assumptions. Those failures are
retained for the separate production fix and a combined seven-package run.
No successful whole Windows matrix, installed native worker, complete HIA
replacement, or permission weakening is claimed here.
