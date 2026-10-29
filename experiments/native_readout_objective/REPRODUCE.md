# 复现固定原生 sparse kernel 的读出目标研究

本指南分别说明如何恢复已发布原始证据、重算完整审计，以及在全新目录重复运行封存协议。正式结果、选择提交、归档身份和审计结论以交付的实际收据为准；下面的执行步骤不预先宣称收益门槛通过。

本研究固定原 sparse kernel、420 个 encoder 系数、42 个可训练 readout 系数及原 NDU，比较 `ridge_reference`、`iterative_q_mse`、`policy_regret`，并保留 `finite_grid_dp`。唯一主比较是 `policy_regret − iterative_q_mse`。16 个注册 seed 和全部预算见 [PROTOCOL.json](PROTOCOL.json)；科学解释见 [README.zh.md](README.zh.md)。旧 flow 的 0/3、旧 policy 的 0/4 分别保留。

## 1. 已公开的源码和可执行文件身份

| 对象 | 身份 |
| --- | --- |
| 源码、协议与前置证据公开提交 | `7908860cb959cbe1599379d4ecbfcc22fbccbe61` |
| `SOURCE_SEAL.json` SHA-256 | `83f5243f7b7c7aead3742baccd01caaf619759658f320e824589ff016269d2e9` |
| `PROTOCOL.json` SHA-256 | `3d19c2f0aef69da5d368da01e34308f1344ec98b10fd0aaefa1ba4877aa9baff` |
| 重建的 `continuous_host` SHA-256 | `fa9dc78b129b0ec3b072e9fc8c8fdd49479515c79aeb2660f355e38f41e54dce` |
| 共用 runtime 包 `INDEX.json` SHA-256 | `343b59bfa029ff261bf3b3326d23c7ddfbf0f0b4f4418e3e64be022f1d123ba7` |

原生构建来源是 `5898cd8b0f724c3152b6cc52856721f72e5e08be` 的 Rust neuron/NDU 源码，最终构建收据及 manifest 位于 [native/](native/)。这份执行文件有新的构建身份，不是遗失旧二进制的恢复。共用 runtime 的 [回环收据](../continuous_boundary_policy_reproduction/preflight/RUNTIME_ROUNDTRIP.json)记录 168 个文件逐项恢复通过；该包只包含准备期证据和重建执行文件，不包含正式研究样本。

## 2. 获取仓库历史和数值环境

以下命令从一个全新工作副本开始。不要使用浅克隆；公开前置提交和后续选择提交必须保留在 Git 历史中。可以只检出 `experiments/`，完整数学审计所需的研究源码均在其中。

```sh
git clone --filter=blob:none --no-checkout --single-branch \
  --branch research/continuous-boundary-flow-20261028 \
  https://github.com/TrillionniumFoundation/hepta-private-ci.git \
  hepta-readout-reproduction
cd hepta-readout-reproduction
git sparse-checkout init --cone
git sparse-checkout set experiments
git checkout research/continuous-boundary-flow-20261028
git fetch origin \
  research/continuous-boundary-flow-20261028:refs/remotes/origin/research/continuous-boundary-flow-20261028
export PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1
```

必须使用上述显式 refspec。只更新 `FETCH_HEAD` 不够；驱动器和独立审计要求命名引用 `refs/remotes/origin/research/continuous-boundary-flow-20261028` 存在，并验证源码与选择提交的祖先关系及文件原字节。

在隔离的 Python 环境安装封存依赖：

```sh
python -m pip install -r experiments/continuous_boundary_flow/requirements.txt
python -c 'import sys, numpy, scipy; print(sys.version); print(numpy.__version__, scipy.__version__)'
```

准备期运行使用 Linux x86_64、Python 3.12.14、NumPy 2.3.5、SciPy 1.17.0。正式运行的精确身份以归档 `study/ENVIRONMENT.json` 和原生构建收据为准。独立审计会逐字节比较有限网格 DP 的浮点数组摘要，因此仅有相近 Python 版本或相同数学公式不足以保证通过；应重建记录的 Python/NumPy/SciPy/Linux 数值环境，并核查实际 BLAS/浮点执行环境。遇到 DP digest 差异时保留差异、排查环境，不能改封存协议、源文件、摘要或容差来绕过验证。

## 3. 快速恢复实际执行二进制

从仓库根目录执行，输出目录必须尚不存在：

