# Scoped learning V2: original run records and maintenance evidence

This packet records two actual model runs at `d81cb97c5b01aea0df03d84d40336b25576337de`, their original owner/checkpoint material, and subsequent test-support and formatting maintenance. **Qualification remains HOLD_NO_GO.** The original lifecycle checks pass. The adopted model still answers all four evaluation questions with `no` and answers the next positive comparison incorrectly.

## Source and review boundaries

| Stage | Immutable source | Review |
| --- | --- | --- |
| Frozen Cell/Organ update-scope artifact | `eba4601966388af65f811d31077fabd00886e4e1` | [#5419](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5419) |
| Scoped registration, checkpoint/recovery enforcement, research-owner integration | `d81cb97c5b01aea0df03d84d40336b25576337de` | [#5420](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5420) |
| Checkpoint test-support reuse, before formatting | `8fda2cd1b4e6e052d5dd232d6ba53e45c507eba9` | Maintenance test/lint source |
| Final formatting | `d2ebadca8bb95a7f208bf0538690125acdd784eb` | [#5431](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5431) |
| Exact dependency-name spelling exception | `342fb02346fb1a2f97d684fb1a3ef9042737401b` | Same maintenance PR; evidence parent |

The actual-model source tree is `49829b9efd25251907743d36fd9c87625ae2bdce`. Its test executable SHA256 is `1b71791e45562c7059662001df67e688a67aa679f96e3e79ae0a2e2807eaafd5`. The original compiled nextest archive SHA256 is `c770a7b7187d84c06805629fb530fd6a40192d6715e17a10486e1e662d7386c6`.

The maintenance test tree is `eb059277eaa039d60333394c9e25730a02ce4a98`. The final formatting tree is `5a23c73d908a551631280384474f10944aff88fb`. Native tests and model runs were **not rerun after the final formatting step**. Earlier native results retain their original source identities.

## Two actual model runs

Both native tests performed 10 optimizer steps, one source-task forward call, eight evaluation forward calls, and one next-task forward call. Each used checkpoint profile 2 and the frozen scope. Source tracking recorded 11,218 entries before and after. Both completed with exit 0 and zero automatic retries under the original 60-second test watchdog.

| Observation | NoUpdate run | Adopt run |
| --- | --- | --- |
| Operation | `learning-scoped-v2-d81cb97c-no-update-v1` | `learning-scoped-v2-d81cb97c-adopt-v1` |
| Native test duration | 51.749 s | 52.077 s |
| Exposed evaluation score | Parent 3/4, candidate 1/4 | Parent 1/4, candidate 2/4 |
| Native disposition | `NoUpdate`; retained parent selected | `ResearchExternalTrainedArtifactAdopt`; newly trained candidate selected |
| Next answer to “Is 8517 greater than 8516?” | `yes`, correct | `no`, incorrect |
| Recovery | Learning and generation owners reopened; no reexecution | Owners reopened; hot/cold original readbacks equal; hot forward delta 1, cold delta 0 |
| Durable job | `1a1be737b16-5e21-cd` | `1a1be76691a-5e21-e7` |

The observed resource envelope was CPUQuota 400% and MemoryMax 8,589,934,592 bytes (8 GiB). These records do not establish a separate 0.25-core/2-GiB acceptance claim. Both original jobs reached terminal exit 0 with complete durable output. Unit and cgroup cleanup readbacks are retained in the original owner records and `publication-readbacks.json`.

### Actual Adopt answers

The following values come from the **new d81 run**, with file hashes checked against the original capture index.

| Question | Expected | Parent | Candidate |
| --- | --- | --- | --- |
| Is 4807 greater than 4806? | yes | no | no |
| Is 5208 greater than 5209? | no | no | no |
| Is 6311 greater than 6310? | yes | no | no |
| Is 7402 greater than 7403? | no | yes | no |
| Next task: Is 8517 greater than 8516? | yes | — | no |

The 1/4 to 2/4 change comes from the fourth evaluation answer becoming `no`. The frozen plan explicitly records `independent_evaluation=false` and `prior_tasks_and_outcomes_exposed=true`. These are finite, previously exposed questions scored through a conditional yes/no raw-logit contract. They do not establish generalization, independent evaluation, or broad language-generation quality.

Relevant original member identities:

- `native-adopt-v1/model/evaluate-result.json`: `0caeef63d9e91ab1102ef5d94323c70deb00cbc40c4ddce3ef8c0adb3af69ffc`.
- `native-adopt-v1/model/frozen.json`: `97c738e264ac7da5f3a44a51910f5bd18a780fbe089a4936f341457ae051a625`.
- `native-adopt-v1/evidence/next-use-delivered.json`: `01ecd9eccb0eba80eb0ab87e7478666578f14cb712b958cb383a98403438860b`.
- Selected new candidate artifact: `56d88f2dda61db06f88a96ebed05d29e1a9e2e8d1d02e3f296a8544df743e45c`.

## Archive inventory and integrity

| Archive | Original members | Original bytes | Archive bytes | SHA256 |
| --- | ---: | ---: | ---: | --- |
| `actual-scoped-runs.tar.gz` | 495 | 9,747,511 | 6,306,956 | `2b1088d0730deedaea6dfa6b4f3d89ce84d0d7998128fe69ebaea487bfe4ba24` |
| `maintenance-records.tar.gz` | 49 | 6,262,096 | 6,057,750 | `c83e9437b9fc66a7ece56d61cd058733da0133ef138cc473640341379db9b645` |
| `local-validation-records.tar.zst` | 170 | 21,932,642 | 3,874,652 | `286109d276827553c32b40c749441353600910de516a02bcb25fe3cc2aaf98c8` |

The corresponding `*.index.json` files record every member's relative path, byte length and SHA256. All archive members were read back and compared with their indices. Original files were hashed again after capture and remained unchanged. `archive-verification.json` independently reads all 495 actual-run members, verifies names and hashes, compares them with the original files, and derives the displayed answers from the original JSON.

The 495-member archive contains the complete enumerated `native-no-update-v1`, `native-adopt-v1`, and `archive-preflight-v1` run directories: training artifacts and receipts, raw model outputs, owner observations, checkpoint bytes, native test commands/stdout/stderr/JUnit, and original SQLite files with their recorded WAL/SHM companions. The five SQLite-related files were captured and verified as bytes; capture did not open a database connection.

This is a run-record packet. External base-model weights and the entire external execution environment are not bundled. Frozen plans retain the external material and source pins. The two adapter artifacts are retained. The 54,118,647-byte compiled nextest archive is intentionally omitted from the source evidence; its original content inventory, executable identity, metadata and upload receipts are retained.

## Original validation history, including failures

The local archive preserves original bytes from four groups: 110 earlier Hepta validation files, 30 material/probe files, 10 model-owner readbacks, and 20 local maintenance records. It retains both raw and originally compressed logs, all source inventories, command records, preparation failures, and historical staging descriptions. Historical staging READMEs describe their time of writing; this README states the final packet status.

| Original observation | Source / scope | Outcome |
| --- | --- | --- |
| `native-final-06` | d81; artifact, Agentd-learning and original generation-owner selections | 151 passed; 729 unselected/originally ignored; 0 retries; 26.207 s test phase |
| `native-final-05` | Same d81 source and selection | 91 passed, 60 failed; exit 100 |
| `strict-lint-d81-01` | d81, all targets | Exit 101; unchanged guarded-acceptance example warnings |
| `strict-lint-d81-02` | d81, lib/tests | Exit 101; newly duplicated checkpoint support module |
| `fmt-check-d81-01` | d81 | Exit 1; formatting differences |
| `native-checkpoint-01` | 8fda, local maintenance attempt | Exit 101 before tests; ENOSPC while creating a compiler temporary directory |
| `native-checkpoint-02` | 8fda, remote checkpoint selection | 11 passed, 757 unselected; 0 retries |
| `scoped-fix-01` and `strict-clippy-01` | 8fda | Passed; tracked source unchanged |
| `scoped-format-01` and `scoped-format-check-01` | Format overlay subsequently committed as d2eb | Passed; nine Rust files formatted |

The first `native-final-05` failure was `Host(CheckpointMismatch)` in `current_withdrawal_and_revocation_refuse_new_learning_observations_and_recovery`. Later failures include ENOSPC/StorageFull. The later storage failures do not establish the cause of the first checkpoint failure. Follow-up 06 used the same source and test selection with explicit `TMPDIR=/workspace/scratch/ht-ac851-06`. A resource record originally labelled “during” was collected after the test summary; the accompanying after record preserves that limitation.

The 11 maintenance checkpoint tests are a subset of the earlier 151-test selection. They must not be added to 151 as new distinct tests. The 8fda source manifest before and after native/fix/strict-lint checks is `073ba6485d2b14cbd037113e7def491902cfb32a3bccdb4cf93483ed98ca4505`. The post-format manifest is `896d242c5e166b5b50eca6254fb2fa4f0b422d63ca84a856b5d0fadf8ed88995`.

### Exact dependency-name CI correction

Hosted codespell job `128983262713` reported only four occurrences of the legitimate dependency name `inout` in earlier retained raw build logs. The one-line follow-up `342fb02346fb1a2f97d684fb1a3ef9042737401b` appends exactly `inout` to `.codespellignore`. It changes no original log, directory exclusion, Rust lint allowance or qualification rule. The original command `codespell --ignore-words .codespellignore --skip ./.git` passed over the full isolated tracked source with the same codespell version 2.4.3, in 10.779 seconds, exit 0, zero retries, and a clean unchanged source before and after. The resulting tree is `6cf4ebb191ef7142b9dd11d51d086a6139be895a`. Original hosted output, the exact byte change, and the new command receipt are separate files in this packet. This local check does not claim a hosted rerun has completed.

### Workspace interruption and recovery

The local execution environment temporarily disconnected during evidence transfer. At that time, `maintenance-records.index.json` correctly recorded the local ENOSPC originals as `OBSERVED_BUT_RAW_NOT_TRANSFERRED`. That original capture has not been rewritten. The environment then recovered; `local-validation-records.index.json` records `RAW_RECOVERED_AND_ARCHIVED_AFTER_WORKSPACE_RECONNECTED`, preserves those originals, and verifies their hashes. No model run or test was restarted to create this recovery record.

Capture-control timeouts were reconciled with their original idempotency keys. `capture-control-readbacks.json.gz` retains the original responses, terminal reconciliation and maintenance capture status. Two incomplete archive transports were explicitly aborted before commit when switching to a complete source-bundle transfer. These transport operations do not change the model runs' zero-retry observations.

The initial unpublished evidence candidate retained a capture command and hosted output as plain text. Its spelling/whitespace checks reported an original command variable and original hosted trailing whitespace. Those two records are now deterministic gzip files with decompressed lengths and hashes in `raw-record-encodings.json`. The original bytes, initial check output, and the first blob-check invocation missing its required allowlist argument are preserved in `evidence-preparation-records.tar.gz` and its index. No extra spelling exception or directory skip was added.

## Qualification limits

The native research owner, original checkpoint codec, original generation actor and original learning signature verifier were exercised. The Python worker was restarted and the native owner/Fleet lifecycle was recreated. `native_daemon_os_restart=false` and `independent_operator_custody=false` remain explicit.

Both native results retain `production_activation=false`, `production_final_use=false`, `production_root_capability=false`, `original_parameter_v3_qualified=false`, and `product_ope_qualified=false`. Research keys and custody remain in use. This packet establishes neither production activation nor a payment, improvement-bonus, or chainwork entitlement.

The implementation's Cell/Organ scope protection is an identity-level contract. The packet does not claim universal tensor verification or a complete cost qualification for every legitimate shared-weight, low-rank, routing, caching, batching or distillation implementation.

## Handling and repository policy

Credential/private-key byte patterns and named secret JSON fields were screened during capture; no member was excluded. This bounded scan is described in the capture scripts and control records. `sensitive-scan.json` records the final archive scan. No original file is normalized or rewritten inside an archive.

All three large archives exceed the repository's default 500-KiB blob threshold. The evidence commit adds exact SHA256-and-path allowlist entries for these fixed bytes. Per-member indices and raw control records are mechanical evidence data. The evidence stage changes no Rust source and is kept separate from the implementation and maintenance stages under the repository's change-size guidance.
