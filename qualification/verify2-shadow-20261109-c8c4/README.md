# VERIFY-2：有效检查选择与真实留存记录复算

**工程实现与留存记录复算已完成；科学晋级仍为 HOLD，生产权限为 NONE。**

本轮建立终端风险监测、联合 checker 效果学习、单次检查 VOI、受 host
强制约束的 shadow 接线，以及两条留存记录复算入口。全部代码通过 GitHub
分阶段发布；尚未合入 main 或部署为生产 verifier。

## 源码与 PR

| 阶段 | 已发布内容 | PR |
| --- | --- | --- |
| 1 | 有限状态、显式后续动作与损失矩阵的检查 VOI | [#5473](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5473) |
| 2 | 适用域、前缀上下文、检测率、误报、UNKNOWN 与共错的联合效果模型 | [#5475](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5475) |
| 3 | 固定 horizon/后续策略的风险监测、缺标签与接受覆盖报告 | [#5477](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5477) |
| 4 | 三模块绑定、强制 host gate、完整决策输入记录 | [#5483](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5483) |
| 5 | 原生 pilot 日志的风险复算、提前中断目标区分、UNKNOWN 处置保留 | [#5487](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5487) |
| 6 | 留存神经预测通道的配对效果学习与毛信息价值复算 | [#5501](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5501) |

源码基于 #5390 的 `410afb60ca4ca91b7d77c7902510ee8ddf5f0339`。
六阶段完整代码提交为 `e6a4724d070f0216a25db0c23e2bedf050eb39ce`。
41 份包内 Python 文件的 Git blob 均与发布提交一致；旧
`contracts.py`、`runtime.py`、`metrics.py` 的固定 SHA256 保持一致。
本地运行环境是重建的该 Python 包，不是完整 Rust workspace checkout。

## 1. 新实现解决了什么

选择器计算检查前最优动作的预期损失，减去获得检查结果后的预期最优损失，
再减增量检查成本。无信息、无法改变后续决策或高度相关的重复检查不获得
虚构收益。联合效果表对完整检查历史条件化，不直接乘边际可靠率。

风险目标固定 domain、event、horizon 与 continuation policy；公开特征和
checker 效果使用同一个上下文身份。域外、未见前缀、支持不足、版本或
snapshot 不匹配会拒绝或返回 unsupported。待完成的权限、schema 和原 owner
检查阻断可选调度；没有模型结果能够签发接受权限。

决策记录包括动作集合、完整损失矩阵、预算、host gate、模型与数据摘要、
检查历史和结果条件决策。修复残余失败、拒绝机会损失及后续强制检查成本
必须进入损失矩阵；当前声明成本尚未完成全部物理成本资格。

## 2. 原生留存记录与 horizon 区分

本轮恢复并逐文件核对了 10 份原始记录，复算入口实际使用其中 8 份。
跨文件 roster、开始/结束身份、原 inference/decision bindings、强制接受、
effect 顺序和标签顺序检查通过。逐文件读取不是跨文件原子快照。

| 项目 | 本轮复算观察 |
| --- | ---: |
| 历史 confirmation 轨迹 | 108 |
| 原操作开始/结束绑定 | 1,966 |
| 历史模型 forwards | 652 |
| 完整 train 轨迹 | 12 |
| 完整 calibration 轨迹 | 12 |
| confirmation 中观察到完整三步目标标签 | 66 |
| 提前停止、缺少不中断目标标签 | 42 |
| 新频率表预测（历史步骤 0 与 2） | 240 |
| 本轮新增神经 forwards / 重执行原 effect | 0 / 0 |

“在第 2 步停止时的实际状态标签”与“若不中断、完成第 3 步的标签”属于
不同目标。42 条提前停止轨迹保留后者缺失；不借用其他 arm 的完整标签。
已完成三步才中断的轨迹仍可保留已观察到的终点标签。

接受、拒绝、中断、UNKNOWN 与真实 error 分开记录。新增回归确认：
mandatory checker 因授权不足返回 UNKNOWN 时，可以同时具有独立读取的
已知 `error=false`。没有 policy 接受决策的 calibration reference panel
把接受覆盖及误接受 policy 指标设为 null，不报告虚构的零错误率。

## 3. 风险诊断

只用 train 的实际 ACK 前缀及终端标签拟合 Beta(1,1) 平滑频率表。
在完整标注的 calibration 集合中得到：

| 指标 | 初始前沿 step 0 | step 2 |
| --- | ---: | ---: |
| Brier | 0.2227891156462585 | 0.14583333333333334 |
| Log loss | 0.6377616405797456 | 0.4707841205631325 |

这是同一受控模板集合在不同信息前沿的预测诊断。它没有比较新旧调度策略，
也没有建立神经 verifier 优势。原 fixed-check confirmation 同样有完整标签；
其他六个主要 arm 各只有 6/12 可用 horizon 标签，其已标注子集指标不能直接
当作同分布策略比较。各原主要 arm 的接受覆盖仍为 4/12。

## 4. 实际神经预测通道的检查效果

固定 `score >= 0.5` 为 fail，只在 12 条 calibration 配对 panel 上拟合：
其中 4 条正确，8 条错误。风险先验只用 train，得到 9/14。

| 初始预测通道 | 检出错误 | 对正确结果误报 |
| --- | ---: | ---: |
| Qwen neutral | 0/8 | 0/4 |
| Qwen auditor role | 0/8 | 0/4 |
| Qwen readout 0 | 8/8 | 4/4 |
| Qwen readout 1 | 8/8 | 4/4 |
| Smol neutral | 0/8 | 0/4 |
| Qwen repeated neutral | 0/8 | 0/4 |

六条通道在这一初始空 ACK 输入条件下都产生固定结果；拟合的六个毛 VOI
全部为 0。已读取 neutral 后，重复 neutral 的增量毛 VOI 也为 0。
不同模型或分数在这里没有提供任务间的辨别信息。

诊断把检查成本设为分析用的 0，以分离毛信息价值；没有声称物理检查免费。
在这个经验模型中加入任意正成本，净值便为负。这个适用范围限定为
受控模板的初始预测通道；强制 SQLite owner readback 保持原有角色。

对应 held-out 原 arm 每个保留 6/12 完整 horizon 标签、6 条缺标签、
4/12 原接受覆盖。两个 readout 共用同一 arm；重复任务和多个前沿不计作
独立样本。缺标签范围 `[0,0]` 不是未来错误率置信上界。

## 5. 验证与精确源码身份

- 本地包级 **132 tests，全部通过，零跳过**。
- 最终代码 GitHub Ubuntu 24.04：**132 tests，12.472 秒，通过**。
- 最终代码 GitHub Windows 2025：**132 tests，58.211 秒，通过**。
- 两平台各执行 **72/72 条真实 SQLite fixture confirmation**，工程 gate 通过。
- 2026-11-09 12:13:50 UTC 观察时，macOS 15 仍排队；整个三平台矩阵尚未通过。

[最终源码 CI](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42614477333)
由代码 head `e6a4724d070f0216a25db0c23e2bedf050eb39ce` 触发；Linux 和
Windows 实际 checkout/tested 的 GitHub 合成 merge 为
`99b22a11dfbab525229d78cb5fed3473acc22c26`。本目录单独保留较早四阶段 CI，
没有把它充作后续代码的验证。CI 的 fixture 运行也与本地原生日志复算分开。

当前执行环境未安装 `just`，仓库要求的 `just fmt` 调用返回 command not found；
本轮未修改或声称测试 Rust 源码。Python 包测试及远端原有验证工作流均有实测记录。

## 6. 晋级状态

| 用户要求的晋级证据 | 当前状态 |
| --- | --- |
| 三个部件与 bound shadow 接线可执行 | 已完成 |
| 真实留存模型/效果记录复算，保持目标与证据绑定 | 已完成 |
| 前瞻真实任务 shadow 与独立外部终端标签 | 未完成 |
| 冻结新调度实际减少终端错误 | 未证明 |
| 接受覆盖与总效用没有不可接受退化 | 未证明 |
| 收益覆盖全部额外成本 | 未完成全成本测量 |
| 原 owner、独立 evaluator/signer 的生产装配 | 未完成 |

因此保持 **HOLD / NONE**。当前成果是可审查实现、实际历史诊断和严格标签
边界；它们没有签发生产晋级或总体可靠率结论。

## 复算与目录

在完整仓库或包含该 Python 包的源码目录运行：

```sh
python -B -m unittest discover -s experiments/verification_cell_verify1 -t . -v
python -B -m experiments.verification_cell_verify1.shadow_replay --input /path/to/original-run --output /path/to/new-risk-replay
python -B -m experiments.verification_cell_verify1.checker_replay --input /path/to/original-run --output /path/to/new-checker-replay
```

两个 output 都必须是未存在的新目录。以各自 `freeze.json` 的 8 份输入 SHA256
核对原 run 文件。原生历史导出与旧独立审查的固定链接见 `SOURCE_BINDING.json`；
本轮直接读取原始 run，未重新下载或重哈希旧二进制导出包。

`risk_replay/` 保留完整预测、标签、snapshot、模型、结果与冻结记录；
`checker_replay/` 保留配对 panel、实际观察、held-out 观察、联合模型、VOI 与冻结记录。
`MANIFEST.json` 固定本证据包文件摘要，`published-source-readback.json` 固定 41 份源码身份。