```sh
export HEPTA_READOUT_RUNTIME=/tmp/hepta-readout-runtime-restored
python -m experiments.continuous_boundary_flow.evidence_bundle unpack \
  --bundle-dir experiments/continuous_boundary_policy_reproduction/preflight/runtime_evidence \
  --output-dir "$HEPTA_READOUT_RUNTIME"
export HEPTA_READOUT_NATIVE="$HEPTA_READOUT_RUNTIME/engineering/bin/continuous_host"
sha256sum "$HEPTA_READOUT_NATIVE"
```

解包器验证有序分片、完整 archive、文件名册、每个文件的长度与 SHA-256；拒绝链接、越界路径、重复成员和未声明文件，并恢复执行权限。将输出摘要与第 1 节的实际二进制身份核对。Linux x86_64 之外的主机不能把这份执行文件直接视为可运行；只读证据检查与实际原生执行是不同步骤。

同一 runtime 包还含 `engineering/bin/boundary_policy_score_host`，供相邻 policy 复现使用；本读出研究使用 `continuous_host`。需要自行重建时参考 [原 native 构建说明](../continuous_boundary_flow/native/README.md)，保留新的构建收据。不同字节的重建结果不能替代此处已封存的执行文件；要研究新构建，须另立并公开对应源码/协议/二进制身份。

## 4. 原样恢复完整正式证据并重算审计

完整研究归档入口是 `evidence/bundle/INDEX.json`。请使用包含正式归档的发布版本；仅有准备期 runtime 包时，不能把它当作完整研究证据。

```sh
export HEPTA_READOUT_RESTORED=/tmp/hepta-readout-evidence-restored
python -m experiments.continuous_boundary_flow.evidence_bundle unpack \
  --bundle-dir experiments/native_readout_objective/evidence/bundle \
  --output-dir "$HEPTA_READOUT_RESTORED"
```

恢复布局如下：

| 路径 | 内容 |
| --- | --- |
| `study/` | 正式 run：协议、源/环境/选择封存、公共探索数据、实际 native 激活、物理 DP teacher、所有候选和选定 checkpoint/profile、开发轨迹、确认 shards、诊断面板、成本与 `MANIFEST.json` |
| `engineering/owner/` | 固定已有 episode 的原生 durable-owner、冷恢复和实际 STOP 覆盖收据 |
| `engineering/bin/` | 本次研究使用的实际执行文件 |
| `engineering/audits/` | 保存的独立审计及相关检查输出 |
| `engineering/outer_costs/` | 构建、审计、封装等外围成本记录 |
| `engineering/` 其余内容 | 交付身份、日志与其他附加证据，以归档文件名册为准 |

完整归档可独立提供执行文件；快速 runtime 包不是必需的第二份依赖。直接重算正式科学审计：

```sh
python -m experiments.native_readout_objective.audit \
  "$HEPTA_READOUT_RESTORED/study" \
  --repository "$PWD" \
  --output /tmp/hepta-readout-recomputed-audit.json
```

输出必须是不存在的新文件，并放在 `study/` 外。不要把日志、缓存、解释性文件或审计输出写入封存的 `study/`；完整文件名册会拒绝额外产物。不要重写归档中的绝对路径或原时钟值。

审计核查源/公开提交/构建绑定、实际原生激活与 profile 链、各候选优化过程和开发选择、全部确认轨迹、物理任务账本、独立 Q24 读出和原 NDU 动作规则、共同状态量化面板、通信与成本、配对 seed 统计。固定注册规模为 16 seed × 4 arms × 256 episodes = 16,384 条确认轨迹；诊断面板和 owner replay 不计入该样本量。应保存复算输出并与 `engineering/audits/` 内相应完整原审计逐项比对；不预填通过状态或结果摘要。

若要重新执行工程验证，使用独立新输出目录，保留归档原工程记录：

```sh
python -m experiments.native_readout_objective.engineering \
  --run "$HEPTA_READOUT_RESTORED/study" \
  --native-binary "$HEPTA_READOUT_RESTORED/engineering/bin/continuous_host" \
  --output /tmp/hepta-readout-owner-replayed
```

该命令使用 seed 3301、三个学习臂、ID/OOD 各 context 0/path 0，共六个已有 episode。它重建完整任务状态、替换进程并检查后缀；不是新的收益试验。STOP 探针仅在选定轨迹确实出现 STOP 时运行，覆盖次数以新收据为准。

## 5. 在全新目录重复训练和确认

