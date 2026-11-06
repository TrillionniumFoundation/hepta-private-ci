# R2 历史候选协议与可执行分析工具

本目录原样保留已有 `r2-preregistration-v2` 的 15 个运行文件、候选约束和实际验证证据。
它把已完成的协议工作接到当前交付中；状态仍是 **候选协议，六个确认性准入条件开放**。
这里没有重新定义冻结对象、选择 N、分配总预算、执行功效模拟或启动四臂研究。

## 来源与保持规则

历史来源为 commit `975e1a264c14ed3da02dcee23a64327825387e42`、tree
`cb612abe0d02afaf711d37f5d8575a577da5524e`，原 R1 证据 commit 为
`de2b1212242cfa6f25563b99a385497a86dc7e49`。这些历史身份没有被当前集成身份覆盖。

[PRESERVATION.json](PRESERVATION.json) 逐项记录 28 个原样复制文件的原路径、大小、
SHA256 和 Git blob；15 个运行文件全部保持原字节。`PROTOCOL.inherited` 与归档
`source-recovery/fixed/r2_PARTIAL_FREEZE.json` 的 **frozen 子对象**逐项相同。
其 canonical SHA256 是 `f720cbb1e97087c8be4ffaec5f006589876b1b3e67dba1cc7ea47c93f4bb108b`；
整个候选 PROTOCOL 的 canonical SHA256 是
`17fc492f638858e1104d2dfe8d058c1e837a2d055df7991e0ae28ec5097358a9`。
canonical 对象摘要和文件字节摘要是不同身份，不可互换。

[SOURCE_PUBLICATION_AUDIT.json](SOURCE_PUBLICATION_AUDIT.json) 保存本次归档前的 GitHub 查询。
当时 15 个候选 exact blob 均返回 404，已发布 PARTIAL_FREEZE 阳性对照可读取；这不是对仓库
所有其它版本的穷举证明。PR #4857 的 `de2b121...` 到 `68564f6...` 变更恰为 A 的五个文件，
与当前 C 使用的 A 依赖字节完全一致。该审计记录保留当时观察，不随后续发布改写。

## 已有机制增量与确认性资格

原验证收据中“trainer absent”等描述保留其历史时点。当前相关交付已有以下增量：

