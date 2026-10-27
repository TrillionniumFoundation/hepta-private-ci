# Retain the cloned observation control after the original lint failure

This child of `99ae396ccdf3534928253b2af7b9329c0127ea44` changes one test.
`NeuralCognitiveExecutionV1` derives `Clone`, not `Copy`, and retains an
`Arc<Mutex<...>>` observation slot. A named cloned handle writes the observation
and refuses a second write while the original handle matches and exports it.
This preserves the actual shared-slot control. No production behavior, model
gate, source pin, workflow, qualification or installation permission changes.

Original Hepta run [40503341442](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40503341442)
at `0366222cbc577969982f406b0c29ea46a33becd2` remains **FAILURE**. Its verified
command records contain542 passing scoped tests, one real ordinary/revocation
test and one real three-round hold/readback test. The original final lint gate
fails because Clippy removes two temporary clones before borrowed method calls;
the unmodified generated patch is retained. Applying that patch mechanically
would discard the cloned-handle exercise, so this source keeps a named clone.

The original three rounds completed with four ordinary sessions reading the
same original CURRENT and no installed child. The separate three descendant
diagnostics also complete. Their gain over the strongest control is0/1 and
over actual CURRENT is1/2; public fixture scores are not independent future
quality. All product and installation flags remain false. This older run does
not establish the later five-package, ordinary-plus-reopen gate or V3 recipe.

`raw-records.tar.gz` contains only selected original command records and bound
logs, the original lint patch, loop/session summaries and six assessments. It
contains no issuer tree, private keys, model/runtime payload or credentials.
Its ZIP source was checked by whole SHA256 and every member's CRC. Original
command-log sizes and SHA256 values were checked before retention.

The new source has only static review and recorded local command availability
checks at this freeze. Exact-source Rust compilation, tests, lint and formatting
remain required in the unchanged original CI; no green result is claimed here.
