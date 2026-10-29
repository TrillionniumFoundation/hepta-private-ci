# V10 原生运行结果与源码验证

## 验证结果

**原生验证成功完成。** [GitHub run 40909855139](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40909855139) 的 job `123574545575`、attempt 1 为 success；实际测试提交为 `4131172a07fdf5bf5fe84f0397800bf900248ab8`，tree 为 `6de01a5c1158b90d5e7db9cd18fc3bef36cfa8c1`。这证明限定实现完成了实际运行，不代表研究比较取得了通用优势。

| 验证层 | 实际结果 | 口径 |
|---|---|---|
| Python CI 驱动边界检查 | 11 项通过 | 证据包、请求、路径等驱动行为；不属于模型质量样本 |
| 十个相关 Hepta package 普通 Rust 测试 | 969 passed、31 skipped | 使用 `just test`，retries=0；JUnit 含 969 个运行 case |
| Actual 生命周期 | 精确选中的一个 parent 通过 | Nextest summary：1 passed、242 skipped；parent 内启动五个 owner 进程 |
| 原参数／更正训练／删除重建的 Rust parity | 16、16、15 行均通过 | 固定绝对容差 1e-4、相对容差 1e-5；含 raw logits、margin、typed 值与来源身份 |
| 原始证据完整性 | 343 个 regular files 全部匹配摘要 | 解压合计 14,171,333 字节；不重新执行训练或模型 |

普通测试的 nextest wall 为 106.968 秒，actual parent 为 29.760 秒、actual suite 为 29.762 秒。包含构建／启动的 actual 命令为 68.314534 秒；整个 verification wrapper 为 691.088818 秒。这些范围不同，不能相加或互相替代。普通 App Server 构建为 202.890004 秒，普通测试编译与运行命令为 381.551288 秒。[原始收据](../memory-cell-v10-ci/evidence/native-attempt-04/receipt.json)；[完整 job 日志](../memory-cell-v10-ci/evidence/native-attempt-04/JOB.log)。

验证前后 tracked source 均干净，保护源清单未变，缺失必需收据列表为空；该 verify 没有执行 fix、format 或旧 held 评估。完整研究矩阵独立运行，未在 native CI 中重跑。

## 原始产物与恢复

原始 GitHub artifact ID 为 `12913009976`。ZIP 为 1,394,087 字节，SHA-256：

```text
0fd75c4e1216f5e5ff302a81506f16d36dd2cc66c158f1a6f980638238d9199e
```

内部 `memory-v10-evidence.tar.xz` 为 1,293,916 字节，SHA-256：

```text
5313231c09d852a66b1d2035790656e148e8b3ca4f6654fa713a135cce38037c
```

原始 `receipt.json` SHA-256 为 `25a4ffad028f5061b2c26cc6e38221f0a6f90a7de210a1acc7bcbd533c0cde9e`。Git 中保留四个 ZIP 分块，恢复后必须得到同一个原始 ZIP；不是重新打包的近似替代。[GitHub origin](../memory-cell-v10-ci/evidence/native-attempt-04/GITHUB_ORIGIN.json)；[ZIP 分块清单](../memory-cell-v10-ci/evidence/native-attempt-04/ZIP_PARTS.json)；[全部成员身份](../memory-cell-v10-ci/evidence/native-attempt-04/INDEX.json)。

在仓库根目录可执行纯证据恢复：

```sh
python qualification/memory-cell-v10-ci/evidence/restore.py \
  --attempt qualification/memory-cell-v10-ci/evidence/native-attempt-04 \
  --output /tmp/hepta-v10-native-restored
```

目标目录必须不存在。程序验证 ZIP、tar 和全部成员，最后才复制输出。恢复是离线字节验证，不重跑测试、训练或模型。恢复后的 `native-actual/` 包含 `NATIVE_ACTUAL.json`、三个 owner snapshots、三个导出阶段、迁移及撤销证据；根目录还含 JUnit、执行日志和完整保护源清单。

## 五个 owner 进程实际做了什么

| 进程 | 实际动作与结果 | 原始 PID |
|---|---|---:|
| 1 | 真实 SQLite 初始来源；原 Torch checkpoint 保持参数身份并导入；两类参数读出、跨 key 组合、预算、sleep／wake、坏 artifact 拒绝；in-flight Draining 与停止 | 27823 |
| 2 | 新进程冷读旧参数；未查询训练来源更正后旧 bundle 失效；写入 hold；从当前 snapshot 训练并读取新参数 | 27834 |
| 3 | 新参数冷读；删除一个 semantic 来源；旧 bundle 失效；以剩余来源清洁重建并读取 | 27847 |
| 4 | 同宿主真实 TCP 迁移后的独立目录冷启动；原源路径不可用；混合寻址 worker 实际运行；撤销后拒绝读取；正常停止 | 27867 |
| 5 | 带父进程独立保留的 withdrawal frontier 冷启动；明确拒绝被撤销 bundle，没有可用控制读取 | 27875 |

前四个进程都有 `stopped: true`、exit 0、`reaped: true`；第五个有明确 withdrawal 拒绝原因、父进程回收和零控制返回字节。第五个是预期的冷启动拒绝，不能写成第五个成功提供记忆服务的 owner。

