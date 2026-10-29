# 复现原 policy 协议：同种子、新二进制、单独证据

本目录用新身份重建并运行原 `continuous_boundary_policy` 的封存科学算法。原 8 seed、13 arms、全部训练/开发/确认预算和协议字节保持不变；原补充研究的完整 raw archive 与两份旧执行文件未恢复。这里的新轨迹不是遗失旧轨迹的恢复，也不是新增独立样本。

原研究 **0/4** 结论保留；本次结果必须单独报告，不能与原研究合并推断或替换其历史记录。明确范围见 [REPRODUCTION_PLAN.json](REPRODUCTION_PLAN.json)，原结论与恢复缺口见 [原报告](../continuous_boundary_policy/REPORT.zh.md)及 [RECOVERY_STATUS.json](../native_readout_objective/RECOVERY_STATUS.json)。本指南说明恢复与执行方法，正式统计结果以完整审计收据为准。

## 1. 已公开身份

| 对象 | 身份 |
| --- | --- |
| 新源码、协议、计划和前置证据公开提交 | `7908860cb959cbe1599379d4ecbfcc22fbccbe61` |
| 新 `SOURCE_SEAL.json` SHA-256 | `6608ee0c6ddd33862096a3c7d5085ab670b05a7c4c45d728f9f59efaa064b717` |
| 与原研究逐字节相同的 `PROTOCOL.json` SHA-256 | `c55747dd06640b92aca2198dcbfa21a0a5bf53f5890daf6bc51aa257f887865a` |
| 继承的原 policy source seal SHA-256 | `6b3afbf2af8476730c1260f470bd8f0f68d69652950499388abc3b178f0fd858` |
| 新 `continuous_host` SHA-256 | `fa9dc78b129b0ec3b072e9fc8c8fdd49479515c79aeb2660f355e38f41e54dce` |
| 新 `boundary_policy_score_host` SHA-256 | `655b919aca126a33ee2fd54501b024eb80f4b1842b0e3410791958d93a588c47` |
| `preflight/runtime_evidence/INDEX.json` SHA-256 | `343b59bfa029ff261bf3b3326d23c7ddfbf0f0b4f4418e3e64be022f1d123ba7` |

新 source seal 继承并逐项核验原 67 个封存文件，另绑定新 driver、计划、构建/测试收据。原科学源码没有改写。`phases.py` 机械保留原训练和确认算法，变化为新公开路径、严格身份门和一次性阶段标记；独立数学审计继续调用原审计实现。

已测试的新二进制与最终构建身份由 [preflight/](preflight/) 保留。runtime 的 [回环收据](preflight/RUNTIME_ROUNDTRIP.json)记录 168 个文件恢复通过，其范围是准备期诊断和实际执行文件，不能用来充当正式 26,624 条确认轨迹。

## 2. 仓库、公开历史和数值环境

可用完整克隆，也可只检出研究目录；必须保留 Git 历史和指定 named remote ref。

```sh
git clone --filter=blob:none --no-checkout --single-branch \
  --branch research/continuous-boundary-flow-20261028 \
  https://github.com/TrillionniumFoundation/hepta-private-ci.git \
  hepta-policy-reproduction
cd hepta-policy-reproduction
git sparse-checkout init --cone
git sparse-checkout set experiments
git checkout research/continuous-boundary-flow-20261028
git fetch origin \
  research/continuous-boundary-flow-20261028:refs/remotes/origin/research/continuous-boundary-flow-20261028
export PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1
python -m pip install -r experiments/continuous_boundary_flow/requirements.txt
python -c 'import sys, numpy, scipy; print(sys.version); print(numpy.__version__, scipy.__version__)'
```

建议在隔离的 Python 环境执行安装。不要浅克隆，也不要只依靠 `FETCH_HEAD`；初始化与审计要求源码、协议、计划及选择提交都是 `refs/remotes/origin/research/continuous-boundary-flow-20261028` 的祖先，并逐字节核查公开内容。

