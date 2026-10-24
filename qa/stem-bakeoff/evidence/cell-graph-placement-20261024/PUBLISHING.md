# Publication after the original controller log loss

This supplements the original publication plan. It does not change the frozen
experiment, certify the incomplete ledger, or rerun a graph. Keep the original
full-evidence auditor unchanged; use the separately named partial auditor.

## Complete the three distinct evidence sections

1. **Original primary graph evidence.** Retain the original dispatch, graph and
   environment export, all 30 original request files, all 18 graph owner and
   collection files, reducer launch/stdout/stderr/exit metadata, reduction
   receipts and prediction archives. Keep the original unchanged reporter's
   85,620-byte result, SHA
   `6df19c646c3b610011b138a3f0cc870bc4523d23d5ae1bc2b52f78778dc39102`.
   Its 18-row complete census remains separate from recovery and cost coverage.
2. **Original failed/partial evidence.** Keep `graphs/recovery/b0-A-s0.json` as
   failed and leave the original B/C recovery paths absent. Retain the original
   raw manifest and exactly four existing chunks, every existing wrapper
   receipt, the controller-loss inventory/read receipts, extracted prefix bytes
   and the 45 complete records with original byte ranges. Do not create a file
   at the missing original `raw/<full-SHA>/ledger.json` path. Do not insert
   invented missing records, reconstructed helper spans or zero cost values.
3. **Separate recovery-v2 validation.** Retain the union of the actual per-case
   append-only journal delta archives, including case intents/records/outers,
   raw intents/results/failures, staged large-record chunks and manifests, into
   a new task-owned v2 evidence path. Include source/preparation/protocol/bundle
   hashes, construction metadata, state captures, bounded transfer acknowledgements
   and each per-case archive/manifest. Preserve failed, unknown and unattempted
   cases. Never copy a new v2 record into the original `graphs/recovery` paths.

The current original-partial paths are:

```text
/home/qian-qi/workspace/hepta-cell-graph-evidence-20261024/raw/a8cd6fc298c63d525e8794c00d6e738800898c968b30b8ad52e589ad87807589/
/home/qian-qi/workspace/hepta-cell-graph-evidence-20261024/controller-continuity-v1/recovered-prefix-v1/
```

The new source bundle fixes the v2 namespace. Its exact SHA, not a reconstructed
or newly generated reference bundle, must be recorded with every checkpoint.
New journal files were copied after every case, so the final session-store
snapshot is supplementary rather than the sole surviving raw record. The
archives contain disjoint raw-call ranges: A 0–10, B 11–17 and C 18–24. All
three archives are necessary. Each also has its own `MANIFEST.json` and
after-case state. Retain those under separate case directories when unpacking;
do not overwrite one case manifest with another. A separate local custody check
verified each archive and its actual remote write acknowledgement, every member
hash, and the union of all 59 final checkpoint files/25 call intent-result pairs.
Its result is `66e37f7db07520b8145fe08c03e1dd797e4b4bc7c94074fae92284ed79491ee1`.

## Retain the executed read-only audits

The new partial script only reads existing outputs, runs the pinned original reporter,
and recomputes array reductions/parity and paired scalars. It starts no model,
graph worker, training, Runtime service or primary task.

This audit has already run with the peer-reviewed source
`aee46b227c9bcec695dcffae44e941d674d67a23b0799890240969f2b7529392`, as
job `1a16ddf5c60-1b6abb-4a6a`: exit 0, complete/nontruncated stdout, primary
tensor/scalar pass, prefix integrity pass and original recovery integrity pass.
Its full-cost flag remains false. Retain the actual result
`33824ede8355be4e27786209956329da5e3ce8e8dcba4ab1d5ac0c0a159a6b16`.
The exact executed command below is provided for reproduction; publication
does not require a second run.

