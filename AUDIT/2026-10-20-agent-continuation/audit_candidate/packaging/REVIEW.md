# 冻结证据包发布前清单

**这里只生成清单、一个 R0 身份索引和打包脚本，没有复制 payload、创建重型压缩副本或执行远端操作。** 原冻结目录保持不变。

- 待选安全 payload：**128 个，5,897,735 字节**；控制清单本身另计。
- 最大选定 blob：**477,165 字节**；硬上限 512,000；发布计划过限 **0**。
- 原文件过限：**13** 个。日志仅整文件 gzip；非日志快照不分片、不压缩。
- 拟发布文本扫描：**0 个候选命中 / 0 个文件**；命中文件整项隔离，发布集合命中为 0。没有打印匹配值。
- OWNERS 的 **84** 个直接引用中，**1** 个未随包；冻结 catalog 全部未随包条目 **27** 个，逐项在 MANIFEST 的 missing_references 中。

## 审核要点

R0_PR_IDENTITIES.jsonl 是单份 1,623 行的完整 PR 身份投影：PR、source SHA、head ref、base ref、recorded base SHA、synthetic merge SHA；默认 head repository 写入 schema，例外逐行记录。它省略标题、人员和检查等字段，不能声称替代完整原始元数据。原始清单 SHA、API 分页出处和字段映射均保留。

原始日志自然 gzip 后，冻结 OWNERS/manifest 的原路径通过 MANIFEST.reference_resolution 映射到 `.gz`；原文 SHA256 仍可验证。冻结文件不重写。外部 Git blob URL 是精确内容引用；动态 API URL 仅说明来源，不是旧响应的永久字节归档。

UI 的原产品 ZIP 只保留稳定 artifact12191530387 URL 和原始 SHA。无稳定来源身份的 initial diagnostic ZIP 不作为产品证据，也不随包。工具安装目录、浏览器/依赖缓存、完整 worktree 和后续 P0/Operations 候选均不复制。

## OWNERS 直接缺引用

| 原路径 | 字节 | 原因 |
| --- | ---: | --- |
| `p5_inventory/snapshot.json` | 4,119,455 | over_hard_limit_nonlog_metadata_not_split_or_compressed；出处与原 SHA 见 MANIFEST |

## 其余未随包 catalog 引用

以下属于原冻结目录的完整 catalog，未静默当作已归档。原 SHA、出处及已保留原始日志等覆盖关系在 MANIFEST 中逐项记录。

| 路径 | 省略原因 |
| --- | --- |
| `cell_p0/dependency_payload.json` | 超过硬限；非日志，不分片/压缩 |
| `cell_p0/logs/job_117826243985.excerpts.json` | 可选副本、检索封装或摘录；未复制 |
| `cell_p0/logs/job_118041065193.excerpts.json` | 可选副本、检索封装或摘录；未复制 |
| `cell_p0/logs/job_118041065193.raw.log.gz` | 可选副本、检索封装或摘录；未复制 |
| `cell_p0/logs/job_118054244669.excerpts.json` | 可选副本、检索封装或摘录；未复制 |
| `cell_p0/logs/job_118054244669.raw.log.gz` | 可选副本、检索封装或摘录；未复制 |
| `cell_p0/logs/job_118059888568.excerpts.json` | 可选副本、检索封装或摘录；未复制 |
| `cell_p0/logs/job_118069436384.excerpts.json` | 可选副本、检索封装或摘录；未复制 |
| `cell_p0/logs/job_118069436384.raw.log.gz` | 可选副本、检索封装或摘录；未复制 |
| `cell_p0/logs/job_118069853019.excerpts.json` | 可选副本、检索封装或摘录；未复制 |
| `cell_p0/source_payload.json` | 可选副本、检索封装或摘录；未复制 |
| `p1_p4_audit/additional_source_payload.json` | 可选副本、检索封装或摘录；未复制 |
| `p1_p4_audit/canonical_source_payload.json` | 可选副本、检索封装或摘录；未复制 |
| `p1_p4_audit/future_source_payload.json` | 可选副本、检索封装或摘录；未复制 |
| `p1_p4_audit/github_snapshot.json` | 超过硬限；非日志，不分片/压缩 |
| `p1_p4_audit/log_payload.json` | 超过硬限；非日志，不分片/压缩 |
| `p1_p4_audit/logs/job_117564830781.excerpts.json` | 可选副本、检索封装或摘录；未复制 |
| `p1_p4_audit/logs/job_117703142266.excerpts.json` | 可选副本、检索封装或摘录；未复制 |
| `p1_p4_audit/logs/job_118223944566.excerpts.json` | 可选副本、检索封装或摘录；未复制 |
| `p1_p4_audit/logs/job_118411015933.excerpts.json` | 可选副本、检索封装或摘录；未复制 |
| `p1_p4_audit/logs/job_118411313757.excerpts.json` | 可选副本、检索封装或摘录；未复制 |
| `p1_p4_audit/remote_source_payload.json` | 可选副本、检索封装或摘录；未复制 |
| `p5_inventory/additional_api.json` | 可选副本、检索封装或摘录；未复制 |
| `pr_inventory/check_runs.jsonl` | 超过硬限；非日志，不分片/压缩 |
| `pr_inventory/dependency_edges.jsonl` | 超过硬限；非日志，不分片/压缩 |
| `pr_inventory/open_prs.jsonl` | 超过硬限；非日志，不分片/压缩 |

