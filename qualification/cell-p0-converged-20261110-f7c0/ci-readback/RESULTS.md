# P0 maintenance integration: exact-source CI readback

## Scope and conclusion

The first maintenance integration commit **`8c9c51eca0befdaab6cfc12551c14ad9587a5131`**, tree **`f14dfd771c86ef23125e60c388e8367cc8781ab3`**, has two directly verified successful native runs. This report derives its counts from those runs' original logs, execution records and JUnit files. No counts are copied from either parent commit.

| Run | Job | Source | Observed scope | Passed | Failed | nextest skipped |
| --- | --- | --- | --- | ---: | ---: | ---: |
| [42928810231](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42928810231) | [130222044286](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42928810231/job/130222044286), `native` | `8c9c51e` | Ordinary Agentd, learning-artifacts and intelligence-eval libraries | 1,104 | 0 | 72 |
| Same run and job | Same | `8c9c51e` | Seven explicitly selected Root parent cases | 7 | 0 | 908 |
| [42928810298](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42928810298) | [130222044526](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42928810298/job/130222044526), `owners` | `8c9c51e` | Shared automation, neuron and Agentd libraries | 1,134 | 0 | 71 |

All six inspected workflow runs are attempt 1. The two successful runs concern the exact historical commit above. **They do not qualify `72251601928807febae580dbd7754edac20bda10`, any subsequent repair, or the moving PR head.** The GitHub run response's `head_sha` and `head_commit.tree_id` identify the executed source; the nested pull-request head can already point to a newer commit and is not substituted for that identity.

This was a bounded, read-only retrieval: five original ZIP artifacts and six complete job logs were obtained. No CI was started or rerun, no project source was changed, and no training or business task was launched. The scope is engineering qualification, with no claim of independent task efficacy, scientific sample growth, production adoption, or closure of the whole ordinary-caller learning chain.

## Independent Root count and skipped-count interpretation

The daemon artifact contains separate `ordinary.xml` and `root.xml` files. Parsing the XML independently yields 1,104 and 7 test cases respectively, with zero failure, error or skipped elements. Each file matches the byte count and SHA256 in its original summary. The summaries bind the original execution-record hash, source commit, source tree, run ID and attempt. The original test logs independently contain the 1,104/72 and 7/908 nextest summaries.

The Root job log has the actual output line `Root test uid=0` at `2026-11-11T00:22:28.6027587Z`. The launch requires UID 0 and uses `--run-ignored only` with a fixed seven-name filter. All seven names in the Root JUnit exactly match both the expected and observed sets in `root-parent-coverage.json`. The ordinary launch separately requires UID 1001.

The artifact's `root-prior-junit-excluded.xml` is byte-identical to the ordinary JUnit. It is explicitly excluded from the Root result. The fresh `root.xml` is a distinct 2,115-byte file containing only the seven selected parent cases. Nested child test output is not counted as additional Root parent cases.

For the shared run, the original test log reports 1,134 passed and 71 skipped; independently parsed JUnit contains 1,134 executed test cases with no failures/errors/skipped elements. Its source-bound execution record also reports 1,134 passed. The separate Python execution-gate suite reports 15 passed; those are not added to the Rust-library count.

`nextest skipped` denotes tests excluded or ignored by that invocation. The emitted JUnit files contain executed cases and therefore have zero skipped elements. These are different denominators. The ordinary and shared libraries overlap, so their counts must not be summed as distinct independent tests or source tasks.

## Source identity and maintenance state

For daemon run 42928810231, the original artifact records six source cuts: checkout, before tests, after tests, after maintenance, after bins, and final. Every cut records:

- Commit `8c9c51eca0befdaab6cfc12551c14ad9587a5131`.
- Tree `f14dfd771c86ef23125e60c388e8367cc8781ab3`.
- Empty tracked-source status.
- An inventory of 14,322 files.
- Uncompressed inventory SHA256 `b6315a002ae1d3c53ee6829dd13d55b614f952814f14e0bffb5c8a1138e47913`.

All six original compressed inventories were decompressed and their full bytes compared: they are identical. Each uncompressed hash matches its source snapshot. Ordinary, Root and helper-build execution records independently retain the same before/after commit and tree with `dirty=false`.

| Daemon maintenance check | Original command scope | Result |
| --- | --- | --- |
| fmt | `just fmt --base b8e8c6e82abc1479c573f61a5e17d28d581e6cad` | Return code 0; empty log |
| fix | `just fix --locked --offline` for Agentd, learning-artifacts and intelligence-eval | Return code 0; complete 59,168-byte log |
| bins | `cargo check --locked --offline` for those three packages with `--bins` | Return code 0; complete 34,024-byte log |

None of those three command records reports a timeout or output-limit event. Their retained logs match the original recorded byte count and SHA256. `maintenance-summary.json` reports completion with an empty changed-file list; both `maintenance.patch` and `maintenance-postimages.jsonl` are empty. `qualification-status.json` records no failure and completed maintenance. This is source-bound maintenance success for the selected packages, not a claim that all repository CI lanes passed.

