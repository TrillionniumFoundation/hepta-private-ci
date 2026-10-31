# R8 交付的复现入口

从交付分支 `research/hcsn-five-track-verified-delivery-20261031` 的完整 checkout 根目录运行。先记录 `git rev-parse HEAD`，将结果与交付提交对应。以下步骤区分已有证据核验、冻结模型重放、新计时和原生重新构建；重复运行不产生新的独立确认样本。

## 1. 环境与证据恢复

本轮数值续验使用 Python 3.12.14、NumPy 2.3.5、SciPy 1.17.0，BLAS 单线程。NumPy 重放不需要 PyTorch；原训练和原 Torch 计时的环境记录仍在各自冻结文件中。依赖需由正常渠道安装，环境差异另记。

```bash
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
HCSN_RUN="$(mktemp -d /tmp/hcsn-r8-repro.XXXXXX)"

python3 tools/hcsn/round8_20261031/verify_delivery.py --output "$HCSN_RUN/delivery-files.json"

python3 tools/hcsn/round8_20261031/bundles.py verify state_task
python3 tools/hcsn/round8_20261031/bundles.py verify value_calibration
python3 tools/hcsn/round8_20261031/bundles.py verify native_owner

python3 tools/hcsn/round8_20261031/bundles.py restore state_task
python3 tools/hcsn/round8_20261031/bundles.py restore value_calibration
python3 tools/hcsn/round8_20261031/bundles.py restore native_owner
```

三组分卷共 12 卷、42,392,087 字节，外层索引分别登记 30、121、64 个成员。价值归档中的 121 项包含原 120 个证据文件及其索引。每卷、整包和成员内容均校验 SHA-256。已有同路径但不同字节的证据会拒绝覆盖；未登记路径、目录穿越和符号链接也拒绝。原生的 64 个外层成员包含三个内层原始 archive，外层恢复不自动递归展开它们。逐条 journal、witness、receipt 和内容输入的索引见对应 `RAW_RECORDS_MANIFEST*.json`。

这些是证据归档，不是新的训练数据。重新打包不是复现的必要步骤。

## 2. 事件动力学

```bash
python3 -m unittest tools.hcsn.round8_20261031.event_dynamics.test_event_dynamics -v
python3 -m tools.hcsn.round8_20261031.event_dynamics.tail_regression --output "$HCSN_RUN/tail.json"
python3 -m tools.hcsn.round8_20261031.event_dynamics.validation --output "$HCSN_RUN/event.json"
python3 -m tools.hcsn.round8_20261031.event_dynamics.resolution_audit --output "$HCSN_RUN/spatial.json"
```

本轮对应结果是 11 个行为测试、4 个尾部门、13 个事件律门和 9 个首达空间门通过。源码身份以 [总核验回执](event_dynamics/evidence/CONTINUATION_VERIFICATION.json) 为准。低噪声反例和近边界尾部用例属于检验的一部分；它们不支持整个参数域的统一精度结论。

重复事件的原 576 格上风方案有一个准确率门不通过，因此下面第一条命令**预期退出码为 1，输出中 `passed=false`**。要检查具体失败项，不能把任意异常都当作预期失败。

```bash
python3 -m tools.hcsn.round8_20261031.event_dynamics.renewal_resolution --output "$HCSN_RUN/renewal.json"
```

随后单独执行事先保存扩展协议的 1152 格计算；它使用原误差和收敛阶门槛，没有重写上一个结果：

```bash
python3 -m tools.hcsn.round8_20261031.event_dynamics.renewal_resolution_extension --baseline "$HCSN_RUN/renewal.json" --output "$HCSN_RUN/renewal-extension.json"
```

扩展的三个门应通过。数值误差随依赖版本可能有微小变动；约二阶 fitted、约一阶 upwind 和绝对误差门均应直接从新输出读取。此固定标量实验不能替代一般低噪声、非线性移动边界或耦合过程证明。

## 3. 冻结价值校准、轨迹重放与支持域

```bash
python3 -m unittest tools.hcsn.round8_20261031.value_calibration.test_value -v
python3 -m tools.hcsn.round8_20261031.value_calibration.audit \
  --prepared tools/hcsn/round8_20261031/value_calibration/evidence/prepared02 \
  --confirmation tools/hcsn/round8_20261031/value_calibration/evidence/confirmation01 \
  --output "$HCSN_RUN/value-confirmation-replay.json"

python3 -m tools.hcsn.round8_20261031.value_calibration.recovery.support_audit \
  --prepared tools/hcsn/round8_20261031/value_calibration/evidence/prepared02 \
  --freeze-sha256 da08baa4464b202a0071a2767d08009464f9b60e279c540332fc09ed042096ad \
  --output "$HCSN_RUN/value-support.json"
```

完整确认审计覆盖 61,440 对、444,930 个决策。支持域检查的 673 个 nominal 状态准入；三个已知偏移的状态全部拒绝。拒绝数不能算业务完成数。

以下两个分析程序重新构造完整有限 DP，并执行训练外诊断。它们默认写出同名 `RECOVERY_FINITE_VERIFICATION_20261031.json` 和 `RECOVERY_SHIFT_DIAGNOSTIC_20261031.json`，所以应在一次性复现 checkout/worktree 中运行，保留交付 commit 里的原回执以供比较。它们不改原 preparation、冻结模型或 confirmation。

```bash
python3 -m tools.hcsn.round8_20261031.value_calibration.recovery.verify
python3 -m tools.hcsn.round8_20261031.value_calibration.recovery.shift_diagnostic
```

