# Native follow-up 复现与执行身份

## 固定材料与可复现范围

主 predictor/protocol 在远端 `9f885429cab68f1150a5155ef78b0eb9a68dd7e3` 发布，calibrator、supplement、dynamics、live hook、候选检验及 43 个冻结文件在 `1166eccb6e72ced755bcf1712349200a5a0f1a9c` 发布后才打开验证。实际 source/binary SHA 见 [FREEZE_READY_MANIFEST.json](FREEZE_READY_MANIFEST.json)、[NATIVE_BINARY_FREEZE.json](NATIVE_BINARY_FREEZE.json)。最终格式化若改变文本，精确重放应恢复这些已发布原字节。

原 native crate 固定 ref 为 `9595221c21f1fe0775295a9c8756a1ba4d69ea49`。本轮没有修改生产 core；原 `qualification-legacy-write` feature 只用于真实无签名 V1 历史诊断，不能当成正式 `LedgerWriter` 信任路径。构建过程复用上一轮原源校验、22-crate 隔离 workspace、原依赖版本及 Rust 1.95.0。[上一轮原生复现说明](../../abc_next/native/REPRODUCE.md) 给出工具链/cache 与428个原文件的准备方式。

用户要求原始数据、大 weights 和 binaries 不推 GitHub。本轮只发布源码、协议、详细报告、compact aggregate 和逐项身份。没有原件时可以审计方法与结果；不能声称已经完成逐字节重放。使用新输出目录重放已观察来源是复现，不能重新增加独立样本或独立资格。下一轮科学检验必须另行预注册真正未访问的来源。

```bash
export NATIVE_REPO=/workspace/scratch/2b3c256bef7d/hepta-ndu-recovery
export NATIVE_RAW=/workspace/scratch/2b3c256bef7d/abc4-native-runs
export NATIVE_PY=/workspace/scratch/2b3c256bef7d/ndu-env/bin/python
export NATIVE_AREA="$NATIVE_REPO/experiments/multimodal_output_portfolio/abc_followup/native"
export PATH="/workspace/scratch/2b3c256bef7d/task-tools/rust-1.95.0/bin:/workspace/scratch/2b3c256bef7d/task-tools/bin:$PATH"
export CARGO_HOME=/workspace/scratch/2b3c256bef7d/abc3-native-runs/cargo-home
export CARGO_TARGET_DIR="$NATIVE_RAW/target"
export CARGO_BUILD_JOBS=1
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
cd "$NATIVE_REPO"
```

协议内的 upstream generator、independent observer、source manifest、cache 路径与 SHA 都必须真实存在。路径迁移需要明确记录环境变更；不能只改 protocol 路径却继续使用旧 protocol SHA。`model-003` 是绑定最终协议的同一份原已训练 weights，前两次 model 目录仅反映验证前的 binding amendments，没有重新 fit。

## 原实际执行顺序

所有 Python 主入口都使用 root 共用 exact-PID receipt wrapper。以下是 shell helper，调用的模块及参数仍由 wrapper 原样记录；不读取或设置任何凭据环境变量：

```bash
native_run_python() {
  local native_receipt="$1"
  local native_module="$2"
  shift 2
  "$NATIVE_PY" -B -m experiments.multimodal_output_portfolio.abc_followup.process \
    --receipt "$native_receipt" \
    --module "experiments.multimodal_output_portfolio.abc_followup.native.$native_module" \
    -- "$@"
}
```

`process.py` 在启动前记录 wrapper/entrypoint SHA，用 `wait4(child.pid)` 收集实际 child 状态与 Linux rusage，并 fsync log；exit 非零的记录保留。native 执行由 `native_run.py` 核对 binary SHA 后 `os.execv`，使同一 PID 变为真实 Rust binary。

### 1. 历史 development 与拟合

原 collection 的 registration 使用保留的 DEVELOPMENT_PROTOCOL，实际输入维数为478；其最早描述中的510是已公开修正的元数据笔误。主协议显式接受这个固定历史 registration，防止把任意 development 数据改标为 calibration/verification。

```bash
native_run_python "$NATIVE_RAW/reproduction-development.process.json" collect \
  --protocol "$NATIVE_AREA/DEVELOPMENT_PROTOCOL.json" --role development \
  --output "$NATIVE_RAW/reproduction-development"
native_run_python "$NATIVE_RAW/reproduction-fit.process.json" qualify fit \
  --protocol "$NATIVE_AREA/PROTOCOL.json" --data "$NATIVE_RAW/reproduction-development" \
  --model "$NATIVE_RAW/reproduction-model"
```