| 路径 | 当前可核验范围 | 对本候选的影响 |
| --- | --- | --- |
| [A transition capture](../../transition_capture.py) 与 reader | #4857 head `68564f6fd8414ba5452ad6c6bf37d7cc41c767e8` 的真实状态、动作、结果身份与成本捕获机制 | 可作为采集实现依赖；不证明新数据或独立标签已存在 |
| [C action-value](../../R2_ACTION_VALUE.md)，[PR #4949](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4949) | 参数实际更新、双外部摘要绑定、新进程预测、失败与取消保留；源码 SHA256 `0a620b0188fb21432ae530aa3857025b9595a82a7d22747635cacb50754e3945` | 已执行的是合成标签 SGD 机制测试；没有真实独立开发标签 fit，不是已资格的 actor–critic、EVSI 或完整 NDU |
| [tiny-sd 开发训练](../sd_development_20261106/README.md)，[PR #4939](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4939) | 固定源 `fdbbfdbe582b2de80077236c8f2f0ab8fcbe76c3`，旧 R1 bee 图片上一次实际 conv_out 更新与冷装载数值匹配 | 真实生成器更新机制闭环；不是新来源确认性训练或语义收益验证 |

这些增量不把旧候选中的六个 OPEN 改成通过：新来源簇、独立评价与访问边界、完整真实 trainer、
总预算与强基线、质量与功效、确认性候选身份仍需各自的实际证据。
用户本轮所有基线和消融的覆盖映射见 [REQUIREMENTS_COVERAGE.md](REQUIREMENTS_COVERAGE.md)。
在编写这份集成说明时，后续 D 策略实现仍在开发/审阅，未计作已验证能力。

## 现有统计对象

固定 roster 是 `00, 10, 01, 11, greedy, planner, retrieval`。先分别计算每个方法的
gamma=2 entropic CE，再作七个已登记对比；不把配对差值的 CE 当作 CE 之差。

| 对比 | 公式 |
| --- | --- |
| 原主比较 | CE11 − CE01 |
| 冻结生成器下的控制增量 | CE10 − CE00 |
| 固定控制器下的生成增量 | CE01 − CE00 |
| 联合对基准 | CE11 − CE00 |
| 交互 | CE11 − CE10 − CE01 + CE00 |
| 已训练控制器下的生成增量 | CE11 − CE10 |
| 联合对验证集选择的强参考 | CE11 − CE_reference |

设计规定 32 个 fit seeds、每来源两个嵌套 draw、99,999 次 crossed bootstrap。
fit 和来源簇独立重采样，方法与两个 draw 保持配对；七个区间使用 Bonferroni 调整。
这些是计划与算法，不是已经训练 32 个控制器或完成 32 次真实独立 fit 的证据。
有限样本 bootstrap 区间仍是近似推断，已有 scalar 复核不证明实际数据上的统计功效。

## 已量化与未量化部分

已量化的候选推理限制为 horizon 10、同步软 deadline 600 秒、2 threads、VLM 最多 80 tokens、
输入长边 512、输出 256×256、diffusion 请求 12 steps。CPU/wall 费率 0.02/0.001 是研究效用转换，
不是货币价格或完整实际成本。

`BUDGET_CONTRACT.json` 中每 fit/arm 总 CPU、wall、内存、数据量、保留磁盘量、全研究 CPU 上限
仍全部为 null；所有实际 action service tariffs 也为 null。没有分配完整研究预算。
未知项不能补零，inclusive 包络不能与其 exclusive 子项重复相加；失败和未选工作不能丢弃。

候选 MDE 为 0.02、功效目标 0.8、备择增量 0.04、CI 半宽目标 0.02；质量下限 0.75、
严重错误率上限 0.01 仍待真实评价定义和验证。N 候选为 128/256/512/1024/2048，**N 未选择，
真实功效未运行**。最小 N=128 对应的 57,344 个计划 episodes 不代表已执行数量。

## 离线运行与依赖

运行依赖为 Python 3 和 NumPy。编译/准入检查不加载模型、获取数据、访问标签或使用网络；
分析工具只读取调用者明确提供的结果导出。
本次搬迁检查环境为 Linux、Python 3.12.14、NumPy 2.3.5。运行入口以自身 `__file__` 找兄弟
代码/JSON，普通 CLI 不依赖原 scratch 路径或 `source-recovery`。可从本目录执行：

```bash
python -B compile_contracts.py --output /absolute/new/plan.json
python -B check_readiness.py --output /absolute/new/readiness.json
```

输出路径必须尚不存在。第一条 exit 0 仅表示成功编译 128 条全为 NOT_RUN 的 fit-arm 计划，
不调度工作；第二条当前预期 **exit 2 / BLOCKED**，表示六个条件尚未满足。
`analyze_capture.py` 需要独立保留的 design 与 capture 摘要及实际导出；不能用此目录虚构输入。
`audit_data_manifest.py` 只核对声明的来源 ID、hash 和分组元数据，不读取图像/标签、执行近重复
视觉审计或证明 custody。完整导出字段见原样 [EXPORT_FORMAT.md](EXPORT_FORMAT.md)。

| 依赖层 | 文件 |
| --- | --- |
| 冻结候选与数据排除 | PROTOCOL、BASELINE_CONTRACT、DATA_CONTRACT、BUDGET_CONTRACT、UTILITY_AND_POWER、EXPOSURE_REGISTER、READINESS_INPUT |
| 统计与账本 | r2_statistics → r2_capture → analyze_capture |
| 编译与结构准入 | compile_contracts、check_readiness、audit_data_manifest，读取相应兄弟 JSON |
| 原验证 | test_protocol_tools、validation/original、reviews；只保存既有结果 |
| 历史冻结核验 | source-recovery/fixed 的两个旧文件；reviews/source/make_candidate.py 为审阅源存档，不是本目录运行入口 |

`reviews/ORIGINAL_SOURCE_MANIFEST.json` 是原独审的 12 文件清单，原字节保留。
其中 11 项映射到本目录同名文件，make_candidate 映射到只读历史源；映射和逐项核验在
PRESERVATION 中。没有复制整棵旧研究源码或重新生成候选文件。

## 验证及成本边界

原 `validation/original/` 保存 17 项合成算术/账本控制的 launch、终态和完整日志，其中已有
一次 99,999 bootstrap 小控制；原框架耗时 1.685 秒。完整原测试进程 CPU/wall 未测量，不能
用框架耗时冒充。原独立 scalar 审阅验证 9 组 crossed 权重、7 方法、4 种参考选择，最大误差
8.881784197001252e-16；它不涉及模型、真实标签或独立评价访问边界。

新 `validation/relocation/attempt1/EXECUTION.json` 仅验证搬迁：从包外 cwd 调用两个 CLI，
compile exit 0，readiness exit 2，28 份保存原件运行前后摘要一致。没有重跑旧 bootstrap、
模型、训练或真实评价；完整大 PLAN 保留在收据记录的 scratch 输出路径，发布摘要和哈希。

| 新物理命令 | CPU 秒 | 外部 wall 包络秒 |
| --- | ---: | ---: |
| compile_contracts | 0.802673 | 0.167218 |
| check_readiness | 0.995064 | 0.299755 |
| 两个互不重叠子进程合计 | 1.797737 | 0.466972 |

wall 包络包括子进程结果收取；wrapper 区间 wall 0.478128 秒包含上述子进程，不能再相加。
wrapper 自身区间 CPU 0.017247 秒另列，区间不含 imports 和最终 receipt 写入。
峰值内存、能耗、物理 I/O、网络、原测试完整成本、编写和发布成本仍未知。
这里的准入、算术和成本证据不授权候选晋级；`no_update` 不应被解释为其它开发阶段没有更新参数。
