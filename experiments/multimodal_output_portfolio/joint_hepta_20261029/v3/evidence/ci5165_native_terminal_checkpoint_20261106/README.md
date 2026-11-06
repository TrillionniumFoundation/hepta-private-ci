# Native Windows Clippy terminal result and Linux failure inventory

This independent supplement records the terminal results at #5165, source
`25a3895dd11a1cb1dde3ba42371a1d629878e25a`, tree
`9bef7c893c42bf10246fc18ce04079077037094d`. The actual pull-request checkout
`37415647323fe41c6f8f98810a2ddf34293a9a0e` has that same tree. All three jobs belong
to ordinary pull-request run 42304403498, attempt 1. The earlier CI32/33/34 packet
keeps its original in-progress snapshot and is not rewritten.

Windows job 128191497898 actually passed the original MSVC Clippy and clean
worktree gates. Its selector analyzed 437 targets with zero build actions; the
Clippy build then analyzed and completed 1,322 targets with 6,768 actions. Those
actions include 2,935 remote cache hits, 3,306 internal actions and 527 local
actions. These are not counts of newly compiled units or independent test cases.
Warnings remain. Both the owner audit and a separate root audit bind the complete
609,523-byte original console to fresh job, source and actual-merge records.

The native workflow captures selector stdout instead of retaining a separate
complete label list or temporary query file. This packet therefore does not claim
an independent native comparison of every selected label. The preserved exact
selector source and earlier local Bazel mechanism checks supply that distinct
scope; the new result supplies actual Windows gate execution.

GNU job 128191497954 and musl job 128191497933 both failed at the same source.
Their complete original consoles print the same five distinct failed Rust cases:
two compact cases and three restricted executor-skill cases. The inventory records
their original failure locations and diagnostics without changing expectations or
the read capability gate. Cached shards and retry replays are identified. The
console totals of 416 passing, three failing remotely and 168 skipped are Bazel
target counts, not individual Rust-case counts. No later repair is qualified by
this failure inventory, and a generic system-bubblewrap warning is not treated as
a sufficient root cause.

Run `python3 -O -B restore.py /absolute/empty/directory` to verify the complete
retained inventory and restore inert regular files. The reader executes no
archived sources. Original commands, complete raw inputs and audit scripts remain
inspectable; scripts preserve their original workspace layout and are not claimed
directly executable after arbitrary relocation. The INDEX records original modes,
including private logs and executable source scripts; restored files use 0644.
Each bounded gzip member contains one exact XZ segment, with no new spelling
exclusion. The previous packet's manifest is a reference, and its archive remains
in the separate published packet. The native execution-log artifact is not
downloaded or revalidated here.

The Windows lint gate is closed at this exact source. Windows runtime safety,
ARM business qualification and repository-wide green status remain separate.
All earlier failures and frozen scientific, protocol and evidence bytes remain
unchanged.