## 过限原文件

| 原路径 | 原字节 | 处理 | 发布字节 |
| --- | ---: | --- | ---: |
| `cell_p0/dependency_payload.json` | 928,310 | omit_uncompressed_metadata | 不随包 |
| `p1_p4_audit/github_snapshot.json` | 2,003,917 | omit_uncompressed_metadata | 不随包 |
| `p1_p4_audit/log_payload.json` | 2,829,727 | omit_uncompressed_metadata | 不随包 |
| `p5_inventory/hepta/logs/108436525730.raw.log` | 1,228,666 | gzip_original_log | 129055 |
| `p5_inventory/hepta/logs/109794734555.raw.log` | 1,213,422 | gzip_original_log | 128253 |
| `p5_inventory/hepta/logs/109881374384.raw.log` | 691,634 | gzip_original_log | 61419 |
| `p5_inventory/snapshot.json` | 4,119,455 | omit_uncompressed_metadata | 不随包 |
| `pr_inventory/check_runs.jsonl` | 951,467 | omit_uncompressed_metadata | 不随包 |
| `pr_inventory/dependency_edges.jsonl` | 607,305 | omit_uncompressed_metadata | 不随包 |
| `pr_inventory/open_prs.jsonl` | 1,365,393 | omit_uncompressed_metadata | 不随包 |
| `ui_p0/source-job.log` | 1,470,409 | gzip_original_log | 184966 |
| `ui_p0/ui-gateway-source.zip` | 2,117,670 | external_reference_only | 不随包 |
| `ui_p0/ui-source-diagnostic.zip` | 4,547,316 | excluded_unrelated_unverified_binary | 不随包 |

## 敏感模式扫描

选定文本与解压日志中没有模式命中。规则覆盖常见服务 token、密钥块、credential assignment、Authorization 和签名/凭证 URL；不把有限模式扫描描述成绝对无秘密证明。

## 逐文件 payload 清单

下表列全部 payload；本 REVIEW.md 与 MANIFEST.json 两个控制清单另计，完整控制文件身份见机器 manifest。