本轮重新检查了 15 套 head × 673 个 nominal 状态及 45 套 shifted DP。只有 first_passage 模型族通过完整的原 nominal 修复门集合；clocked/direct 各自仍有未通过项。训练外结果是诊断，不能用于调参后再次声称同一保留集是未见确认集。

## 4. 历史压缩和风险预测

```bash
python3 -m unittest tools.hcsn.round8_20261031.state_task.test_task -v
python3 -m tools.hcsn.round8_20261031.state_task.replay --output "$HCSN_RUN/state-reviewed.json"
python3 -m tools.hcsn.round8_20261031.state_task.cost_replay \
  --reviewed-replay "$HCSN_RUN/state-reviewed.json" \
  --output "$HCSN_RUN/state-numpy-cost.json"
```

重放会核验 22 个冻结输入、30 个归档证据文件、四种场景的原始生成数据，并检查 106,496 个预测、动作与原摊销公式。预测绝对误差容差为 `3e-6`，保护动作必须一致。13 个预测器的重复输出仍对应原 8,192 个独立确认样本。

计时程序先落盘协议，再记录 468 个 batch 调用和 3,328 个 scalar 调用。它使用本机 NumPy 后端，分别记录加载、前向检查及服务工作；不能与旧 PyTorch 计时拼成未经声明的完整成本。时间结果受主机和缓存影响，不要求逐字节重现。新输出使用排他创建，不覆盖交付回执。

## 5. 原生 owner：fresh checkout 构建路径

先按第 1 节恢复 evidence。原始构建和最新构建的范围不同：本轮已经完成核验过依赖产物上的 fresh direct-rustc 构建、9 个新编译 Rust 测试、数值资格复跑、新内容成本实验，以及 fresh bootstrap 的 60 个源文件身份核验、manifest 解析和精确锁检查。**本轮没有执行从空缓存开始的 Cargo 下载或从空目标目录开始的 clean Cargo/just 构建。** 下列步骤提供该路径。

需要 Rust 1.96.0、真实的 `just` 和 `cargo-nextest`。以下 `/path/to/...` 由使用者替换为实际的新目录或已有正规工具路径。

```bash
git worktree add --detach \
  /path/to/pinned-main \
  732e934ba496d90fbe042b8d41d479ef901643e5

python3 tools/hcsn/round8_20261031/native_owner/bootstrap.py \
  --source-root /path/to/pinned-main \
  --existing-build /path/to/new-native-inputs \
  --cargo-cache /path/to/genuine-cargo-cache

CARGO_HOME=/path/to/new-native-inputs/cargo-home \
RUSTC=/path/to/rust-1.96/bin/rustc \
  /path/to/rust-1.96/bin/cargo fetch --locked \
  --manifest-path /path/to/new-native-inputs/Cargo.toml

python3 tools/hcsn/round8_20261031/native_owner/build.py \
  --build /path/to/new-native-owner-build \
  --existing-build /path/to/new-native-inputs \
  --workflow /path/to/pinned-main/codex-rs \
  --toolchain /path/to/rust-1.96 \
  --tools /path/to/genuine-just-and-nextest \
  --report /path/to/new-native-build-report.json
```

`--existing-build` 沿用旧参数名，但 bootstrap 要求该目录尚不存在；`--cargo-cache` 可以是空的正常 Cargo registry 缓存。若 pinned commit 不在 clone，先通过正常 Git fetch 取得。Cargo fetch 需要访问实际 registry，除非缓存已经完整。精确锁的 SHA-256 是 `6bbac28b4ea02636d97d28db3ede87a2fe096e764f5434395b755180505e15bf`；不重新求解锁，不使用 bridge 的另一套版本代替。

真实 binary 在 **`--existing-build/target/debug/codex-native-event-owner-r8`**，不在 `--build` 目录。fresh Cargo 与 direct-rustc 的链接设置可以不同，应记录新 binary 的真实 SHA-256，不能仅凭相同 Rust 源码摘要宣称二进制逐字节一致。

```bash
python3 tools/hcsn/round8_20261031/native_owner/qualify.py \
  --binary /path/to/new-native-inputs/target/debug/codex-native-event-owner-r8 \
  --out /path/to/new-native-qualification \
  --build-sha 58c5acd47498d5536293ae8223ed1b28ae8f87a21efd0467c801e46f4298d89b

python3 tools/hcsn/round8_20261031/native_owner/qualify_content.py \
  --binary /path/to/new-native-inputs/target/debug/codex-native-event-owner-r8 \
  --out /path/to/new-native-content-qualification \
  --build-sha 58c5acd47498d5536293ae8223ed1b28ae8f87a21efd0467c801e46f4298d89b
```

完整 clone 已含冻结内容模型，不需另取权重；稀疏 checkout 应物化 `CONTENT_SOURCE_IDENTITY.json` 中六个依赖路径。正常结果的 15 对配对包含 12 对正常输入与 3 对缺文件场景；后者应保留真实失败读取。`passed` 门控一致性和调用次数，完整 CPU 的差值另读结果，不把门控通过当作自动成本优胜。

## 6. 结果解释

连续 Brownian 合同、十五格点价值任务、五态 native cell 是三个不同数学模型。本交付没有声称已经把三者接成统一业务策略。普通 exact filter 与普通 event 调度必须保留为对照。宿主 Python 崩溃、任意中断原子恢复、开放内容质量、高维耦合误差和全局算法优势的未通过项见 [验收账本](BLOCKER_LEDGER.json)。
