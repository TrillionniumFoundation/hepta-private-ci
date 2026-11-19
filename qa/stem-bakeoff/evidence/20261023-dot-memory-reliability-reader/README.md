# Current-publication admission, source isolation, and one bounded Reader failure

## 中文结论

本分支保留两项已验证的可靠性修复，以及一次严格按预设规则判失败的代码 Reader 开发尝试。
修复关闭的是直接 TCP 读取旧参数、来源祖先跨分割及旧数据绕过等确定场景，不证明未来任务优势。
Reader 成功加载并生成，但答案不满足严格 JSON 和唯一编辑目标要求，没有应用或执行候选补丁。
这是从固定 a26 基线导出的隔离研究分支，不覆盖、合并或部署其他并行分支。

## Exact scope and concurrent work

Source baseline: `a26aeb74cf63c7489deb5ece7e2b9a86e5697748`.
Two locally tested stages, published as separate commits with identical trees:

1. TCP current-source binding: local `62bfc3a8a258906f2202db4fcd891064f0d1f18c`, tree `049762fab499820526f316da9154ffa36287c23a`.
2. Source-component isolation: local `a1e836a6ce2d5dec558076bb2d69f14fa4f6b08e`, tree `2162fdeb29507365e0e472f80ab6f78a137bf096`.

