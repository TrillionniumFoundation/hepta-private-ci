# R30 formal checkpoint preparation

This directory prepares a new `native-evidence/r30-project-checkpoint` group. It never modifies source, native state, existing frozen evidence groups, the three canonical reports, INDEX or the publication ledger.

`PREPARATION-PLAN.json` freezes 88 existing attachment inputs and the exact 20 original R30 files (19 project originals plus the separate outer terminal). Its archive fields deliberately remain unbound until root's unique download is present and verified. The plan is a preparation snapshot, not a claim that a full archive has been checked locally.

`assemble.py` uses only Python standard-library file/JSON/hash/archive operations. It does not import or execute any runner, run Git, call Cargo/Rust/metadata, run a formatter, contact the native controller or upload anything. Its AST has been parsed; the assembler itself has not yet been executed.

After the complete original archive arrives, create a new `FINAL-INPUTS.json` following the template. Bind the archive's exact relative path, bytes, SHA256 and Git blob. Optional root custody/readback files require exact source pins and safe report destinations. No R31 result or preparation belongs in this group. The expected member count is learned from the actual archive and verified against every INDEX row; it is not guessed from small receipts.

Run the assembler only on those closed local inputs. Without `--seal` it verifies and prints a small result without creating the formal group. With `--seal` it verifies all inputs before creating the new directory and refuses an existing destination:

```sh
python3 source53-r30-formal-preparation/assemble.py --inputs source53-r30-formal-preparation/FINAL-INPUTS.json --seal
```

The full archive and original INDEX are preserved. Every non-source archive member is attached with a source/destination map; all 197 source files remain available within the complete archive and are individually rehashed against the registered manifest. The assembler does not claim an additional offline whole-Git-tree reconstruction. Large UTF-8 report copies may use deterministic, lossless gzip; both original and copy pins remain explicit.

The complete log is independently parsed for exactly 1,345 unique PASS rows, zero FAIL/TIMEOUT and two reported skips. Raw, effective and outer returns, resources, controller ranges, original manifests and both locks are checked independently. The old R29 Bedrock failure remains historical source52 evidence, while the new R30 PASS is attached to diagnostic source53. Neither root cause resolution, behavior repair, whole-workspace qualification nor scientific approval is inferred.

On successful sealing, the script writes only the new formal group and preparation-local `BINARY-PLAN.json` / `HANDOFF-MANIFEST.json`. New binary objects are listed for root registration; the assembler performs no uploads. Scientific results remain HOLD, and authority remains DENY_ALL.
