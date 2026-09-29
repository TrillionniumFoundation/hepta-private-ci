# Complete-message output observation and verification checkpoint

This supplement updates the historical qualification checkpoint in
`HARDENING_STATUS.md`. It is not a final-candidate pass receipt or deployment
acceptance. The exact source and merge candidate must still pass qualification.

## Observed defect and source repair

Run `36297653148`, macOS merge-candidate lane, tested source
`543c2a2a6a35d5a8cfacb2c451f83d280fdce8eb`. The actual worker E2E reached a
successful, authority-checked App Server turn but failed its assertion that the
observed output contained `fresh context accepted`.

The controlled Responses provider emitted `response.output_item.done`, carrying
a complete assistant message without text deltas. The App Server exposes both
item completion and the final-message turn summary. The old worker only appended
`AgentMessageDelta`, so successful terminality could accompany silently missing
output. Adding artificial deltas to the fixture would hide the runtime defect;
the original E2E output and tombstone/correction assertions are retained.

`native_output.rs` implements per-item assembly scoped to the existing exact
`CodexTurnBinding`. That assembly is shared through normal observation and
interrupt grace, not a process-global cache or another durable store.

- A complete item can provide the first and only copy of its message.
- Deltas and completions for one item are merged, not concatenated twice.
- First-observed item order is stable even when item deltas interleave.
- A matching duplicate completion is idempotent. Conflicting completed content,
  deltas after completion or a completion inconsistent with the observed prefix
  fail rather than rewriting history.
- A final-message summary is merged by item ID; it cannot replace earlier
  messages with a partial view of the turn.
- Aggregate output remains bounded to 1 MiB, at most 4096 items and 256-byte
  nonempty item IDs. Arithmetic and identity checks precede mutation. A batch
  snapshot with a conflicting later item cannot partially publish earlier items.

Only the matching, adapter-validated turn completion establishes terminality and
correlation. Message completion does not grant success. Existing cancellation,
timeout, authority-loss and cumulative-usage semantics remain in force.

Four new source tests cover completion-only/idempotent summary, interleaved
items, atomic conflict rejection and byte/item/identity bounds. The existing
observation tests now retain one binding/assembly through each tested sequence
rather than reconstructing a binding on every event.

## Actual native evidence before this output repair

The retained artifact is `10924797638`, named
`inference-libraries-macos-15-merge-candidate-543c2a2a6a35d5a8cfacb2c451f83d280fdce8eb`.
It contains actual nextest JUnit and logs, not a hand-written success summary.

| Library | Executed | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: | ---: |
| inference.control | 29 | 29 | 0 | 0 |
| inference.worker | 62 | 61 | 1 | 0 |
| Agentd | 169 | 169 | 0 | 0 |

All ten `local_admission::tests` and all four `native_diagnostics::tests` passed
in that worker run. The sole worker failure is the real E2E output assertion
above. These results supersede the earlier statement that those fourteen tests
had not yet executed; they do not establish that this later output repair passed.

Retained JUnit SHA-256:

- `infer_core.xml`: `b8b0e856725724ea2c88b62c10975704e306fbff6adee3e06f1cf94c709afa2c`
- `worker.xml`: `eb916fd62174ef28a9445e6da069ce392984b00734d680be84e9bbc473118ae6`
- `agentd.xml`: `72e6063f48f624a28483952f11b2e913ffd149b882eb5e1c5c6b1fe32e1d083f`

## Source preparation is not qualification

The reviewed two-file wiring patch and four affected source files were prepared
with repository Rustfmt in run `36298950745` from source
`6ce0d3bedc81dbf481daf1003fa9ba5b9c226d15`. Artifact `10925047569` retains the
exact prepared bytes, diff, SHA-256 and Git blob IDs. The formatter made only two
additional layout changes. The prepared source was compared with the reviewed
local patch and each retained file's two hashes verified before integration.

This temporary operation created unreferenced blobs only: no ref update, commit,
merge, acceptance or deployment was performed by the workflow. The temporary
preparation workflow and staging patch are removed from the integrated source
candidate. All retained qualification workflows remain read-only.

No Linux/native all-target/Clippy result, real provider/device qualification or
independent acceptance follows from formatter success. Cross-module stale
observations and non-ancestor historical implementation-map anchors remain
repository-controlled baseline blockers. The local physical driver, durable
local operation/handle reconciliation, late authenticated usage amendments,
permanent missing-history resolution, configurable acknowledgement grace and
complete durable metrics remain unfinished.
