# source52：单叶 fixture 修复、实际 apply 与 r28 启动快照

本组封存 source52 commit `1e0910becc37383e6d17ecf861ea844fd07d8862`、tree `211f15baff19095e8c98bcea2b0ed99ca2270ade`。source51 的原 194 条清单逐行保留，新增既有仓库叶 `codex-rs/network-proxy/src/runtime.rs`，共 **195 路径＝181 Rust＋14 其他**；准备范围仍为 26 Rust owners、27 CI selectors。

## 分开的事实层

| 层 | 本组记录 |
| --- | --- |
| 修复与静态审阅 | 仅四个 hostname pattern/list-update fixture 显式启用原有 allow_local_binding；101 个原 assertion token、独立默认配置循环及真实地址保护测试保留。没有改生产默认或公共 helper。 |
| 原 r26 结果 | source51 原门仍 FAILED100：1562 PASS、2 FAIL、0 TIMEOUT，3 reported skip。实际 NotAllowedLocal 断言不证明具体 DNS 回答或耗时原因。 |
| Git 注册 | 四层原 direct-tree 和派生对象均独立重算，实际 Git commit API 与预测 tree 完全对应；不是 native checkout HEAD 声明。 |
| 原实际 apply | job `1a1b1e474a3-fc05-7b5b`；三个原 Git 命令和自然外层均退出 0，195/双锁/HEAD 守卫通过。native HEAD 仍为 `bef6fa7645df9df12b69fda499e97eed25de6c75`。 |
| r28 启动 | job `1a1b1e9bee0-fc05-7b7c`；只保留启动授权、冻结 runner、上传和 launch 原件。阶段结果、测试计数和终态全部为 null，后续闭合结果不回填此快照。 |

历史 PLAN、provisional manifest、registration 和 static review 内的 `native_applied=false` 等字段按原字节保留。较晚的真实 apply 由 [CLOSURE.json](CLOSURE.json) 与 [INDEPENDENT-READBACK.json](INDEPENDENT-READBACK.json) 单独绑定。

## 原件入口

- [五成员原输入包](source52-preparation/source52-apply-input.tar.gz)：43,267 B，SHA256 `9c7a414899bd05d1e70b9a6cbac64eef9dda552f8e56c904ee9f8e21ab37d6cb`，已登记 Git blob `eefc9ec94d7c5a0074eaa35788b3fbe670314420`。逐成员原字节、原 tar modes 与 Git source modes 分开核对。
- source52-preparation/：预计计划、原四层 trees、实际注册 API、195 清单、两份 root 授权与 approved scripts。
- native-apply/：25 份原 native evidence＋6 份 controller 原件，以及完整原读回/传输准备材料。
- r28-launch/：仅四份启动输入；没有收取 initial-process-status、process-read、Python/strict/tests 的结果或日志。
- reviews/、apply-preparation/、apply-binding/、r28-preparation/、r28-binding/：原静态与 bound 审阅，不作为执行通过证据。
- [SOURCE-DESTINATION-MAPPING.json](SOURCE-DESTINATION-MAPPING.json) 覆盖所有来源；大块相同准备副本可共用原字节目的地，根授权及实际 apply 原目录完整保留。没有重新包装 source51 或 r26 archive。

`python3 assemble_attachment.py --verify-only` 仅核本组 manifest 和映射字节，不执行任何附带 runner、Rust、Git、metadata 或 formatter。**science HOLD / authority DENY_ALL 不变；apply 与 launch 不授予工程测试资格。**
