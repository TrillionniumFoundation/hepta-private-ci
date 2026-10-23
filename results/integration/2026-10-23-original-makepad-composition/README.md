# Original Makepad App composition: source and verification evidence

This record accompanies Hepta source commit
`bb3a82cc6c4c24fae5fe62d83ff723afb6326224`, tree
`9f45307ad3502328aee501e5c142388c541351b0`, based on
`56630b12b8a4c69fff2c47b95b36d88a7389c39f` (the original #3067 candidate).
It contains the original App composition source, its exact preimages, source
provenance, authored verification gates and the limited checks actually run.

## What this source adds

The existing Makepad App can adopt an external, already-owned original
`ChatWorkspace` through `native-presentation`. One `ChatSourceSlot` and the
original `ImeRouter` remain in the original App. The caller supplies its existing
workspace; the composition path does not construct a replacement workspace or
copy its draft. Both existing `NativeHost` and the new presentation mode use the
same event-loop admission and App lifecycle. The original owner-host event,
witness and close implementation from `before_event` onward is byte-identical.

The new presentation mode has no owner installation or Send authority. It shows
nonblocking observations through the existing Console widgets and can request
a read-only refresh. `RequestSend` still returns `SendUnavailable`. Cleanup
releases the client once; it does not cancel a Session, Agentd run or effect.

Fourteen omitted notice files are restored byte-for-byte from their original
historical source. Together with the already-present CJK OFL, all fifteen match
the unchanged current catalog. The catalog still requires 29 assets and the
exact Liberation corresponding-source archive. This evidence includes source
and notice provenance, not a complete verified resource bundle or rendered font.

## Executed checks and their limits

| Check | Actual result | What it establishes |
| --- | --- | --- |
| Exact JUnit gate Python tests | 12 passed normally and 12 passed with `python -O`; the root reviewer repeated both sets | Synthetic report/receipt acceptance and rejection logic |
| Workflow syntax | YAML/TOML/Python parsed; four Bash blocks passed `bash -n` | Parseable candidate configuration and exact command/profile wiring |
| Rust source syntax/format | Official Rust 1.95 rustfmt, stdin-only, 13 upstream Rust files passed; v3 preserves their v2 bytes | Syntax/format only; no name resolution, type checking or linking |
| Patch v3 | `git apply --check`, `git apply`, all 35 final file comparisons passed | Patch applies to the recorded ten original preimages and produces the recorded source |
| Original byte boundaries | Original UI lock, core, presenter, IME router, pointer gate, room/composer and native-host event suffix retained | Those source sections were not replaced by this slice |
| Remote source publication | Root verified all 9,159 tree leaves by mode/blob and all 35 changed files | Published source identity, not CI or runtime qualification |

There was **no Cargo invocation, Rust compilation, Rust test execution, actual
nextest execution or native window run for this slice**. Previous Desktop egui
and shared-presenter tests qualify their earlier source only. This archive
does not promote those earlier results to the new Makepad composition.

## Mandatory next execution

The new workflow retains the original browser lanes and adds source-head and
base-merge Linux native-presentation lanes. It uses the original locked graph,
Rust 1.95 and official nextest 0.9.146. Both full `--lib` selections remain
unfiltered. Fresh JUnit reports must contain exactly the required new test
names: five in headless mode and all eight in native mode. Missing, skipped,
failed, retried, duplicate or prefix-substituted cases fail the gate even when
old tests succeed. Native Clippy denies warnings. These are configured future
gates, not completed results.

Desktop still needs its separate adapter, all three original UI dependencies
pinned to this real source commit, a normal Cargo-generated lock, default,
shared and native tests, and a verified resource bundle. Only one Desktop
Personal/Research/Build slot may be chosen for a candidate window. Safe switching
needs scope/generation protection against overlapping `RoomKey` values and late
IME events. A complete three-slot UI remains open.

The current original native editor preserves valid draft text on rejected
edits, but can reset selection and undo during reconciliation. Resource
preflight and SDK Loaded state do not prove which font bytes later produce
pixels; compiler-recorded absolute source paths and later filesystem changes
remain relevant. Physical IME, readable CJK pixels, assistive technology, Web,
mobile and bare-metal acceptance remain separate work.

## Evidence layout

`archive-entries.json` is an explicit allow-list of complete files with exact
size, SHA-256 and Git blob digest. `inventory-summary.json` reports its totals
and classifications. Root can create a deterministic archive directly from
that allow-list and verify every member after extraction.

Included records contain the 212 original Hepta source snapshots, frozen v1/v2/v3
source and patch records, their actual patch command outputs, the original SDK
API/build inputs, official nextest JUnit source inputs, original notice inputs,
the Python/static checks and their raw output, and the root's independent test
and publication readback records. Historical patch v1's real exit 128 is kept:
its generator incorrectly split a GPL form-feed; v2/v3 correct LF handling
without changing the original license bytes.

The combined rustfmt receipts retain their original record, including paths of
the separately developing Desktop slice; this archive includes only their
upstream raw inputs/outputs. It does not package the unfinished Desktop source,
Git/Cargo caches, temporary patch-check repositories, cache-migration records,
Agentd V8 research, target directories, binaries or font payloads.


## Published archive

`raw-evidence.tar.gz` retains all 350 allow-listed complete files plus the
original allow-list and inventory summary. `manifest.json` records every raw
member byte count, SHA-256 and Git blob; decoding the deterministic archive
matched every original member. The subsequent archive commit changes only
evidence. Desktop dependencies pin the actual source commit `bb3a82cc6c4c24fae5fe62d83ff723afb6326224`.

```sh
python3 -m tarfile -e raw-evidence.tar.gz extracted
```

The 212 original input snapshots include pre-existing PNG test fixtures. Those
images are historical source inputs from the pinned original repository, not
new screenshots or evidence that this Makepad candidate rendered successfully.
No compiled executables or libraries are included.