这重新执行6,000历史来源对的真实prefix/两个未来分支及2,000步fit。模型选择仅看历史selection。新的 timestamps、process receipts 及freeze文件身份会不同；需按本次实际文件重新冻结，不能填入旧receiptSHA。实际原模型可直接使用保留的 `model-003`；不要覆盖它。

### 2. Calibration、冻结与一次 verification

以下完整流程是对已访问来源的复现。实际科学执行中 predictor freeze 已发布后才 calibration，calibrator及supplement全部发布后才 verification。再做一遍不产生新独立验证。若用于新科学研究，先替换真正未访问的来源并重新注册，不能沿用下面范围。

```bash
native_run_python "$NATIVE_RAW/reproduction-calibration.process.json" collect \
  --protocol "$NATIVE_AREA/PROTOCOL.json" --role calibration \
  --model "$NATIVE_RAW/reproduction-model" --output "$NATIVE_RAW/reproduction-calibration"
native_run_python "$NATIVE_RAW/reproduction-calibrator.process.json" qualify calibrate \
  --protocol "$NATIVE_AREA/PROTOCOL.json" --data "$NATIVE_RAW/reproduction-calibration" \
  --model "$NATIVE_RAW/reproduction-model"
```

原 supplementary registration 与 live hook 绑定的是原 `model-003` 的 freeze、历史数据和原 binary 路径。对重新生成的新 freeze/receipt，应建立明确标为复现的新 supplement/hook registration，逐项更新实际 SHA；不能拿旧 registration 冒充相同 byte identity。下面使用**保留的原件**演示已经正式执行过的 verification 和 analysis，其新输出目录只是复现：

```bash
native_run_python "$NATIVE_RAW/reproduction-verification.process.json" collect \
  --protocol "$NATIVE_AREA/PROTOCOL.json" --role verification \
  --model "$NATIVE_RAW/model-003" --output "$NATIVE_RAW/reproduction-verification"
native_run_python "$NATIVE_RAW/reproduction-primary.process.json" analysis \
  --protocol "$NATIVE_AREA/PROTOCOL.json" --data "$NATIVE_RAW/reproduction-verification" \
  --model "$NATIVE_RAW/model-003" --output "$NATIVE_RAW/reproduction-primary"
native_run_python "$NATIVE_RAW/reproduction-prospective.process.json" prospective \
  --protocol "$NATIVE_AREA/PROTOCOL.json" \
  --supplement "$NATIVE_AREA/PROSPECTIVE_ADAPTER_PROTOCOL.json" \
  --data "$NATIVE_RAW/reproduction-verification" \
  --calibration-data "$NATIVE_RAW/calibration-001" \
  --model "$NATIVE_RAW/model-003" --output "$NATIVE_RAW/reproduction-prospective"
native_run_python "$NATIVE_RAW/reproduction-candidates.process.json" candidate_verify \
  --protocol "$NATIVE_AREA/PROTOCOL.json" \
  --registration "$NATIVE_AREA/CANDIDATE_PROTOCOL.json" \
  --data "$NATIVE_RAW/reproduction-verification" --output "$NATIVE_RAW/reproduction-candidates"
```

`candidate_verify` 另依赖已冻结旧 head candidates/weights/calibration 原件，全部路径和 SHA 在 CANDIDATE_PROTOCOL。它不是新 future head 的 independent acceptance。

### 3. 构建与原 native 两条实际尝试

从匹配原crate source的checkout准备新目录，再构建新研究bin；不运行完整Agentd或改生产workspace：

```bash
native_run_python "$NATIVE_RAW/reproduction-build.process.json" build \
  --source "$NATIVE_REPO" --output "$NATIVE_RAW/reproduction-build"
cargo build --offline --release \
  --manifest-path "$NATIVE_RAW/reproduction-build/Cargo.toml" -p codex-native-head
```

已保留的原实际 binaries 位于 `native-binaries-006`。continuous SHA 为 `b30b813104776c6af619f3004cc8475e9d4f4916650fae2e1afcfed8b79480b6`，proposal SHA 为 `82e5b79d27f7a777fe0dbbf31e525bd4d44b411ee2c3c97ddc53b20269c9bfe1`。以下先准备不同契约的 packet；即使预知原 residual 契约会失败，也真实调用原 bootstrap 以保留准确第一错误。