准备期环境为 Linux x86_64、Python 3.12.14、NumPy 2.3.5、SciPy 1.17.0。正式 run 的实际平台、CPU、Python 和依赖身份见归档 `study/ENVIRONMENT.json`，二进制环境见构建收据。独立审计对有限网格 DP 数组执行精确 digest 比较；应复原记录的 Python/NumPy/SciPy/Linux 数值环境，并核查 BLAS/浮点执行差异。跨环境出现摘要不同，应保留并定位差异，不得修改已封存协议、源文件、期望摘要或检查容差来让审计通过。

## 3. 恢复共用 runtime 和两个真实二进制

```sh
export HEPTA_POLICY_REPRO_RUNTIME=/tmp/hepta-policy-reproduction-runtime
python -m experiments.continuous_boundary_flow.evidence_bundle unpack \
  --bundle-dir experiments/continuous_boundary_policy_reproduction/preflight/runtime_evidence \
  --output-dir "$HEPTA_POLICY_REPRO_RUNTIME"
export HEPTA_POLICY_REPRO_NATIVE="$HEPTA_POLICY_REPRO_RUNTIME/engineering/bin/continuous_host"
export HEPTA_POLICY_REPRO_SCORE="$HEPTA_POLICY_REPRO_RUNTIME/engineering/bin/boundary_policy_score_host"
sha256sum "$HEPTA_POLICY_REPRO_NATIVE" "$HEPTA_POLICY_REPRO_SCORE"
```

输出目录必须不存在。核对第 1 节 SHA-256；解包器验证每片、完整 archive、文件 manifest、长度和逐文件身份，拒绝链接、越界路径、重复及额外成员，并恢复执行权限。执行文件面向 Linux x86_64。读出研究也使用这里相同身份的 `continuous_host`。

自行构建时，先按 [原 native 构建说明](../continuous_boundary_flow/native/README.md)创建独立新构建树，再用本目录 `build_score.py`：

```sh
python -m experiments.continuous_boundary_policy_reproduction.build_score \
  --repository /absolute/repository \
  --native-build /absolute/verified-native-build \
  --output-dir /absolute/new-score-build-receipt \
  --compiler /absolute/pinned-rust-toolchain/bin
```

这个 builder 会核验新 native 的精确身份、原源码、vendor、lockfile 和 compiler；它不是允许任意二进制进入原研究的适配开关。最终格式后的收据为 `preflight/SCORE_BUILD.json`；`SCORE_BUILD.preformat.json` 与原测试收据保留真实受测历史。若重新编译产生不同字节，不得用它冒充当前身份，也不得改旧 builder 或绕过 SHA 检查；不同构建需要独立版本和新公开封存。

## 4. 原样恢复完整正式研究并审计

完整归档入口为本目录 `evidence/bundle/INDEX.json`。需要已包含正式归档的发布版本；准备期 runtime 包不包含正式研究轨迹。

```sh
export HEPTA_POLICY_REPRO_RESTORED=/tmp/hepta-policy-reproduction-evidence
python -m experiments.continuous_boundary_flow.evidence_bundle unpack \
  --bundle-dir experiments/continuous_boundary_policy_reproduction/evidence/bundle \
  --output-dir "$HEPTA_POLICY_REPRO_RESTORED"
```

| 恢复路径 | 内容 |
| --- | --- |
| `study/` | 正式 run 的协议、source/plan/environment、阶段标记、公共训练数据、全部候选及选定 checkpoint/profile、开发选择、确认 shards、原始成本与 `MANIFEST.json` |
| `engineering/continuous_state/` | 原工程 driver 在本次选定模型上的持续状态、冷进程续行、共同输入计时与 summary |
| `engineering/bin/` | 两个实际执行二进制 |
| `engineering/audits/` | 保存的独立审计及相关检查输出 |
| `engineering/outer_costs/` | 构建、审计、封装等外围成本记录 |
| `engineering/` 其余内容 | 交付身份、日志及附加证据，以归档文件名册为准 |

完整归档自含执行文件，可以直接对实际二进制身份和数学证据一起审计：