保持当前已公开源封存和注册协议，不重新执行 `freeze`，不修改原 seed 或门槛。重复相同 16 seed 的运行属于本研究的重复实验，不能再次作为独立样本合并计数。

```sh
export HEPTA_READOUT_SOURCE_COMMIT=7908860cb959cbe1599379d4ecbfcc22fbccbe61
export HEPTA_READOUT_RUN=/tmp/hepta-readout-new-run
python -m experiments.native_readout_objective.study initialize \
  --output "$HEPTA_READOUT_RUN" \
  --native-binary "$HEPTA_READOUT_NATIVE" \
  --publication-commit "$HEPTA_READOUT_SOURCE_COMMIT"
python -m experiments.native_readout_objective.study train \
  --output "$HEPTA_READOUT_RUN" \
  --native-binary "$HEPTA_READOUT_NATIVE"
python -m experiments.native_readout_objective.audit \
  "$HEPTA_READOUT_RUN" --repository "$PWD" --selection-only \
  --output /tmp/hepta-readout-new-preconfirmation-audit.json
```

`initialize` 要求全新输出目录；`train` 拒绝重复或部分完成的阶段。确认前审计只读取训练与开发证据，拒绝确认产物。任何失败都保留原目录与日志，不通过删除标记、清空部分证据或重写成本来续跑成一个“未中断”试验。

**在下一条命令之前，必须公开本次新 run 的选择封存。** 将 `$HEPTA_READOUT_RUN/SELECTION_SEAL.json` 的原字节，通过有写入权限的发布者提交到 `experiments/native_readout_objective/evidence/SELECTION_SEAL.json`，并使该提交进入指定远端研究分支。保留原研究的公开提交与归档。新运行有新的训练时钟和环境绑定，不能复用旧 selection commit，不能伪造本地 remote ref，也不能只传一个未经实际公开的 commit 字符串。

发布并获取其真实完整 40 位 commit 后，再执行：

```sh
git fetch origin \
  research/continuous-boundary-flow-20261028:refs/remotes/origin/research/continuous-boundary-flow-20261028
export HEPTA_READOUT_SELECTION_COMMIT=REPLACE_WITH_ACTUALLY_PUBLISHED_NEW_SELECTION_COMMIT
python -m experiments.native_readout_objective.study confirm \
  --output "$HEPTA_READOUT_RUN" \
  --native-binary "$HEPTA_READOUT_NATIVE" \
  --publication-commit "$HEPTA_READOUT_SELECTION_COMMIT"
python -m experiments.native_readout_objective.audit \
  "$HEPTA_READOUT_RUN" --repository "$PWD" \
  --output /tmp/hepta-readout-new-confirmation-audit.json
python -m experiments.native_readout_objective.engineering \
  --run "$HEPTA_READOUT_RUN" --native-binary "$HEPTA_READOUT_NATIVE" \
  --output /tmp/hepta-readout-new-owner
```

没有向该分支公开新 selection 的权限时，可以完成原样恢复、审计、训练和确认前检查；应交给有权限的发布者完成公开步骤，再继续确认。不得绕过这一已封存条件。另一个科学问题、种子方案或二进制版本需要独立方案和新的预先公开流程，不能在已完成研究上改名追加。

## 6. 成本、数值和结论的范围

科学 `costs.jsonl` 保留每个注册阶段的原始 CPU/wall 值，区分共享模型/DP/探索、实际 native 特征导出、候选拟合、开发运行、确认、诊断面板和序列化。包围窗口含子阶段和已回收子进程 CPU，嵌套收据不能再次相加。工程 `overall_cost` 是包含其子窗口的总量；重新解包、独立审计、编译、归档和公开的外围成本另列。

三个学习臂均按每步 20 个 i64，即 160 个数值输入字节，按每 byte `1e-6` 扣减净效用；完整 JSON 请求和响应流量另测。数值字节不是全部网络流量，CPU 没有被虚构成货币价格。没有硬件功率或焦耳测量，不从少事件、闭式求解、快运行或低 CPU 推出节能。

主判断使用封存的 16 个配对 seed、双侧 95% t 区间、下限大于 0.005 且零稳定性失败。所有其他排名、风险校准、量化翻转和按 teacher 动作分组的 regret 均按注册口径解释。相同解析风险预测器在不同策略访问分布上的校准变化，不等于预测器本身改善。有限网格 DP、有限轨迹和六个 owner case 不能证明精确连续时间自由边界或任意长期稳定性；研究始终保持 `DENY_ALL`，不构成生产 admission。