```bash
/data/hepta-cell-input-20261024/.venv/bin/python audit_cell_graph_partial_v2.py \
  --source-dir /home/qian-qi/workspace/hepta-cell-graph-benchmark-20261024/qa/stem-bakeoff \
  --dispatch /home/qian-qi/workspace/hepta-cell-graph-evidence-20261024/requests-v1/dispatch.json \
  --graph-evidence /home/qian-qi/workspace/hepta-cell-graph-evidence-20261024/graphs \
  --report /home/qian-qi/workspace/hepta-cell-graph-evidence-20261024/controller-continuity-v1/original-report.json \
  --partial-prefix /home/qian-qi/workspace/hepta-cell-graph-evidence-20261024/controller-continuity-v1/recovered-prefix-v1/complete-prefix-records.json \
  --output /home/qian-qi/workspace/hepta-cell-graph-evidence-20261024/controller-continuity-v1/independent-partial-audit-v2
```

Any future reproduction must use a new output directory. Retain the script's exact source/hash,
targeted test log, independent source review if available, actual native start/
status/read receipts, reporter stdout/stderr, reproduced original report,
`partial-audit.json` and `input-sha256.json`. Exit zero means the declared
partial audit checks succeeded. `complete_original_cost_audit_pass` remains
false even if all 18 numerical graphs pass.

Also retain the separate actual recovery audit script
`audit_recovery_cases_v2.py`, its exact source hash, final state/input file
manifest and JSON result
`c18b3f5b4c2e7978bfccfebb3d1d41835872a85e99c5592762939a153baed6d5`.
It independently verifies the three original-job byte reuses from the full
new per-call journal: 25 native records, 59 file checkpoints and no issues.
Keep the earlier through-B report, which correctly lacks final C qualification.
The original failed/absent/absent recovery snapshot remains separate; the
partial primary auditor checks that snapshot against the actual old paths.

The per-case archives have acknowledged size/hash identities:

| Case | Bytes | SHA256 |
| --- | ---: | --- |
| A | 570,932 | `e5029a8ae54e5c8096d8b810cb208ea5289b8d0cfa044c44931682cf1e17f1ce` |
| B | 340,706 | `93ca89e25dcda67917c6c4893b166d40f74d77a99195e9ab7626c8eacd18ff51` |
| C | 358,659 | `169b45a7da7f7eff9e3d51158708e761a40a9dc55263b27be73a67332c34a52a` |

B's two earlier transport-timeout receipts, observed-absence checks and later
successful bounded upload must all be preserved. Keep C's 42,405 ms copy-cost
receipt separate from recovery and from archive construction/final receipt
publication. C's transfer ran alongside a later native-code build; it is not
a controlled performance sample. Acknowledged final archive custody does not
turn earlier uncertain effects or unmeasured publication costs into zero.

## Build a bounded task-owned archive

Use the graph evidence root and explicitly selected source/review/audit files.
Do not traverse other projects, model caches, raw news corpora, training labels,
or the original retention study. Do not include an archive in its own input
tree. Freeze archive inputs only after the intended evidence writes settle.

The manifest must list every archived regular file with relative path, exact
byte count and SHA256. Reject symlinks or unexpected external paths. Preserve
the original file bytes; an archive may normalize headers/timestamps for
reproducibility while retaining actual event timestamps in the receipt files.
Include all failed and partial files and both original and corrected source
history. Keep original versus v2 files under separate top-level folders.

Keep the archive creation receipt, complete archive size/SHA and any transfer
part size/SHA outside the archive they acknowledge. A final upload acknowledgement
cannot be inside its own acknowledged archive. The remote archive write must be
create-only or verify an existing identical byte sequence; it may not overwrite
the original graph/recovery artifacts.

Before committing to the original graph evidence branch, verify:

- The frozen original adapter, graph owner/protocol, reporter and reducer hashes
  still match the earlier committed values.
- The original recovery remains failed/absent/absent; new v2 outcomes are listed
  separately with actual job IDs, exact old-output checks and their own hashes.
- The manifest and report preserve `4/34` raw chunks, `45/383` complete snapshot
  records and `full_ledger_sha256_verified:false`. The missing sealing tail and
  original post-owner/helper spans remain unknown.
- The README includes all six primary paired differences, the cold API/control
  path versus millisecond inference distinction, heterogeneous host/environment
  limits, own ceilings rather than reservations, and no overall net-benefit or
  intelligence claim.

All known setup, reconstruction, source transfer, new read-only audit, journal
transport and archive/publication costs should be linked to their actual
receipts. They have different scopes and must not be added to nested owner
intervals or presented as a fabricated complete total.