At the publication check on 2026-10-23 14:54 UTC, the latest program report was
[#3578 at 429894ac](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3578).
Its six critical authority/fence/server and dataset/training/trial implementations
were fetched and byte-compared with a26: all remain identical. Its 55 changed paths
relative to a26 have no intersection with these 13 source changes. Neither defect
fix is therefore supplied by that stack. This branch deliberately preserves the
exact tested a26-derived source instead of implying validation on newer d61
process-isolation code. Integration into that stack remains untested and is not
performed by publication.

## Reliability changes and observed tests

- A source-bound authority verifies the current epoch, manifest and roots of a
  parameter publication. Conflict or any new event invalidates an old placement.
  Workers durably latch the latest revocation frontier **before** rejecting a
  stale/unavailable binding. Clean rebuild/new publication, migration and restart
  remain admitted in their tested current-state cases. Standalone withdrawal-only
  authorities retain their documented behavior. Trusted configuration must retain
  source-bound mode; arbitrary configuration downgrade is not qualified.
- Conservative source components bind declared causes, failed/fixed commits,
  original failure/commit evidence and exact repair-patch identities. Components
  propagate through time partitioning, candidate admission and fission. Crossing
  a cutoff purges the whole component. Run creation plus attempt evidence is
  distinguished from late updates and missing provenance. Legacy dataset schema
  and invalid census/partition ancestry fail closed at load time.
  Conservative overmerging is possible; this is not semantic near-duplicate
  detection or proof that an event was never previously seen.

Recorded baseline: 39 mechanism methods pass. Final scoped system: 51 distinct
methods (26 service, 20 domain, 5 TCP); codec/router/population regression: 73.
Independent final-byte verification reran 9 overlapping methods successfully;
these are **not** nine extra independent experiments. Source hashes were unchanged.
The original red results and an intermediate repair that incorrectly failed to
persist withdrawal state remain in the archive; they were not overwritten.

Known-incident executor self-test: unchanged source fails, incomplete repair fails,
complete repair passes, in three isolated old-source checkouts (84.804 seconds
total). These patches were known development controls, not model-generated repairs
or an unopened task cohort. The first launch failed because `/usr/bin/time` was
absent; that observation is retained separately.

## Bounded Reader attempt: negative result, no answer repair

Official model: `Qwen/Qwen2.5-Coder-1.5B-Instruct`, Apache-2.0,
revision `2e1fd397ee46e1388853d2af2c993145b0f1098a`.
Weight SHA-256: `c1b9b30e907950516ba3c646bdf570d8084c25a6410a0cdca80cf04b11bc13a8`.
All nine weight/config/tokenizer/license file hashes are in `acquisition.json`.
No weights are included here. Native Transformers loading used
`trust_remote_code=false`, local offline generation and BF16 CPU inference.

A frozen single known-development producer-clock incident was selected before
loading. The prompt contained original public source and symptoms, not the gold
patch, repair-ID answers, evaluator tests or a formal holdout. One greedy attempt
used seed 19031, prompt cap 6144 tokens and output cap 1536. Limits were one model
process, two numerical threads, 30 minutes, 6 GiB process-tree RSS, host-available
memory guard and disk/asset guards. No guard was exceeded and no retry occurred.

The baseline ran 11 tests, 7 pass and 4 fail. The model emitted 50 tokens from a
2742-token prompt: Markdown-fenced JSON requesting replacement of
`previous_seen=True` with `previous_seen=False`. The exact old string does not
exist. Strict JSON admission failed and the intended edit target also had zero
matches. The output was not stripped, corrected, reapplied or executed. Baseline
and candidate source files remain byte-identical. Candidate tests were not run.
This proves local loading/generation feasibility, **not** a qualified common
Reader, a strong RAG baseline, universal model incapability or repair advantage.

Measured costs: acquisition/hashing 92.311 s; source/prompt preparation 0.000482 s;
model load 4.484 s; generation 112.058 s; cold Reader child 125.597 s; baseline tests
including launch 0.202 s. Nonoverlapping measured stages total 218.110 s;
wall through review/decision 353.893 s; summed child CPU 252.330 s. Sampled peak
process-tree RSS was 4,355,596,288 bytes (distinct self-rusage maximum is recorded).
No training updates occurred. The original protocol, prompt, tokens, raw output,
launch and resource receipts, baseline tests and failure decision are retained.

## Current evidence crosswalk, not retroactive credit

By 2026-10-23 14:56 UTC, the separate original lifecycle package
[#3570](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/353f1e37641f158346f188c848f4ba6329368dfa/qa/stem-bakeoff/evidence/20261023-typed-cell-lifecycle/README.md)
was verified read-only: archive SHA-256
`acd7835de3b37b1768a7dca60f1b02b5d2175099c1c4650ce132ca28625b3aa2`,
452 manifest members, 103 a26 and 107 d61 source files matched pinned Git bytes.
Raw scores independently recompute to fresh adapter 9/9, disabled 0/9, shuffled
0/9, corrected 8/9, withdrawal replay 8/8. Four training receipts total 800 updates
and 49,400 input tokens; 14 successful model-child receipts are present. Declared
engineering and parameter gates are 19/19 and 6/6. This closes the terminal
execution/evidence-recovery wait for **d61**, not complete correctness: retained
`case_05` answers `purple` instead of `white` after correction. The earlier a26
exit-137 interruption remains a failed/incomplete attempt. Hosted 43-method
mechanism checks are separate from actual pretrained lifecycle execution.
These results do not test this branch's two new fixes. No model was run by this
verification, and it is saved-byte consistency, not independent-host attestation.

The [original a26 domain result](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1da7ad2837e4545c72c68aaccbf85a0d5fe222f8/qa/stem-bakeoff/evidence/20261023-memory-domain-development/README.md)
remains 3 historical known repair IDs, zero validation/future cases, and exact
retrieval winning its registered quality tie by deployment bytes. Historical
population single scores 45/64,43/64,40/64 versus guarded split 2/64,0/64,0/64
are not replaced by subsequent exposed-cohort routing diagnostics. The latest
program report links those newer diagnostic artifacts separately; this package
neither reruns them nor calls them future qualification.

Still open: correction retention reliability beyond the finite gate; a competent
common Reader/executor and strong answer-retrieval baseline; genuinely independent
future incident sources and sealed evaluation; same-total-budget split/connection
benefits; long-term recovery and actual multi-physical-host behavior. A new Reader
attempt needs a separately frozen development protocol and full costs, not repair
of this failed answer. No further model trial was launched for this publication.

## Evidence and reproduction

`development-evidence.zip` contains 80 explicitly scoped payload files plus a
SHA-256 manifest. `evidence-index.json` records all members. Archive SHA-256:
`f29c400c7a12cbb90ae7ae690c6727a03196d417ba344da50c5186d6c95edfb9`
(130,896 bytes). It excludes weights, credential/state databases, user chats,
internal coordination and stale status prose. Original local paths in receipts
are provenance, not service endpoints. See `REPRODUCE.md`; reading/verifying the
archive requires no model execution. Publication grants no production promotion.
