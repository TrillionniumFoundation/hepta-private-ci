# HEAD + readonly merge recovery

This branch stores recovery instructions and the executed conflict resolver. It is not the merged production source and must not be represented as a successful combined candidate.

## Exact source graph

- Left: `32c0160e60d377eb79983abc394832efce12c988`, tree `a2afbbad566929ddf2b001215c54fe041823d273`.
- Right: `57ffff832355d75937045f240fed2c2d48783029`, tree `f2b297cf94da0029c02e26b644694f7653fa12d7`.
- Observed unique merge-base: `dd4b6c17344986a3a9379e372bf19d282f812a30`.
- The actual local `git merge --no-commit --no-ff` ran from the left parent and initially conflicted in CALLERS plus seven existing QA files. The resolver also updates the new readonly QA module, for eight total.

## State at executor loss

The resolver finished successfully, staged all conflicts, and passed cached diff whitespace checking. Its full-record audit file was observed at 1,480,975 bytes. Counts were 554 boundaries and inventory IDs, 400 protected records across 328 paths, 32 shared channel callers, eight QA constant updates, and 18 exact Rust parent postimages. The native coverage inventory file remained byte-identical to the left parent. No narrow tests, full QA, Rust, or H execution was performed for this merge.

The following local `git commit` was sent but never returned before exec-server disconnected and the platform explicitly reported environment unavailable. No combined commit SHA or tree SHA was obtained. No combined-source GitHub API commit was created. Do not reissue an uncertain local commit or infer its outcome.

## Resolver provenance and use

`resolve_head_readonly_merge_v5.py` is reconstructed from the complete successful patch sequence retained in the conversation. Its source matches the executed resolver, but a fresh filesystem hash was unavailable. It intentionally retains the original scratch paths. On a newly authorized isolated clone, adapt only BASE/ROOT/OUT to the actual deployment paths and create OUT before running it. Do not run it as an ordinary task or count it as adoption.

First check the exact parent graph, check out the left parent cleanly, and perform the real Git merge against the right parent. The script requires both the exact HEAD and MERGE_HEAD. It resolves and stages; it does not commit, publish, invoke H, compile Rust, or run tests. Commit the resolved tree with exactly the left and right parents only after checking all invariants again. Root owns any new H operation and the final qualification.

## Full-record merge rules

Boundary records are keyed by their unique ID, with all non-caller fields preserved exactly. The only mutually changed boundary is `learning_original_owner_command_channel`: its 24 base callers plus three HEAD and five readonly callers become 32, keeping the left order and appending the right-only paths. The 24 left-only and 14 right-only IDs are all retained, and the inventory is checked as an exact Counter against all boundary IDs.

Protected records are canonicalized as complete JSON objects and handled with Counter multiplicity. The result equals `Counter(left) - Counter(right removals from base) + Counter(right additions to base)`. Root adds 14 complete records and removes none. Readonly replaces three complete records and adds eight, represented as three removals plus eleven additions. There is no map keyed by path and no path deduplication. Existing Root record ordering is retained except the three replaced records, whose complete right postimages are appended with the right additions.

The TOML parser handles the mid-file `[authority]` section explicitly, preserving it and all false authority flags. Grouping all boundaries then all protected records would create needless reordering; the executed resolver preserves the original mixed record sequence.

## QA conflict detail

The initial_connection conflict hunk includes two adjacent readonly material-context caller tuples as well as the shared channel tuple. Choosing the left hunk alone loses the two readonly additions. This was caught by whole-AST comparison before publication and corrected.

For the seven existing QA modules, the resolver proves that the left parent differs from base only in the shared caller tuple. It therefore takes the full right-parent AST, modifies only that tuple to the 32-caller union, and proves that all remaining AST nodes match the right parent. The new readonly QA gets the same tuple-only update. All independent mutation functions remain intact.

- `qa/b4-no-bypass/test_original_model_root_source_closure.py`
- `qa/b4-no-bypass/test_original_next_use_command_source_closure.py`
- `qa/b4-no-bypass/test_original_no_update_stage_source_closure.py`
- `qa/b4-no-bypass/test_original_readonly_ready_source_closure.py`
- `qa/b4-no-bypass/test_original_selector_command_source_closure.py`
- `qa/b4-no-bypass/test_original_training_bootstrap_source_closure.py`
- `qa/b4-no-bypass/test_original_training_command_source_closure.py`
- `qa/b4-no-bypass/test_original_training_initial_connection_source_closure.py`

The executed script uses `head_other_ast_matches_base=false` to mean the new readonly module has no left-parent counterpart. The local audit JSON changed only that report field to null before the commit attempt; that metadata edit does not change source or merge semantics.

## Acceptance

Positive ordinary adoption, correct ordinary NoUpdate/fallback, fresh-session C consumption and actual daemon/Root cold restart all remain zero.
