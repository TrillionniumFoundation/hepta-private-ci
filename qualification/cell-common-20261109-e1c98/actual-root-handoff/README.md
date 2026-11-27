# 实际 Root sealed handoff 与 scope 冷恢复：两个组件用例通过

同一精确 f070 源码的两个原始 ignored tests 已在实际 `euid=0` 下执行并通过。scoped 用例内部覆盖 Cell 与 Organ；legacy 用例验证原 schema-1 路径。**这证明原 Root storage/transport 的组件行为；fixture 的 learning metadata 和 writer proof 仍为 synthetic，未建立部署后的独立 owner、非 Root consumer 或完整普通 P0。**

| 身份 | 绑定值 |
| --- | --- |
| 运行时 commit | `f070113bb61cda492d2668b3afbbcda13e11fa52` |
| 运行时 tree | `068b6a7749e94d7335c826d6c43c19198e02cc24` |
| durable job | ai395 `1a1c04825b9-5e21-9aa`，succeeded / exit 0，无 timeout 或 retry |
| source archive | 91,972,209 bytes；SHA-256 `36c55cbff0d7320d0df010e13d76a8a03a7669e6a54e01f81baf372b5ecacfc9` |
| nextest archive | 90,922,965 bytes；SHA-256 `a439bbb5bdc4a8d36f1a34495033de2d94d65acf6fe0b665d4a654a3ab8f7244` |
| controller | 解压后的 SHA-256 `8d81e563e4af9e146dd0227f25015d51f67d3af1c80587ed6784d0286bcf7303` |
| 冻结计划 | SHA-256 `20f345d3023f45b6a16481900733aaa25f9d2cc230b67eaab979d48d4c639880` |

归档复用实际模型 preparation 002 的同一个 archive，先核对四项本地 native gate 全部成功、模型 job 994 已终局，再顺序执行本组件。没有重新构建或运行额外测试。完整输入与工具 pin 见 [PLAN.json](PLAN.json)、[preparation](MODEL_PREPARATION_RESULT.json)、[tools](MODEL_TOOLS.json)，模型终局前置见 [原命令记录](MODEL_TERMINAL_RECORD.json)。

## 实际执行

原 `just test --archive-file` 经仓库的 `run-nextest.py` 调用 Nextest，使用独立 `--workspace-remap`、`--extract-to`、`--run-ignored only`、`--retries 0`、`--no-tests fail`、`--test-threads 1`，filter 只选下面两个原用例。完整 argv 和环境见 [RESULT.json](RESULT.json)。

| 用例 | 结果 | testcase 秒数 |
| --- | --- | ---: |
| `root_learning_scoped_sealed_pin_preserves_scope_on_cold_reopen` | PASS，内部依次验证 Cell、Organ | 0.025 |
| `root_learning_sealed_pin_and_dedicated_uds_recover_original_checkpoint` | PASS，legacy 路径 | 0.014 |

[原 JUnit](root-handoff.junit.xml) 记录两个 testcase，均无 failure、error 或 skipped 元素。原 Nextest 摘要为 **2 passed / 852 skipped**，并过滤其余 7 个 binary；852 是 archive 的过滤计数，不能计为额外通过。Nextest 本次测试窗口为 0.042 秒。

测试经过真实的 Root CAS 文件/fsync、sealed memfd/SCM_RIGHTS、实际 pidfd、Root peer 身份和原 checkpoint client。scoped 用例记录原 checkpoint、推进 Experience、关闭 owner/channel 后重新打开原 store，拒绝不同 source-run、legacy reopen 和替换 update-rule，并比较 retained inode、owner、mode、bytes 保持一致。

服务端与消费者都在同一个 Root 测试进程。此次没有 daemon OS restart，也没有训练、评价、模型执行或普通 ObjectiveStart；不能把 checkpoint owner reopen 写成整个普通 daemon 已恢复。

## 私有目录与原检查

所有特权写入位于新建的 mode-0700 `/var/lib/hepta-common-e1c98-root-test-f070113b`。原检查要求每级 ancestor 都由 uid 0 所有且禁止 group/world write，因此未使用 `/var/tmp`，也未改变任何原有目录权限。[ANCESTORS.json](ANCESTORS.json) 记录 `/`、`/var`、`/var/lib` 实际均为 root:root、0755、非 symlink 的目录身份。

source/archive/tool 复制后再次核对 pin，`CARGO_HOME`、target、TMPDIR、cache、config、data 和 archive extraction 都指向新私有目录。Cargo 使用原准备阶段核验的真实 toolchain binary，不经过用户 rustup shim。原 `/home/qq` source 的 Git 身份前后干净且相等；私有 source 副本原文件字节不变，只增加 `codex-rs/target/nextest/local/junit.xml`。

Root 原件仍留在该私有目录。它们通过已结束 controller 的 stdout 显式导出，读取时核对 uid 0、0600、长度和 SHA；本目录是审计副本，不是新的 Root capability。传输链与原文件身份见 [ROOT_FILE_EXPORT.json](ROOT_FILE_EXPORT.json) 和 [MANIFEST.json](MANIFEST.json)。

## 成本窗口

| 窗口 | wall 秒 | child CPU 秒 | child peak RSS KiB |
| --- | ---: | ---: | ---: |
| 外层准备、复制、校验和执行命令 | 7.773184 | 7.726606 | 71,984 |
| 内部 just/Nextest 命令 | 0.426743 | 0.417438 | 见原 RESULT |

内层窗口包含在外层之中，不相加。外层资源限制为 200% CPU、4 GiB memory、300 秒进程预算，原 Nextest watchdog 保留；能耗与金额仍未知。[外层 command](root-handoff-f070-v1.json) 与 [durable 最终状态](PROCESS_FINAL.json) 保存真实终局，全部原日志均以原封 gzip 保留。

本组件结果不改变 P1–P4 的 HOLD，也没有补齐普通 provider、真实 stage-owner/CURRENT/NextUse 组装或独立签发材料。完整 P0 的剩余代码和材料见共同候选主报告。
