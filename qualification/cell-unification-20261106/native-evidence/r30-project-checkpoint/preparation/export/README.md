# R30 closed project evidence exporter — inert preparation

The frozen template is `export-r30-closed-template.py`. Its SHA256 is
`45e64afcdffd597de793c12158f90f605bb2274667b2774ad39d431a4af3700a`
(44,373 bytes). It has not been imported, executed or uploaded to the native
task. `FROZEN=False` and all three closure maps remain `None`.

The original job is `1a1b25b399f-fc05-7daa`. The exporter records that job's
actual outcome for source53 commit `f74be175de66a4b351cd239d39d98cd34fe9cc1b`,
tree `440d4a8e09af4009e4d9ea067388826308da8803`. Source53 contains diagnostic
logging; `diagnostic_only=true` and `behavior_repair_claimed=false` remain
explicit throughout. No outcome is prefilled.

The producer executes the original app-server strict command followed by its
complete project test command. A successful closure has exactly 19 producer
files plus the separately preserved authoritative terminal JSON. A failure
may have fewer files, an incomplete record or an orchestration-error record.
The exporter binds and copies the actual existing set, preserving missing
records as missing. It does not fabricate successful receipts or convert a
controller return into an unobserved subprocess return.

Eight helper functions are copied byte-for-byte from the reviewed R28 v2
exporter. `clean_lines` and `review_tests` are copied byte-for-byte from the
actual reviewed R30 v2 producer. The latter checks the exact 1,345 app-server
IDs after execution. A compiler failure without a complete Starting/Summary
pair retains null test counts. Original raw process exits, effective receipt
exits and the authoritative outer exit remain separate.

The archive contains all 197 raw changed source files, both raw locks, nearest
AGENTS instructions, the exact applied seven-member input, full source53 apply
evidence, the original runner, the app-server baseline, ancestor manifests and
the existing source50 lock and source51/source52 apply provenance. Both source
guards check raw bytes, Git blobs, Git modes, the exact staged tree, original
HEAD and absence of unrelated unstaged/untracked files. No Cargo metadata or
Rust command is run. The sole subprocess helper allows only Git read operations
already used by earlier exporters.

Controller verification follows the real R30 direct-file launch rather than an
earlier python `-c` form. Raw controller JSON is retained. Chunk length is
`next_offset - offset`, while `size` is the complete stream size at that read.
The nonempty ranges must form a continuous stream; the terminal seen/stored
counts must match the reconstructed stdout and stderr exactly.

All output files are create-only and flushed/fsynced. The exporter rechecks
every original after collection, writes a deterministic gzip/tar archive, then
reads back every member's bytes and mode. A successful export only establishes
artifact closure. Readback errors are retained and prevent an export-derived
PASS claim; a failed original gate remains failed. Root's complete independent
archive review is still required before any subsequent qualification decision.

`superseded-local-draft-v1/` preserves the initial unexecuted local draft and
its build records. Self-review found that the producer's environment pin has no
`path` member. The frozen template now uses the producer's exact fixed
`agentd-prerequisite-env.json` path. The generator's raw header literal was also
corrected to preserve the regex spelling and remove a local SyntaxWarning.
Neither draft was executed or used to read native files.

## Execution boundary

Only after the original R30 job naturally closes may the three maps be filled
in a separate bound file. Root must review the exact bindings and frozen file
before a single artifact-only execution. The exporter cannot launch R31, run
fix/format, apply a patch, alter the index, update locks or retry any test.