```bash
native_run_python "$NATIVE_RAW/reproduction-residual-packet.process.json" packet \
  --protocol "$NATIVE_AREA/PROTOCOL.json" --supplement "$NATIVE_AREA/PROSPECTIVE_ADAPTER_PROTOCOL.json" \
  --model "$NATIVE_RAW/model-003" --data "$NATIVE_RAW/verification-001" \
  --verification "$NATIVE_RAW/verification-analysis-001/verification.json" \
  --contract state_residual --dynamics legacy --output "$NATIVE_RAW/reproduction-residual-packet"
native_run_python "$NATIVE_RAW/reproduction-future-packet.process.json" packet \
  --protocol "$NATIVE_AREA/PROTOCOL.json" --supplement "$NATIVE_AREA/PROSPECTIVE_ADAPTER_PROTOCOL.json" \
  --model "$NATIVE_RAW/model-003" --data "$NATIVE_RAW/verification-001" \
  --verification "$NATIVE_RAW/prospective-verification-001/verification.json" \
  --contract future_correctness --dynamics bounded_balanced \
  --hook "$NATIVE_AREA/freeze-v1/live-proposal-config.json" \
  --output "$NATIVE_RAW/reproduction-future-packet"
```

每个新 packet 写入自己的host/timestamp，因此SHA会变化。执行新packet时必须使用其真实receipt中的SHA。下面使用保留的两个原packet及其真实SHA，不假设新packet有相同身份：

```bash
native_run_python "$NATIVE_RAW/reproduction-residual-native.process.json" native_run \
  --binary "$NATIVE_RAW/native-binaries-006/codex-native-continuous" \
  --binary-sha256 b30b813104776c6af619f3004cc8475e9d4f4916650fae2e1afcfed8b79480b6 \
  -- "$NATIVE_RAW/residual-packet-001/packet.json" \
  2608cd7e3002efbb7764948c2748fc29881ae2fef2217ef898dd85f2ebdbca07 \
  "$NATIVE_RAW/reproduction-residual-native"
native_run_python "$NATIVE_RAW/reproduction-future-native.process.json" native_run \
  --binary "$NATIVE_RAW/native-binaries-006/codex-native-continuous" \
  --binary-sha256 b30b813104776c6af619f3004cc8475e9d4f4916650fae2e1afcfed8b79480b6 \
  -- "$NATIVE_RAW/future-packet-001/packet.json" \
  59de69591388b1a9858e4e3b47aa7fb2488d3b2512fddb27048f2b0fa6611173 \
  "$NATIVE_RAW/reproduction-future-native"
```

future continuous会自动执行冻结的same-head hook，包含两个nativeproposal subprocess、historical functional evaluation、pendingregistry/witness恢复、同anchor runtime恢复。它必须有实际first-admittedID≥800；找不到则真实失败，不用短流或另选好点补足。

新运行的host timing/resource receipt进入journal身份，整个anchorSHA通常不会与原运行相同。应核对该次运行内部的完整前驱链、同weights/objective/subject、actualanchor、eligibility、NDUprojection、候选/提案及恢复的绑定，而非要求跨运行时间字段相同。重放不证明更新已应用；两条路径始终`DENY_ALL`。

### 4. 全部媒体/commit audit 与 scoped tests

```bash
native_run_python "$NATIVE_RAW/reproduction-evidence-audit.process.json" evidence_audit \
  --protocol "$NATIVE_AREA/PROTOCOL.json" --data "$NATIVE_RAW/verification-001" \
  --model "$NATIVE_RAW/model-003" --output "$NATIVE_RAW/reproduction-evidence-audit.json"
cd "$NATIVE_REPO/codex-rs"
just test --offline --release \
  --config-file /workspace/scratch/2b3c256bef7d/abc3-native-runs/build-001/nextest-scoped.toml \
  --manifest-path "$NATIVE_RAW/build-001/Cargo.toml" \
  -p codex-native-head --bin codex-native-continuous --bin codex-native-proposal \
  --test-threads 1
```

最后这条是原实际执行命令，结果6/6，见 [SCOPED_TEST_RECEIPT.json](SCOPED_TEST_RECEIPT.json)。若使用新reproductionbuild，替换manifest路径并保留实际receipt；如果最终fmt已运行，遵守仓库说明不在fmt之后重跑测试。没有以CI、全仓测试或生产daemon qualification替代本轮具体执行。

## 不应复制的捷径

不要把已读verification改标calibration；不要在失败后换p bin、threshold、候选尺度或sourcewindow而继续引用原冻结协议；不要把observed32坐标称作未来预测；不要给research ledger填任意head、签测试身份或把pendingproposal当appliedupdate；不要把旧head候选与新futurehead stream拼成闭环。真实productAPI、必需外部owner/signature输入及单journal部署接口范围见 [AUTHENTIC_HANDOFF.md](AUTHENTIC_HANDOFF.md)。