| 发布路径 | 字节 | 变换 | SHA256 前 12 位 |
| --- | ---: | --- | --- |
| `audit_candidate/p1_p5/BLOCKERS.md` | 8,936 | copy | `45a4bb54667d` |
| `audit_candidate/p1_p5/OWNERS.jsonl` | 86,444 | copy | `eccbf6ce1d78` |
| `audit_candidate/packaging/R0_PR_IDENTITIES.jsonl` | 477,165 | copy | `6bf4a7994061` |
| `audit_candidate/packaging/pack.py` | 11,354 | copy | `80c4d78b2c20` |
| `cell_p0/README.md` | 7,149 | copy | `2b41ab153916` |
| `cell_p0/SHA256SUMS` | 4,044 | copy | `0e881c1b0da8` |
| `cell_p0/cell-wal-four-paths.patch` | 6,763 | copy | `0080ce403c1d` |
| `cell_p0/github_snapshot.json` | 337,159 | copy | `54f4faae8d99` |
| `cell_p0/handoff.json` | 11,173 | copy | `a0782cc1576b` |
| `cell_p0/log_index.json` | 8,641 | copy | `d08457a7750a` |
| `cell_p0/logs/job_117826243985.raw.log.gz` | 104,003 | copy | `00a273ea736d` |
| `cell_p0/logs/job_118059888568.raw.log.gz` | 27,381 | copy | `13317aa4c031` |
| `cell_p0/logs/job_118069853019.raw.log.gz` | 144,470 | copy | `4b56ea95942a` |
| `cell_p0/rustfmt_check.json` | 560 | copy | `6a1ba3b1a754` |
| `cell_p0/source_projection.json` | 3,327 | copy | `d076cb922ceb` |
| `cell_p0/sources/2909/codex-rs/Cargo.lock` | 418,070 | copy | `17bef7bc25e2` |
| `cell_p0/sources/2909/codex-rs/hepta-control-plane/Cargo.toml` | 676 | copy | `e3aab0b702f8` |
| `cell_p0/sources/2909/codex-rs/hepta-control-plane/src/scope_lane_wal.rs` | 26,123 | copy | `cfd1d6a58f8e` |
| `cell_p0/sources/2909/codex-rs/hepta-control-plane/src/scope_lane_wal_tests.rs` | 10,566 | copy | `c6fdee03df0c` |
| `cell_p0/windows_qualification.json` | 1,761 | copy | `b4743a596f9a` |
| `p1_p4_audit/README.md` | 24,639 | copy | `a4ab6de0e9a9` |
| `p1_p4_audit/SHA256SUMS` | 14,808 | copy | `77d3f4b26e92` |
| `p1_p4_audit/caller_parity_comparison.json` | 1,363 | copy | `f6e97d0e1d9f` |
| `p1_p4_audit/canonical_owner_dag.json` | 213,539 | copy | `b6f2fb819ce7` |
| `p1_p4_audit/findings.json` | 24,161 | copy | `c5d732c6b18d` |
| `p1_p4_audit/followup_snapshot.json` | 437,498 | copy | `7f89b8e8b318` |
| `p1_p4_audit/log_index.json` | 3,327 | copy | `1e05f0225f5b` |
| `p1_p4_audit/logs/job_117564830781.raw.log.gz` | 212,094 | copy | `b907504aed20` |
| `p1_p4_audit/logs/job_117703142266.raw.log.gz` | 7,252 | copy | `64a5b40812f3` |
| `p1_p4_audit/logs/job_118223944566.raw.log.gz` | 82,656 | copy | `5a38485d9119` |
| `p1_p4_audit/logs/job_118411015933.raw.log.gz` | 77,678 | copy | `8703e224b499` |
| `p1_p4_audit/logs/job_118411313757.raw.log.gz` | 81,823 | copy | `818a138761f7` |
| `p1_p4_audit/negative_validator_repro.py` | 5,530 | copy | `4526de211a16` |
| `p1_p4_audit/negative_validator_repro_results.json` | 4,167 | copy | `344c84c76e8c` |
| `p1_p4_audit/source_bindings.json` | 75,061 | copy | `80394eb2441f` |
| `p1_p4_audit/sources/2684/codex-rs/hepta-operator-acceptance/src/cell_split_execution_cli.rs` | 25,235 | copy | `db150bdc03c8` |
| `p1_p4_audit/sources/2684/codex-rs/hepta-operator-acceptance/src/cell_split_execution_owner.rs` | 59,043 | copy | `8a7736079fe7` |
| `p1_p4_audit/sources/2684/codex-rs/hepta-operator-acceptance/src/cell_split_target_host_runtime.rs` | 34,984 | copy | `31335055c1f3` |
| `p1_p4_audit/sources/2695/codex-rs/hepta-ndu/src/group.rs` | 13,547 | copy | `5c680358e812` |
| `p1_p4_audit/sources/2695/codex-rs/hepta-ndu/src/shadow_system2.rs` | 13,845 | copy | `8c795ae8f3ae` |
| `p1_p4_audit/sources/2695/codex-rs/hepta-neuron/src/shared_encoder.rs` | 9,741 | copy | `10ff44905449` |
| `p1_p4_audit/sources/2734/codex-rs/hepta-infer-worker-host/src/neuron_microbatch.rs` | 9,057 | copy | `511322c00398` |
| `p1_p4_audit/sources/2734/codex-rs/hepta-intelligence-eval/src/fenced_holdout.rs` | 12,242 | copy | `da730741b87b` |
| `p1_p4_audit/sources/2734/codex-rs/hepta-intelligence-eval/src/longitudinal_time.rs` | 8,146 | copy | `d455220de2b7` |
| `p1_p4_audit/sources/2734/codex-rs/hepta-intelligence-eval/src/product_runner.rs` | 36,095 | copy | `15e82c5fb2b5` |
| `p1_p4_audit/sources/2734/codex-rs/hepta-intelligence-eval/src/self_evolution_selection.rs` | 27,089 | copy | `0749241ab622` |
| `p1_p4_audit/sources/2734/codex-rs/hepta-intelligence/src/cell_ndu_selection.rs` | 25,839 | copy | `657fc27ef208` |
| `p1_p4_audit/sources/2734/codex-rs/hepta-neuron/src/data_plane.rs` | 36,052 | copy | `56b7ce6462f3` |
| `p1_p4_audit/sources/2734/codex-rs/hepta-supervisor/src/cell_split.rs` | 91,281 | copy | `a597c6e5bf42` |
| `p1_p4_audit/sources/2734/scripts/hepta-cell-split-target-matrix.py` | 15,249 | copy | `f6a2e8c0386e` |
| `p1_p4_audit/sources/2850/scripts/hepta-cell-split-target-matrix.py` | 32,831 | copy | `a392d6ec4b04` |
| `p1_p4_audit/sources/2850/scripts/test_hepta_cell_split_target_matrix.py` | 29,462 | copy | `789ffc1ece09` |
| `p1_p4_audit/sources/2918/CALLERS.toml` | 26,066 | copy | `6ba1e541608b` |
| `p1_p4_audit/sources/2918/codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs` | 6,596 | copy | `86e3f2be9c9b` |
| `p1_p4_audit/sources/2918/codex-rs/hepta-infer-worker-host/src/bin/hepta-neuron-microbatch-qualification.rs` | 9,578 | copy | `2e196c3ee20d` |
| `p1_p4_audit/sources/2918/codex-rs/hepta-infer-worker-host/src/neuron_microbatch.rs` | 19,061 | copy | `805d7a1ac669` |
| `p1_p4_audit/sources/2918/codex-rs/hepta-neuron/src/metrics.rs` | 13,601 | copy | `5de92b54cfbe` |
| `p1_p4_audit/sources/2918/codex-rs/hepta-neuron/src/runtime.rs` | 21,630 | copy | `cb86aa9c2549` |
| `p1_p4_audit/sources/2918/qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json` | 18,469 | copy | `f1531ce896bd` |
| `p1_p4_audit/sources/2920/CALLERS.toml` | 25,965 | copy | `698b65e27d7a` |
| `p5_inventory/REPORT.md` | 17,477 | copy | `4476a5e915ab` |
| `p5_inventory/REPORT_FREEZE.json` | 1,808 | copy | `ef146af651fd` |
| `p5_inventory/hepta/current_source_manifest.json` | 3,693 | copy | `85953b65648e` |
| `p5_inventory/hepta/log_manifest.json` | 1,150 | copy | `036cc5deb112` |
| `p5_inventory/hepta/logs/108436525730.raw.log.gz` | 129,055 | gzip_original_log | `4dd32525b301` |
| `p5_inventory/hepta/logs/109794734555.raw.log.gz` | 128,253 | gzip_original_log | `e22ad1a40bca` |
| `p5_inventory/hepta/logs/109881374384.raw.log.gz` | 61,419 | gzip_original_log | `7d15f6a2845d` |
| `p5_inventory/hepta/logs/109890577459.raw.log.gz` | 1,343 | gzip_original_log | `dc9b95d91b55` |
| `p5_inventory/hepta/logs/111222447293.raw.log.gz` | 4,278 | gzip_original_log | `aab2a595f56b` |
| `p5_inventory/hepta/operations_996_failure_classification.json` | 14,677 | copy | `f88c73684ff1` |
| `p5_inventory/hepta/sources/1272/docs/modules/auth.authbus/PRODUCT_CALLER_CONTRACT.json` | 3,858 | copy | `64038c893e80` |
| `p5_inventory/hepta/sources/1311/codex-rs/hepta-automation/src/model.rs` | 7,617 | copy | `9765d311fa21` |
| `p5_inventory/hepta/sources/1311/codex-rs/hepta-automation/src/scheduler.rs` | 10,594 | copy | `94292337b0c7` |
| `p5_inventory/hepta/sources/996/codex-rs/hepta-memory/migrations/0016_kernel_operation_destination_terminal.sql` | 1,697 | copy | `3a2e61c20804` |
| `p5_inventory/hepta/sources/996/codex-rs/hepta-memory/src/cognitive_store.rs` | 70,512 | copy | `ef1b54636a57` |
| `p5_inventory/host_observation.json` | 330 | copy | `964701a2c159` |
| `p5_inventory/migration_identities.json` | 8,052 | copy | `898311c989bb` |
| `p5_inventory/organ/log_manifest.json` | 237 | copy | `b3d7c0056cc6` |
| `p5_inventory/organ/logs/118122567281.raw.log.gz` | 21,508 | gzip_original_log | `176af709d03d` |
| `p5_inventory/organ/pr210/ui/broker/src/lib.rs` | 36,961 | copy | `82931bd6f751` |
| `p5_inventory/organ/recent_prs.json` | 71,873 | copy | `729c0369f5e7` |
| `p5_inventory/organ/source/docs/HEPTA_INTEGRATION.md` | 9,995 | copy | `55314b700ba6` |
| `p5_inventory/organ/source/docs/VALIDATION.md` | 9,799 | copy | `5add69456230` |
| `p5_inventory/organ/source/kernel/asterinas/kernel/core/src/device/misc/hepta_control.rs` | 9,456 | copy | `3a2dd825cbe6` |
| `p5_inventory/organ/source/kernel/asterinas/kernel/core/src/fs/fs_impls/cgroupfs/controller/cpu.rs` | 42,658 | copy | `b78cf58b0dab` |
| `p5_inventory/organ/source/libs/os-control/API_CONTRACT.md` | 56,355 | copy | `68689e929de4` |
| `p5_inventory/organ/source/libs/os-control/src/native.rs` | 8,844 | copy | `1967c2db5c72` |
| `p5_inventory/organ/source/services/hepta-os/CONTRACT.md` | 13,953 | copy | `0ec2d9c0db13` |
| `p5_inventory/organ/source/services/hepta-os/src/client.rs` | 14,515 | copy | `8669dc6c1e48` |
| `p5_inventory/organ/source/services/hepta-os/src/lib.rs` | 7,492 | copy | `3904ceed5853` |
| `p5_inventory/organ/source/services/hepta-os/src/objective/mod.rs` | 17,623 | copy | `4475f5267ed2` |
| `p5_inventory/organ/source_manifest.json` | 4,561 | copy | `61f4c4ddb499` |
| `p5_inventory/source_manifest_additional.json` | 2,913 | copy | `d449e3a94486` |
| `pr_inventory/README.md` | 7,894 | copy | `f238074a9e1c` |
| `pr_inventory/RUNNING_TASKS.jsonl` | 273,159 | copy | `7e5d6221be20` |
| `pr_inventory/SHA256SUMS` | 1,494 | copy | `829bec01ec5a` |
| `pr_inventory/b4_duplicate_candidates.json` | 25,806 | copy | `cbb932879ed0` |
| `pr_inventory/ci_topology_review.json` | 3,009 | copy | `1ac7546a2d74` |
| `pr_inventory/disk_candidates.csv` | 8,381 | copy | `4bcc16bba04d` |
| `pr_inventory/disk_candidates.json` | 58,988 | copy | `460f6fa62f03` |
| `pr_inventory/important_prs.json` | 109,181 | copy | `c753425f548c` |
| `pr_inventory/main_check_runs.json` | 46,328 | copy | `d9732fa36bc0` |
| `pr_inventory/metadata.json` | 7,575 | copy | `509f7af339bf` |
| `pr_inventory/pr2780_scope_job_117614032937.log.gz` | 96,308 | copy | `20398170f2ff` |
| `pr_inventory/pr2780_scope_log_identity.json` | 598 | copy | `01cf42cda01d` |
| `pr_inventory/pr2780_scoped_evidence.json` | 2,020 | copy | `f0d6f2d15b1e` |
| `pr_inventory/ui_candidates.json` | 3,756 | copy | `991be07a75fd` |
| `pr_inventory/windows_candidates.json` | 40,935 | copy | `e778c64bb62c` |
| `ui_p0/FINDINGS.md` | 17,972 | copy | `d8729ff7b2b5` |
| `ui_p0/browser-153-download.json` | 245 | copy | `d389823a2b67` |
| `ui_p0/browser-153-response-body-loader.cc` | 21,883 | copy | `667ec6672e47` |
| `ui_p0/browser-156-stable-response-body-loader.cc` | 21,883 | copy | `667ec6672e47` |
| `ui_p0/browser-157-response-body-loader.cc` | 22,792 | copy | `979ce76e7042` |
| `ui_p0/browser-cache-purge.json` | 372 | copy | `5a72849eece7` |
| `ui_p0/browser-identities.json` | 2,745 | copy | `3e7bb9355089` |
| `ui_p0/chromium-8508456.json` | 85,327 | copy | `a514ab0b6ffd` |
| `ui_p0/evidence-summary.json` | 6,425 | copy | `4a01940ccc53` |
| `ui_p0/identity.json` | 327 | copy | `568fd12f87e6` |
| `ui_p0/ime.patch` | 29,243 | copy | `694a54d1087b` |
| `ui_p0/no-store-reproduction.json` | 24,679 | copy | `36930f89773b` |
| `ui_p0/platform-before/src/os/web/web.js` | 149,440 | copy | `f2decc893fc7` |
| `ui_p0/playwright-1.64.1-browsers.json` | 1,135 | copy | `2cfd419f71ac` |
| `ui_p0/raw-request-audit.json` | 60,563 | copy | `61b70b66913c` |
| `ui_p0/reproduce-no-store.mjs` | 7,241 | copy | `a6b72b0b4b91` |
| `ui_p0/source-job.log.gz` | 184,966 | gzip_original_log | `adf897a411d6` |
| `ui_p0/ui-build-manifest.json` | 40,152 | copy | `026de9ca6037` |
| `ui_p0/upstream-web-network.rs` | 16,476 | copy | `24dffe35dba1` |
| `ui_p0/upstream-web.js` | 141,816 | copy | `0404897d76bb` |

## 打包与验证

`pack.py` 默认只核对计划及原文件 SHA/大小/扫描，不复制。主协调者审核后用 `--stage DEST --expected-manifest-sha256 <审核的完整SHA>` 写入指定审计 checkout；脚本先验证所有输入和目标不覆盖，再复制。`--verify-package DEST` 可在没有原始大日志的情况下核对发布文件与解压原文 SHA。

脚本不调用 Git、网络、CI 或 PR API。root 后加的动态结果和总 README 不在此清单资格范围内，应单独执行同一 512,000 字节上限检查。
