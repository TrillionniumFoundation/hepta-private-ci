# 原生切片复现与验证回执

## 身份与构建边界

上游源 ref 为 `9595221c21f1fe0775295a9c8756a1ba4d69ea49`。新实验实际运行的九个 Python/Rust 核心文件原字节固定在远端 commit [`9d48cb518fcd457f58eb23d068e6b1bf934b2dc2`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/9d48cb518fcd457f58eb23d068e6b1bf934b2dc2)，完整 tree `56f020dbb43bd745865603a69b47bb711a1918f1`，与本地 `9b639d56c226624514006c4c65aa65efc1448a4f` 相同。逐文件 SHA 在 [EXECUTED_SOURCE_PINS.json](EXECUTED_SOURCE_PINS.json)。复现前必须恢复相同源字节、generator、observer 与 source manifest；完整结果、选定参数与来源大文件未推 GitHub，只有本地 SHA 索引。没有这些原件时可以检查源码与报告，不能声称精确重放已完成。

本地实验根为 `/workspace/scratch/2b3c256bef7d/abc3-native-runs`。以下命令使用新的 `reproduction-*` 目录，不覆盖实际记录。重放已经观察的 calibration/verification 来源只属于复现，不产生新的独立资格；下一次科学验证必须重新冻结尚未访问的来源与协议。

实际工具为官方 Rust 1.95.0、cargo-nextest 0.9.149、仓库 `just`。安装前按官方 manifest 检查组件 SHA；官方 Rust manifest SHA `821ff14e4c4a1cbe1e8915f35aff0a3fbbdf8d293ad48ab8f31e3b0440c581f9`；nextest 下载包 SHA `32d1d8c0567b7a80bee2bad8bb09125c846da96bc009b2de11ec08557290c770`。下载/安装 receipts 与清理 receipts 的 SHA 在证据索引。

初始化变量（真实运行时 repo root 为下列路径）：

```bash
export NATIVE_REPO=/workspace/scratch/2b3c256bef7d/hepta-ndu-recovery
export NATIVE_RAW=/workspace/scratch/2b3c256bef7d/abc3-native-runs
export NATIVE_PY=/workspace/scratch/2b3c256bef7d/ndu-env/bin/python
export NATIVE_AREA="$NATIVE_REPO/experiments/multimodal_output_portfolio/abc_next/native"
export PATH="/workspace/scratch/2b3c256bef7d/task-tools/rust-1.95.0/bin:/workspace/scratch/2b3c256bef7d/task-tools/bin:$PATH"
export CARGO_HOME="$NATIVE_RAW/cargo-home"
export CARGO_TARGET_DIR="$NATIVE_RAW/reproduction-target"
export CARGO_BUILD_JOBS=1
```

`build.py` 从完整固定 checkout 检查 428 个原文件的 SHA，才创建 22-crate 隔离 workspace。新 harness 以实际 core crate/原字节 Agentd module 实现运行，不重写 owner。该脚本修改的只是隔离 workspace manifests，未改生产 Cargo/Bazel 配置。原 workspace globally enabled 的某些无关 features 在缩小 workspace 中不会统一进来；不把它称为完整生产 build。

```bash
cd "$NATIVE_REPO"
"$NATIVE_PY" -B -m experiments.multimodal_output_portfolio.abc_next.native.build \
  --source "$NATIVE_REPO" --output "$NATIVE_RAW/reproduction-build"
cargo build --offline --release \
  --manifest-path "$NATIVE_RAW/reproduction-build/Cargo.toml" \
  -p codex-native-head
```

初始隔离 lock 从原 `codex-rs/Cargo.lock` 复制，Cargo 可以在隔离目录更新因移除 members 与增加 harness 所需的结构。实际发布 binary 所用依赖版本来自原 lock；最终 isolated lock 与 preparation receipt 的 SHA 在证据索引。缓存不齐时应先合法获取所缺 registry 依赖，不能用重新实现 runtime 替代。`profile.dev/test/release debug=0`、单 build job 限制共享内存与磁盘。

## 实际训练与一次资格流程

原实际输出目录依次为 `predictor-train-001`、`predictor-model-001`、`calibration-001`、`verification-001`。协议先写好并固定，后续严格按此顺序：