迁移 receiver 为单独进程 27861，通过 `127.0.0.1` 实际 TCP 完成接收。恢复绑定 owner、scope、generation、bundle digest、owner cut 和独立 cognitive anchor。它证明同宿主、独立目录的冷迁移路径；不证明跨物理宿主性能、无缝在线迁移或任意中断后的恢复。

Readiness 使用明确的 control-only test seam，签名和撤销使用测试密钥；没有生产服务部署。迁移后的 worker 一次 accepted Apply、一次 ambiguous 拒答，实际 process starts=1、attempted=2、validated=2。它学习四类 operation，key 仍由确定性 registry 绑定，不能以这两个请求代替广泛地址泛化实验。

停止中的拒绝、停后读取和 malformed 输入的部分错误响应没有在 `NATIVE_ACTUAL.json` 逐条保存。对应结论来自固定 actual 源中的断言和成功的 parent/JUnit；不能宣称归档包含每项错误的完整 wire response。[Actual cases](../../codex-rs/hepta-agentd/src/memory_inventory_actual_cases.rs)；[Actual parent](../../codex-rs/hepta-agentd/src/memory_inventory_actual_tests.rs)。

## 数值一致性与知识正确性分别核对

Parity 比较同一参数在 Python NumPy、独立 f64 reference 与 Rust 下的计算。两种实现算出相同错误值，也可能通过 parity，因此内容正确性另需 owner 真值。

Actual 的 `check_written_values` 对每个被支持的 semantic／procedure 地址经真实控制 socket 读取，要求 status=Ok、值等于 owner 当前值、source ID 精确一致、一个参数 artifact。执行并保存了以下五组 observations：

| 组 | 源快照 | Socket 单值数 |
|---|---|---:|
| 原 checkpoint 初次读取 | owner-before | 16 |
| 原参数冷启动读取 | owner-before | 16 |
| 更正后的新参数 | owner-corrected | 16 |
| 新参数冷启动读取 | owner-corrected | 16 |
| 删除后重建参数 | owner-deleted | 15 |
| 合计 | 含冷读重复 | 79 |

这些 readout 的 query ID 按类型复用，79 是实际读取次数，不是 79 个独立问题。三个阶段的 47 行也不是 47 份不同新知识；未变化的 procedure 在更正与删除阶段具有相同参数摘要。

独立审计直接读取已保存 reference、Rust parity、owner snapshots 和 observations，不重载模型或训练。它分别检查 47 个阶段地址的真值、79 次 socket 读取、来源及参数身份，并对迁移后保存的 worker 读出事后核对完整 trace。[审计报告](native-audit/AUDIT_REPORT.md)；[机器结果](native-audit/AUDIT.json)；[审计程序](native-audit/audit.py)。

组合测试设计有七次直接 source-truth 断言，期望值由 owner 的 policy／program／event 经共享有界解释器算出。其中五份完整组合 readout 保存为 observations，另外两次返回值未保存。P4 混合 worker 的原测试只直接断言 Ok 与两个 model digests；其完整值／trace 正确性由上述事后 JSON 审计补充，不能冒充原测试就有该断言。

迁移后的保存样例为 event=5、policy=[5,4,11]、program=[reserve_gap,pack,cap,stop]，trace 为 5→0→0→0→0。该单次执行没有充分使用所有参数字段，因而仍须保留逐地址完整 policy／program 真值检查。

## 维护与删除的实测范围

更正使 policy 从 [7,2,13] 改为 [5,4,11]。旧 bundle 在重新训练前因来源 cut 改变而失效，新训练参数由真实 owner 读取；后续新进程重新读取同一参数。删除使支持的 semantic 地址由八个降为七个，procedure 仍为八个；被删 key 不得从当前服务读回旧值。

这证明小规模的更正、冷读、删除来源重建和拒绝旧发布。历史 checkpoints 和审计产物仍保留，不代表物理擦除或一般机器遗忘。Native 只有这三个参数导出阶段；三个 seed 各 32 周期的长期维护来自独立 Python 研究，不能混写成原生 owner 已完成 32 周期。

当前完整 scope cut 的保守失效和两模型共同发布仍然存在；sleep 只释放解码缓存，不声称 RSS 收益。原生通过没有改变研究中 learned 寻址、容量、结构晋升、维护准确率或成本优势的负结果。[实现边界](IMPLEMENTATION.md)；[研究结果](research_results_zh.md)。

## 最终 fix／format 与发布身份

<!-- FINALIZATION_STATUS_BEGIN -->
最终阶段已单独提交 [run 40912733051](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40912733051)。它先认证上述成功 run／job／artifact 及全部保护源身份，再执行 scoped `just fix` 和 `just fmt`；此模式不执行测试。最终 patch 与发布树尚待该阶段完成后核对。
<!-- FINALIZATION_STATUS_END -->

`AFTER_FILES.json` 中的 `git_blob` 来自未修改的真实 Git index，属于 formatter 前的 index 身份；其中 bytes／sha256 来自 formatter 后的工作树。最终发布核对须从新字节独立计算 post-format Git blob，并重建 `after_tracked_tree`，不能把该原 index 字段误称为新 blob。