```sh
python -m experiments.continuous_boundary_policy_reproduction.audit confirmation \
  --study "$HEPTA_POLICY_REPRO_RESTORED/study" \
  --native-binary "$HEPTA_POLICY_REPRO_RESTORED/engineering/bin/continuous_host" \
  --score-binary "$HEPTA_POLICY_REPRO_RESTORED/engineering/bin/boundary_policy_score_host" \
  --output /tmp/hepta-policy-reproduction-recomputed-audit.json
```

该命令读取二进制核对其字节身份，不启动二进制重新生成科学轨迹。纯证据离线复算可同时省略两个 binary 参数；输出中的 `actual_executables_checked` 会如实记录 `false`，不能称为已检查执行文件。源码和选择的 Git 公开祖先关系仍须可验证。

审计输出必须是 `study/` 外不存在的新文件；不要在封存 run 内放额外日志、缓存或说明，也不要改写原时钟或绝对路径。新包装先检查原 67 文件、新源码/协议/计划、构建、环境和公开身份，再调用原 `continuous_boundary_policy.audit.audit_run`。原数学审计重算训练数据/有限 DP、全部候选和开发选择、连续状态/分数/动作、任务账本、风险、原生收据、通信/成本和四项配对比较。

注册规模为 8 seed × 13 arms × 256 episodes = 26,624 条确认轨迹、104 个选定 checkpoint、208 个确认 shards。它是相同注册样本设计的重新执行；解包校验、数学审计或工程测试通过，都不意味着四项收益门槛通过。应保留复算审计并与 `engineering/audits/` 中对应完整原审计逐项比较。

重新执行有限工程工作负载时，使用全新目录，保留原工程证据：

```sh
python -m experiments.continuous_boundary_policy.engineering \
  --study "$HEPTA_POLICY_REPRO_RESTORED/study" \
  --score-binary "$HEPTA_POLICY_REPRO_RESTORED/engineering/bin/boundary_policy_score_host" \
  --output /tmp/hepta-policy-reproduction-engineering-replayed \
  --ticks 8192 --checkpoint-interval 1024 --replay-ticks 16 --warm-ticks 4096
```

该工程 driver 使用实际原 NDU 和持久 Python 循环状态；不会运行 sparse kernel，也不提供 durable native owner 证明。它不产生新的确认样本，实际完成次数和恢复结果以本次收据为准。

## 5. 全新 run 的分阶段复现

不要覆盖任何原 run、封存文件、候选、时钟或已完成阶段。保持当前源码、相同协议和原 8 seed，不重新 `freeze`；要修改科学设计或二进制，必须另立版本。

```sh
export HEPTA_POLICY_REPRO_SOURCE_COMMIT=7908860cb959cbe1599379d4ecbfcc22fbccbe61
export HEPTA_POLICY_REPRO_RUN=/tmp/hepta-policy-reproduction-new-run
python -m experiments.continuous_boundary_policy_reproduction.study initialize \
  --output "$HEPTA_POLICY_REPRO_RUN" \
  --native-binary "$HEPTA_POLICY_REPRO_NATIVE" \
  --score-binary "$HEPTA_POLICY_REPRO_SCORE" \
  --publication-commit "$HEPTA_POLICY_REPRO_SOURCE_COMMIT"
python -m experiments.continuous_boundary_policy_reproduction.study train \
  --output "$HEPTA_POLICY_REPRO_RUN" \
  --native-binary "$HEPTA_POLICY_REPRO_NATIVE" \
  --score-binary "$HEPTA_POLICY_REPRO_SCORE"
python -m experiments.continuous_boundary_policy_reproduction.audit preconfirmation \
  --study "$HEPTA_POLICY_REPRO_RUN" \
  --native-binary "$HEPTA_POLICY_REPRO_NATIVE" \
  --score-binary "$HEPTA_POLICY_REPRO_SCORE" \
  --output /tmp/hepta-policy-reproduction-new-preconfirmation-audit.json
```