For shared run 42928810298, `source.txt` and `source-after.txt` contain the same exact commit and tree. Its original helper custody report confirms unchanged helper identity and source status. Both successful lanes report the same helper executable hash, `26c976816b7e748ecfe1056944211d7bd4eee329111476c0fc7c5bde422e8824`, at 1,439,816 bytes. That is the original CI's custody evidence; the executable itself was excluded from the published artifacts and was not independently downloaded in this readback. The shared-framework lane does not run the daemon fmt/fix/bins sequence.

## Subsequent failures: original diagnostics, not inferred causes

| Run / job | Exact source and tree | Confirmed original failure | Native suite consequence |
| --- | --- | --- | --- |
| [42930233308](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42930233308), job 130226830039 | `0b13cc85f2b602b6c27afa731b2c4a0e1d11075b`; `7c145ecb0acba8e55890e20b3a8cea56b23c3a85` | Helper Cargo build exits 101; E0004 at `hepta-agentd/src/neuron_generation_learning_readback.rs:100:48`, missing `TrainingNoUpdateV2(_)` arm | Ordinary/Root/maintenance step skipped |
| [42930233285](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42930233285), job 130227475305 | Same `0b13cc85…` source and tree | Same E0004, independently present in this run's artifact stderr; helper build exits 101 | Main shared library suite skipped; helper custody check also fails because preparation is incomplete |
| [42930978528](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42930978528), job 130233394425 | `4073268ead64aa1f8303973d37c5c6d73c951061`; `baf7b8d3f189212cc3ed445daf502f8bd5bd645d` | Same E0004, independently present in this run's artifact stderr; helper build exits 101 | Main shared library suite skipped |
| [42930978522](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42930978522), job 130229409114 | Same `4073268…` source; tree from GitHub run metadata | **E0425**, `pending` undefined at `hepta-agentd/src/learning_iteration_recovery_tests.rs:667:9` | Agentd test binary compilation fails before those tests execute; later formatting and attack-proof steps skipped |

The three Linux failure artifacts each contain exactly one numbered compiler error, the E0004 described above. Each is established from its own complete `helpers/codex-hepta-infer-worker-host.stderr.log`, rather than copied from a sibling run. Their source identities are also present in their original source/command records.

The Windows complete job log contains one numbered compiler error, E0425, and states that compilation failed due to one previous error. It contains no E0004. Four earlier nextest invocations passed 15, 2, 3 and 2 tests, respectively; those earlier successes do not make the failed Agentd test build pass. The Windows run has no listed artifact. Its log retains the exact head checkout pin, while its tree is taken specifically from the run's `head_commit.tree_id`; the tree value was not directly printed in that decoded log.

No status or repair success is inferred for later commits. Full diagnostic excerpts with original file hashes and original line positions are in [FAILURE_DIAGNOSTICS.txt](FAILURE_DIAGNOSTICS.txt.gz).

## Retained evidence and hashes

[CI_EVIDENCE.json](CI_EVIDENCE.json) records the checked counts, commands, identities, source cuts, raw-log hashes, diagnostic scope and exclusions. [ARTIFACT_INDEX.json](ARTIFACT_INDEX.json) lists every member of all five original ZIPs by full bytes and SHA256 and maps the retained subset into `RAW_ARTIFACT_RECORDS.zip`.

| Original artifact | Run | ZIP bytes | Verified original ZIP SHA256 |
| --- | --- | ---: | --- |
| 13815599416 | 42928810231 | 6,907,711 | `bbde5ae5af2a03f3e162098ef47ef7164d6c49856eb49d7f2cf3eb6ac29456dc` |
| 13816420861 | 42928810298 | 170,884 | `9d954f43165af5d47356839ddb0eee70677eeca547b1c6e8b1d750b0163e8bbd` |
| 13816578692 | 42930233308 | 1,206,005 | `54fd86482af41434f6f1d9f45dabd82aadef1a651129b13c4a7002eb968bbabb` |
| 13816816091 | 42930233285 | 93,411 | `b6347c6cadd2cb1b3fa354fca3745405c6ea60e898bbb3771e118430cdd2c6d4` |
| 13817627531 | 42930978528 | 93,471 | `f2d373c306783f5dfc36c2e78d738ebea207abe35bf44167c33952bf0e4c6471` |

All five downloaded ZIP byte counts and SHA256 values match the GitHub artifact metadata, and all ZIP CRC checks pass. The small selected archive retains 77 original records without changing their member bytes, including execution/maintenance summaries, source snapshots, JUnit, complete test and compiler stderr logs. Bulky source inventories and helper compiler JSONL are fully hashed and indexed but are not republished; the prior ordinary JUnit excluded by the Root driver is also omitted from the selected archive.

The six `job-*.log.gz` files retain the complete decoded GitHub job logs encoded as UTF-8. The original BOMs and line endings are preserved, including the Windows CRLFs. Both compressed and full uncompressed byte hashes are recorded. `API_CAPTURE.json.gz` retains the parsed run/job/artifact responses used for this report. The package manifest lists all delivered file hashes. None of these retrieval records is a new CI execution or permission to transfer qualification to a different source commit.

### Storage note

The diagnostic excerpt is stored as `FAILURE_DIAGNOSTICS.txt.gz`. Decompression returns the exact original excerpt, including timestamp-line trailing spaces. The complete native logs and original artifact records retain their original hashes. `MANIFEST.json` records this lossless storage transform and the pre-transform delivery-manifest hash.
