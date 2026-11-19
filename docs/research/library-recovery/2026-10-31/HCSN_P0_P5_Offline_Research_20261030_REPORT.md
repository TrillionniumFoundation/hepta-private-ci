# HCSN P0–P5 本地研究冲刺交付

日期：2026-10-30（美东）/ 2026-10-31（UTC）  
仓库目标：`TrillionniumFoundation/hepta-private-ci`  
状态：`LOCAL_RESEARCH_ONLY`、`DENY_ALL`、未推送、未合并、未部署

## 远端当前阻塞

GitHub 已连接账号在实际读取 `get_repo`、`branches/main`、PR #4422、PR #4255 时均返回 `403: Sorry. Your account was suspended`。**未获取当前 main 精确 SHA，未核验当前 PR HEAD/base 或最终 Actions。** 不可将之前的 SHA 充作当下事实，不能在本轮提交远端 PR。不得据此认为主干已通过验收。

## 实现/复验

| 阶段 | 可复现的本地范围 | 实际结果 | 不可外推的结论 |
|---|---|---|---|
| P0 | 已有分段线性边界斜率证书的本地拷贝 + 新独立有限时首达损失积分 | 原有10项 + 新增8项通过 | 非全域 HX 固定点/障碍证明；无有向舍入 FP32 全域保证 |
| P1 | 已有局部值/导数匹配的本地拷贝，修正无效通道导入顺序 + 新四对照配对统计验收工具 | 14项 + 新增15项通过 | 新统计数据均为 **SYNTHETIC**，非新真实种子结果，未证明机制收益 |
| P2 | 已有两状态再生 CTMC 本地拷贝 + 新分段三段矩阵指数独立对照 | 14项 + 新增5项通过 | 不等于全网记忆/长序列召回与连续边界验证 |
| P3 | 已有四模态素材解码/完整性 gate 本地拷贝 | 22项通过 | 无真实四模态训练、OOD 质量或检索优势证据 |
| P4/P5 | 新 P0–P5 fail-closed 证据账本 | 新增12项通过 | 没有 Rust/GPU/64..4096 Cell/焦耳或同质量净收益数据，始终拒绝生产放行 |

**共 100/100 本地 Python unittest PASS**，其中新实现（P0 8、P1 15、P2 5、账本 12）共 40 项；剩余 60 项是从现有本地隔离研究副本重新执行，不是整仓/最新 PR CI。

## 一条命令复现

在本文件所在目录执行：

```bash
python -m unittest discover -v -s .
python -m p0_p5_gatebook
```

运行环境：Python 3.13.5、NumPy 2.3.5、SciPy 1.17.0、mpmath 1.3.0、Pillow 和 ffmpeg/ffprobe。`ffmpeg/ffprobe` 是四模态视频完整解码测试的系统依赖。详见 `all_tests.log` 和 `EVIDENCE.json`。

## 关键新增科学/数值机制

P0 的 `independent_discount_loss.py` 将 `F = P(tau<=T)`、`G = E[e^-q*tau 1(tau<=T)]`、`L = F-G` 分别输出，其中 `L` 直接从非负密度积分而非 `float32(F)-float32(G)` 计算。对 `x=.4, mu=-.05, sigma=.8, T=2, q=1e-23`，得 `L≈3.595173291178638e-24`，而 FP32 的 F 与 G 相等，输出明确拒绝。这**不是**全域误差区间认证；使用常系数与常边界近似。

P1 使用 10–16 个配对种子对四个显式对照进行精确双侧符号翻转、Holm p 值调整、四重 Bonferroni 置信下界；检查同输入批次摘要、学习有效参数、同头/优化器/训练预算、标定局部斜率与值、完整 worker CPU、能耗记录。它不能核验任何自报的预注册时间，所有示例正效应只是程序的合成测试。

P2 执行 70 组随机三段常速率切换、80 组常速率半群一致性，并由 `scipy.linalg.expm` 独立复算；同时证明重复期望事件数与至少一次事件概率不可互换。物理两状态 CTMC 与真正完整 HCSN 模型仍有差异。

## 文件说明

- `experiments/...`、`p1_slope_reference/...`：本地已有研究参考文件拷贝；不能据此声称与最新远端 SHA byte-for-byte 一致。
- `p0_discount_loss/`、`p1_mechanism_gate/`、`p2_renewal_adversarial/test_piecewise_ctmc.py`、`p0_p5_gatebook/`：本轮新增代码与测试。
- `repo_overlay/`：仅新增文件的**建议**整仓目录映射；导入到真实研究分支前必须审计 exact base/head 与现有文件路径。
- `HCSN_P0_P5_Offline_Research_20261030.patch`：可移植研究 patch，仓库依赖需与目标分支一致；当前未在远端应用。
- `p1_slope_reference/import_order_fix.diff`：单独候选修复；与实际最新源码不保证无冲突，不并入加法 overlay。
- `EVIDENCE.json`、`FILE_SHA256.json`、`all_tests.log`、`overlay_tests.log`：本次本地执行及源码摘要。
- `pending_ledger.json`、`denied_gate_report.json`：缺真实 HCSN 科学/生产证据时明确返回拒绝，不把 100 项局部单元测试误认为所有阶段闭环。

## 下一步真正的未闭合工作

先恢复/更换有权限的 GitHub 连接，读取**当前** `main` 与研究栈 exact SHA、diff 和最终原始 CI/job/log。随后将加法 patch 适配到正确科研基线，执行整仓集成与 independent numerical oracle；P1 需要冻结尚未看过的真实种子/数据并开展 Call/Risk/Margin 单/双/联合消融；P2 需要真实 Copy/MQAR 与长记忆任务；P3 需要真实四种 Encoder 与对齐样本；P4 需要 native Rust/GPU + Joule/恢复 + 四规模硬件；P5 只有当 P1–P4 的净收益门通过后才能提升规模。此前冻结的 0/4 机制与 0/18 外部质量门失败证据保持有效。