初始化在创建目录之前验证 source/protocol/plan 已真实公开及两份二进制身份。训练使用原 120 epochs、三个候选、相同公共 teacher 和开发选择；预确认审计独立检查 train/dev contexts、104 个选择、全部训练收据和训练成本前缀，并拒绝任何确认产物。它只用于刚完成训练的 run，不能用于已完成确认的归档。

**继续前必须公开新 run 的 `SELECTION_SEAL.json`。** 有权限的发布者需要把 `$HEPTA_POLICY_REPRO_RUN/SELECTION_SEAL.json` 的原字节提交到 `experiments/continuous_boundary_policy_reproduction/evidence/SELECTION_SEAL.json`，并公开到指定研究远端分支。旧研究和本次已交付研究的选择提交、原始归档均保留。新时钟和环境会改变选择封存；不得复用旧 selection commit、伪造本地 remote ref，或把未公开的本地提交视为预先公开。

获取本次实际公开的完整 40 位选择 commit 后：

```sh
git fetch origin \
  research/continuous-boundary-flow-20261028:refs/remotes/origin/research/continuous-boundary-flow-20261028
export HEPTA_POLICY_REPRO_SELECTION_COMMIT=REPLACE_WITH_ACTUALLY_PUBLISHED_NEW_SELECTION_COMMIT
python -m experiments.continuous_boundary_policy_reproduction.study confirm \
  --output "$HEPTA_POLICY_REPRO_RUN" \
  --native-binary "$HEPTA_POLICY_REPRO_NATIVE" \
  --score-binary "$HEPTA_POLICY_REPRO_SCORE" \
  --publication-commit "$HEPTA_POLICY_REPRO_SELECTION_COMMIT"
python -m experiments.continuous_boundary_policy_reproduction.audit confirmation \
  --study "$HEPTA_POLICY_REPRO_RUN" \
  --native-binary "$HEPTA_POLICY_REPRO_NATIVE" \
  --score-binary "$HEPTA_POLICY_REPRO_SCORE" \
  --output /tmp/hepta-policy-reproduction-new-confirmation-audit.json
python -m experiments.continuous_boundary_policy.engineering \
  --study "$HEPTA_POLICY_REPRO_RUN" \
  --score-binary "$HEPTA_POLICY_REPRO_SCORE" \
  --output /tmp/hepta-policy-reproduction-new-engineering \
  --ticks 8192 --checkpoint-interval 1024 --replay-ticks 16 --warm-ticks 4096
```

没有该分支写权限时，可先完成原样恢复、审计、训练和预确认检查，再交有权限的发布者完成 selection 公开。不能绕过公开条件打开确认。运行失败时保留部分输出和日志；阶段门禁止删除标记后重启，也禁止把重复 run 当作新增独立 seed。

## 6. 解释成本与验收结果

原四项比较、配对 seed、Bonferroni 同时区间、`0.005` 效应门槛和稳定性条件保持原样；不能根据本次确认结果增加 seed、换候选、改统计口径或与旧 0/4 合并。原报告的缺失 raw 仍是历史证据缺口，不能由新轨迹填充后改称“恢复”。

科学成本来自本次实际 `costs.jsonl`：共享模型/边界/DP、训练、开发、确认、序列化、原生子进程与通信分别核查。原始时钟不重写；包围阶段已包含其子窗口和子进程 CPU，不重复相加。连续策略每步按 24 个数值字节计价，native sparse 为 160；每 byte 扣 `1e-6`。四项主比较使用相同 24-byte 口径，完整 JSON 请求/响应 bytes 另计，不能把数值负载当成全部 wire 流量。

工程的 `overall_window_cost` 是含子窗口的总成本；warm/cold/native 数值是其中的子范围。编译、runtime 恢复、独立审计、归档和发布是外围操作，另保留成本，不并入原科学窗口。有限工程状态更新和冷恢复不增加收益样本，也不证明无限时域稳定性。

本实验没有硬件功率或焦耳测量，不能据事件少、观测少、闭式公式或 CPU 时间推出节能。有限决策/有限网格 Bellman 边界不能改称 He–Xiong 原模型的精确连续时间自由边界；source plan 保持 `DENY_ALL`，不触发生产 admission。
