# V11 Windows sandbox lint preparation

This is the reviewed preparation for one new, independent Windows lint run on source `ceadcb3b11dbd94a9d07afb7e6301555e4ff3f80`, tree `27651abb15e269c427c75f28f92a3bd1cd9d191f`. It does not contain a native or lint execution result for that source. Ref creation and workflow admission belong to the root task.

The original V10 run remains `FAIL_DIRTY_SOURCE`: its Windows scoped `just fix` command exited zero but changed `setup_process.rs`. V11 contains that exact observed Clippy postimage. Its complete, separate source-only qualification was replayed by the root task from original run `43069105073`, job `130691870162`, attempt `1`; the copied root audit binds the original ZIP and canonical archive. This preparation includes that root audit, not the complete original source-gate archive.

The driver and support file are byte-identical to the original V10 files. The workflow changes only six source, tree, and unique-branch identity occurrences. The final plan changes only source-qualification metadata from the preserved provisional V11 plan. The original 65-minute absolute job budget, tool requirements, two real helper builds, one `just fix --locked -p codex-windows-sandbox` command, source/lock checks, dirty-source rejection, and partial-result preservation remain unchanged. No native test, model request, or earlier native-PASS prerequisite was added.

All twenty dependency files are retained as full bytes under `source-inputs/`. The prior and candidate complete Git tree inventories are retained under `reference/`. The only dependency change from V10 is the recorded `setup_process.rs` postimage; both lockfiles and the other nineteen dependency files are unchanged. The pending plan and its original peer review remain under `history/provisional-before-source-gate-binding/`.

To replay the preparation checks without executing repository or harness code:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 verify_preparation.py .
```

That verifier checks the member manifest, all four output bytes, both complete tree roots, all twenty dependency bytes, original V10-to-V11 identity-only changes, preserved provisional history, and final root-audit binding. A successful result means the preparation is internally consistent; it does not mean that the proposed workflow has run or that the original V10 lint failure has become a pass.

`FINAL_FOUR_OBJECT_SPEC.json` contains the four exact tree elements and independently computed expected harness tree. `FINAL_OBJECT_PUBLICATION.json` records actual immutable blob creation and full text readback. These records do not assert a branch, commit, or workflow admission.

After those preparation records were frozen, the root task admitted the independent harness once at 17:52:52 UTC on 2026-11-11. The appended `ACTUAL_ADMISSION.json`, `HARNESS_COMMIT_READBACK.json`, and `ROOT_FULL_REMOTE_BYTES.json` record that separate action and exact harness `fe824cce50037071ff559e1aabdf36f9d5954908`. Earlier `PREPARED_NOT_ADMITTED` fields describe their original preparation phase; they are preserved rather than rewritten. This preparation package contains no result from the newly admitted run.
