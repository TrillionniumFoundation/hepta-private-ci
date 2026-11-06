# r28 原四包门：完整闭合 PASS

**source52 的原 Python32、四包 strict、四包完整测试均自然退出 0；科学 HOLD、权限 DENY_ALL 不变。** 本组绑定 commit `1e0910becc37383e6d17ecf861ea844fd07d8862`、staged tree `211f15baff19095e8c98bcea2b0ed99ca2270ade`、195 个变更路径（181 Rust＋14 other）。原生 HEAD 仍为 framework `bef6fa7645df9df12b69fda499e97eed25de6c75`；已注册对象身份不冒充 checkout。

| 原阶段 | 原返回码 | 原进程总秒数 | 实际结果 |
| --- | ---: | ---: | --- |
| Python runner | 0 | 4.025784969329834 | 32 项、0 skip、OK；unittest 自报 3.921 秒 |
| 四包 strict | 0 | 89.19241714477539 | 原 locked / -D warnings 命令及源码双锁守卫通过 |
| 四包完整测试 | 0 | 347.58449029922485 | nextest 52.852 秒；1564 unique 全 PASS，0 FAIL、0 TIMEOUT；另报 3 skipped |

| Package | PASS |
| --- | ---: |
| codex-cli | 652 |
| codex-exec-server | 524 |
| codex-network-proxy | 220 |
| codex-external-agent-migration | 168 |

完整原日志按 Summary 之前的 binary/name 唯一 ID 重解析，严格等于原 1564 个 baseline ID；baseline 仅在执行后验收，未作为 filter。完整日志见 [native-source52-project-r28-tests.log.gz](original/evidence/native-source52-project-r28-tests.log.gz)，原逐例结果见 [tests-test-results](original/evidence/native-source52-project-r28-closed-test-results.json.gz)。Starting 原报 49 binaries，实际结果行涉及 47 个 binary ID；两种统计分别保留，不据此推断哪些例被跳过。原 3 个 skip 仅保留原总口径，不构造逐例 SKIP 记录。

## 历史失败与本轮结果

原 r26 的两个 wildcard 测试，以及原 r24 的三个失败 ID，在本轮都有实际 PASS 行与耗时；[PRIOR-FAILURE-TRANSITIONS.json](readback/PRIOR-FAILURE-TRANSITIONS.json) 逐项绑定旧失败原块、旧源码和新结果。旧 r24/r26 的工程失败保留，source52 先前 apply/launch-only 快照中的 null 字段没有被追写。

## 原件和复算边界

- [CLOSURE.json](CLOSURE.json) 与 [INDEPENDENT-READBACK.json](INDEPENDENT-READBACK.json) 是本组新读回。
- [checkpoint-r28-closed.tar.gz](checkpoint-r28-closed.tar.gz) 原样保留 295 regular 成员、294 条 INDEX，包括完整 195 源码、原双锁、26 gate 原件＋terminal、5 controller 原件、完整 runner、baseline、apply/lock 前置和原始错误历史。源码只保存在 archive，不另复制源码树。
- [ORIGINAL-MEMBER-MAPPING.json](ORIGINAL-MEMBER-MAPPING.json) 覆盖全部成员。大 UTF-8 文本用 mtime=0 gzip 精确保留，相同大原字节可映射到一份附件；所有源与目标 pins 在 [SOURCE-DESTINATION-MAPPING.json](SOURCE-DESTINATION-MAPPING.json)。
- gate controller 的 stdout 为 8309 B，stderr 为 0 B。原分块 size 是读取时总流长度，chunk 长度按 next_offset−offset 核验；[CONTROLLER-OUTPUT-READBACK.json](readback/CONTROLLER-OUTPUT-READBACK.json) 保存连续性、text/hex 和最终 seen/stored 证明。
- export-preparation/ 保留未执行的 v1、v2 和单点修正读回；root-gate-authorization/、gate-binding/、root-export-authorization/、export-binding/ 保留原授权和实际绑定。唯一 exporter `1a1b1ff192d-fc05-7bf0` 的自然 0 只表示归档成功；原测试门为独立 `1a1b1e9bee0-fc05-7b7c`。
- 源码模式按原 manifest 的 Git mode 绑定；tar mode 是传输权限。完整 Git 仓库离线重建不属于这份新 reader 的声明范围，当前树身份来自原 manifest 和 native 多阶段完整守卫。

本组不读取 r29 活动内容、不提供默认工作区或最终 fix/fmt 的通过结论；没有新 Rust、format、metadata 或 native 执行。共享文件系统 free_bytes_after 原样保留，不折算成单任务资源消耗。测试机制通过不等于真实模型效果、retention 或科学资格通过。

纯本地附件复核：`python3 verify_and_assemble.py --verify-only --output <本目录>`。