```bash
cd "$NATIVE_REPO"
"$NATIVE_PY" -B -m experiments.multimodal_output_portfolio.abc_next.native.collect \
  --protocol "$NATIVE_AREA/PROTOCOL.json" --role train \
  --output "$NATIVE_RAW/reproduction-train"
"$NATIVE_PY" -B -m experiments.multimodal_output_portfolio.abc_next.native.qualify fit \
  --protocol "$NATIVE_AREA/PROTOCOL.json" --data "$NATIVE_RAW/reproduction-train" \
  --model "$NATIVE_RAW/reproduction-model"
"$NATIVE_PY" -B -m experiments.multimodal_output_portfolio.abc_next.native.collect \
  --protocol "$NATIVE_AREA/PROTOCOL.json" --role neuron_calibration \
  --prerequisite "$NATIVE_RAW/reproduction-model/predictor-freeze.json" \
  --output "$NATIVE_RAW/reproduction-calibration"
"$NATIVE_PY" -B -m experiments.multimodal_output_portfolio.abc_next.native.qualify calibrate \
  --protocol "$NATIVE_AREA/PROTOCOL.json" --data "$NATIVE_RAW/reproduction-calibration" \
  --model "$NATIVE_RAW/reproduction-model"
"$NATIVE_PY" -B -m experiments.multimodal_output_portfolio.abc_next.native.collect \
  --protocol "$NATIVE_AREA/PROTOCOL.json" --role neuron_verification \
  --prerequisite "$NATIVE_RAW/reproduction-model/calibrator-freeze.json" \
  --output "$NATIVE_RAW/reproduction-verification"
"$NATIVE_PY" -B -m experiments.multimodal_output_portfolio.abc_next.native.qualify verify \
  --protocol "$NATIVE_AREA/PROTOCOL.json" --data "$NATIVE_RAW/reproduction-verification" \
  --model "$NATIVE_RAW/reproduction-model"
```

Access-registration 在读取指定 role 前持久化，包含 phase、前置 freeze SHA、protocol SHA、固定 segments 和 source identity。Fitting 只用 train；calibration 只用 calibration；verification 前核对全部冻结文件。程序可以复现研究流程，但不是独立硬件隔离的 holdout-release authority；本轮的一次打开事实由保留的访问/冻结链与工作记录支持。

训练全流程成本复现只打开 train，权重与 cuts 完全复现，不再次执行上述两个 reserved role：

```bash
"$NATIVE_PY" -B -m experiments.multimodal_output_portfolio.abc_next.native.training_cost \
  --protocol "$NATIVE_AREA/PROTOCOL.json" \
  --original "$NATIVE_RAW/predictor-model-001" \
  --output "$NATIVE_RAW/reproduction-training-cost"
```

## 实际 native 二进制重放

执行过的原 binary 已保存在 `native-binaries-001`，SHA 如下。Cargo `target` 中间文件已清理，不能把缺失的旧 target 路径当成 binary 丢失。

| Binary | 大小 | SHA-256 |
| --- | ---: | --- |
| `codex-native-head` | 1,367,648 B | `c65028b26325a076a66c641b1c269e23dbca22e1d6705f81aa4a94afb7860fc6` |
| `codex-native-proposal` | 1,896,448 B | `1cf418ce1b29c100337f2d44e0efe02b980f756feef7a8f4b1e71dde57049b06` |

原 packet 绑定实际 weights/calibration/verification paths 与每行公开特征、观测标签 digest。其 SHA 为 `11e883c9a9bf5549979745e4fccad89e681493e7886e32f89369f7c20fc4606f`。以下使用保留原件重放：

```bash
"$NATIVE_RAW/native-binaries-001/codex-native-head" \
  "$NATIVE_RAW/native-packet-001/packet.json" \
  11e883c9a9bf5549979745e4fccad89e681493e7886e32f89369f7c20fc4606f \
  "$NATIVE_RAW/reproduction-native-execution"
"$NATIVE_RAW/native-binaries-001/codex-native-proposal" \
  "$NATIVE_RAW/native-packet-001/packet.json" \
  11e883c9a9bf5549979745e4fccad89e681493e7886e32f89369f7c20fc4606f \
  "$NATIVE_RAW/native-execution-001" \
  "$NATIVE_RAW/reproduction-candidates"
"$NATIVE_PY" -B -m experiments.multimodal_output_portfolio.abc_next.native.evaluate_candidate \
  --candidates "$NATIVE_RAW/reproduction-candidates/candidates.json" \
  --model "$NATIVE_RAW/predictor-model-001" --data "$NATIVE_RAW/predictor-train-001" \
  --output "$NATIVE_RAW/reproduction-candidate-evaluation.json"
"$NATIVE_RAW/native-binaries-001/codex-native-proposal" \
  "$NATIVE_RAW/native-packet-001/packet.json" \
  11e883c9a9bf5549979745e4fccad89e681493e7886e32f89369f7c20fc4606f \
  "$NATIVE_RAW/native-execution-001" \
  "$NATIVE_RAW/reproduction-proposal" \
  "$NATIVE_RAW/reproduction-candidate-evaluation.json"
```

没有 evaluation 参数时只构造候选并执行真实 product admission 拒绝；加入真实 development evaluation 后调用原核心 `propose_v2` 与 durable registry。两者都保持 `DENY_ALL`。因为实际执行 receipts 包含时间/资源等非确定字段，新运行的整个 journal/anchor SHA 不要求与旧运行逐字节相同；必须核对该次运行内部的 objective、subject、acknowledged checkpoint、eligibility、projection 与候选/提案链一致。原 proposal 示例特意使用 `native-execution-001` 保留的原上下文。

## 实际 scoped test 回执

实际工作目录为 `/workspace/scratch/2b3c256bef7d/hepta-ndu-recovery/codex-rs`。实际 manifest 为 `abc3-native-runs/build-001/Cargo.toml`，target 当时为 `abc3-native-runs/target`。测试入口遵循 AGENTS 的 `just test`，没有直接调用 `cargo test`。

```bash
cd "$NATIVE_REPO/codex-rs"
just test --manifest-path "$NATIVE_RAW/build-001/Cargo.toml" \
  -p codex-hepta-neuron -p codex-hepta-plasticity \
  --config-file "$NATIVE_RAW/build-001/nextest-scoped.toml" \
  --test-threads 1
just test --manifest-path "$NATIVE_RAW/build-001/Cargo.toml" \
  -p codex-native-owner-bridge \
  --config-file "$NATIVE_RAW/build-001/nextest-scoped.toml" \
  --test-threads 1
```

隔离 nextest config 保留原 default/local 的 slow-timeout、retries=1、JUnit 设置；仅移除引用本隔离 workspace 不存在 package 的 overrides。原文件未改。

| 回执 | Cases | Failure / error / skipped | SHA-256 |
| --- | ---: | --- | --- |
| `test-receipts/core-135.xml` | 135 | 0 / 0 / 0 | `bbfbd8b574de8d83a140c01307941ca1a1c51939aea7d50f570305f5a75d7081` |
| `test-receipts/owner-16-upstream-lock.xml` | 16 | 0 / 0 / 0 | `40b06bfab55757157030fa0501b58b3b9653f676793a8e5ff0b8f617fd17737b` |

Owner bridge 的正式回执采用原 lock 的 tempfile 3.27.0；之前 3.26.0 的 16-case receipt 作为历史保留但不累计测试数。没有生产 Rust 源改动，不触发 common/core/protocol 全仓测试 gate；没有运行全仓或伪称远端 CI 通过。

## 格式化与执行身份

AGENTS 要求的最终格式化已由协调 agent 实际执行，退出码 0；[FINAL_FORMAT_RECEIPT.json](FINAL_FORMAT_RECEIPT.json) 保留前后 SHA、完整 cwd/command 和不重跑 tests 的事实。实际命令为：

```bash
cd /workspace/scratch/2b3c256bef7d/hepta-ndu-recovery/codex-rs
PATH="/workspace/scratch/2b3c256bef7d/task-tools/rust-1.95.0/bin:/workspace/scratch/2b3c256bef7d/task-tools/bin:$PATH" just fmt --base ee824c94f55018927a937d16fa8a96ed2627fa0a
```

该运行发生于原执行源码已发布后，格式化差异单独提交。此前另一个并发 agent 曾提前执行全局 `just fmt`，改动了 4 个实验 Rust 文件；本 agent 随即从 retained execution source 核验 SHA 后恢复原字节，保证原实际执行版本先进入 Git 历史。事件、观察到的格式化 SHA、原执行 SHA、恢复事实在 [FORMAT_SOURCE_IDENTITY.json](FORMAT_SOURCE_IDENTITY.json)。没有重开 reserved 数据，没有重跑训练来掩盖源码变化。最终格式化不改旧 artifact identity；依 AGENTS，未在 final fmt/fix 后再重跑测试。
