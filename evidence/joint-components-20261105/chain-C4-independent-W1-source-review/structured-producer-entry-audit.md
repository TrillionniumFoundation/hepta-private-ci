# C4 已有 Sparse / zero / one-zero 计量入口

冻结源码：`8df4b21d893906570d48f5beafabb3b31e0aefbc`，tree `6f5aaa2af0432e27e24b6bd2ad18013ab4423d14`。只读审查；未启动任何 Cargo 或 native 采样；没有更改冻结源码。

**已有可直接执行的 C4 程序真正调用 Sparse、BlockedZero、BlockedOneZero API，不需要新增外部 Rust harness，也不需要复制算法。** 原 `legal-strategy-v3` 保持执行；以下结果使用各自独立 receipt，不合并成原 v3 的相同网格。

## 1. 完整枚举依据

从 exact C4 Git tree 读取 11,538 个条目，`truncated=false`。枚举全部 `*/examples/**/*.rs`：61 个文件（含 support）、1,235,775 字节。每个本地副本的 Git blob 与长度都匹配该树。完整清单及直接 Sparse API 命中见 [example-byte-audit.json](sandbox:/workspace/scratch/93bfcfe29fc8/pq_recovery/w1-independent-c4/example-byte-audit.json)，SHA256 `c722e4572d9754b23fa642e6d16abb5dbf516fd91ad8edadba88f3983c484296`。

直接 `Preparation::Sparse` / `Task::with_preparation` 计量入口是：

- `trillionnium/crates/trnm-crypto-primitives/examples/pon_work_expensive_v1.rs`，blob `c258df9b422991ed29b56d03d7f43c7b6d125a9d`。
- `trillionnium/crates/trnm-crypto-primitives/examples/pon_shared_material_v1.rs`，blob `9df0e4a48cfc62d6cca4aea9b26a98eca107b361`。

还读取全部 19 个当前 workflow 字节；13-arm reused-v3 的直接调用实际位于 `.github/workflows/trnm-required-baseline.yml`，job `cross-arch-w1-reuse-v3`，总时限 **155 分钟**，不是另两个 W1 workflow 的 55/60 分钟。该 job 的矩阵为 x64/arm64 × head/prospective-merge，前后保留 source guards。两个 Sparse campaign owner 未出现在这 19 个 workflow 的直接调用文本中；这不等于排除了所有间接 owner。记录见 `workflow-entry-scan.json`。

## 2. 可用入口与口径

| 已有入口 | 实际算法和任务 | 实际复用单位 | 边界 |
| --- | --- | --- | --- |
| `scripts/ci/run_w1_reused_cost_v3.py --arch x64 --local` | 13 arms；有 BlockedZero、zero paired、BlockedOneZeroRankOne、maintenance 专用族；9 个确定性材料 | 每 sample/arm 实际一个 setup，存活到 4 次完整搜索结束；8 samples；nonce cap 4096；target 固定 `7f…ff` | 不含 Preparation::Sparse；不是 H=1/8/64、双 target 的 legal v3；unsupported 明确保留，没有 fallback |
| `pon_work_expensive_v1 --work-expensive-v1 …` | 15 arms，含 Dense lazy-full-limb、Sparse lazy-full-limb，以及上述结构算法；默认9材料，也可 `--material` 读一对精确 A/B | `--reuse` 是 **attempt 次数**；每 epoch 真实 setup，最多该数量 attempts 后真实 drop；直到固定总 attempts 用完，不在 hit 后停止 | schema 已为 `pon-work-expensive-native-v2`；旧 selector 名称不变；不是搜索到 winner 的 H；会明确记录 primitive-only/native-branch-unaccepted |
| `pon_shared_material_v1 --shared-material-v1 … --preparation sparse` | 同一调用方提供的 canonical A/B；可选 Dense/Sparse 与 Transposed/FullLimb；proof 为 target-hit 物化 | 恰一个 Task setup 跨 `--cycles` 次完整首 hit 搜索，cycles 1–64，max attempts 1–4096 | stdin 恰 32,768 字节；必须显式 target-index 和 seed；有 native+scalar full verification 后 typed product handoff，仍是 offline primitive，不能借此声明节点/数据授权 |

### 2.1 13-arm owner 的原命令与门禁

`run_w1_reused_cost_v3.py` 使用 Rust 1.95.0、`--locked --release`、目标 native triple，实际 build 上限 900s、单 native campaign 300s、TERM grace 5s；原 reader 是 `scripts/pon_w1_reused_cost_reader_v3.py`。已确认完整 constructor lifetime 在 `pon_w1_reused_cost_v3.rs::cohort`：只调用一次 `Producer::new`，`Some(producer)` 借用到四次 search 完成。每次 search 包括所有 miss、完整 proof、SHA/hex 与保留记录；JSON 输出、stream comparison、verifier 在计时之外。

该 owner 自己没有 `TRNM_EXPECTED_SOURCE_SHA` 比对；hosted job 在外层前后调用 `verify_ci_source`。本地增补也必须在外层硬核 exact C4 before/after 并核原 manifest，不能仅因设置了该环境变量便声称脚本验证过它。执行者已知此边界。

### 2.2 15-arm census 是现成的最小 Sparse 对照

`Producer::new` 的 arm 0 调 `Task::new(a,b,FullLimb)`；arm 14 调 `Task::with_preparation(a,b,FullLimb,Sparse)`。二者 `Producer::attempt` 都调同一公开 `Task::attempt(challenge,target,TargetHit)`。因此这一对在同一次 census 中只改变 preparation，支持域都是全部 canonical 64×64 field matrices，不是把不同 materialization 和 arithmetic 混成一个效应。[example:249–296]

公开 CLI：

```text
pon_work_expensive_v1 --work-expensive-v1
  --attempts 64 --samples 8 --reuse 16
  --target-index 0|1 --seed <预先冻结的64位小写hex>
  [--material <恰32768字节的A随后B>]
```

以上 64/8/16 是现成 campaign owner 的默认值；native example 自身默认值为 32/3/32。不能混称二者。`--attempts`、`--reuse` 的原范围是 1–1024，samples 1–16；原 reader 的 calibration/evaluation 需要另遵其约束。真实 observation 按传入 argv 记，不把默认值当实际执行值。

`execute_cell` 对 fixed attempt sequence 连续执行，包括 hit 后的后续 attempts。每 epoch 保存 setup generation、task cache key、intended/actual attempts、actual hits、teardown 和实际 cached lifetime。producer 成本是四个互不重叠分项之和：setup + attempt（含 challenge）+ 每 attempt proof cleanup + epoch teardown。continuous observed-cell timer 包含 verifier/audit/output，和这些分项重叠，不能再相加。hit 时实际运行 current native full-limb 与 scalar reference 并核 product/task/challenge/ticket。miss 的 trace/ticket 仍完整生成；不是将一个零字节 proof 当作免费 miss。[example:411–577]

现成 reader：

```text
python3 scripts/pon_work_expensive_reader_v1.py <native.jsonl>
  --out <新文件.json> --calibration-samples 2
```

它支持 v2 的 15 arms，先以较早 calibration samples 的 aggregate producer CPU 选一个固定 arm，再在后续 samples 评价；不会为每个 evaluation sample 重新挑最快 arm。1/5/20ms 默认 prefix budgets 只计已实际完成并销毁的 cache epoch，是事后观察，不是实际中途停止或 network credit。reader 显式令 `gamma`、`gamma_upper_bound`、`native_branch_accepted_work` 为 null，work-hardness false。[reader:315–374]

完整现成 owner 是 `scripts/ci/run_work_expensive_campaign_v1.py`，blob `dba09f0efa05ef56595dc764c9a89c8595b58063`：

```text
python3 scripts/ci/run_work_expensive_campaign_v1.py
  --native <pon_work_expensive_v1的实际ELF>
  --shared-native <pon_shared_material_v1的实际ELF>
  --material-dir <真实已有材料目录> --out <新receipt目录>
```

默认参数：64 attempts、8 samples、reuse16、targets 0和1、calibration2、每 native invocation 300s。它先冻结材料/seed，再执行 shared-material 与 synthetic/真实材料 census；需要真实 material-dir，不能用臆造路径/输入补足调用。它允许的 timeout 参数上限不是本轮放宽预算的授权。

**该 owner 不构建二进制。** `source_identity()` 明确 `head_tree_is_executed_source=false`，记录观察到的 worktree source manifest，并要求另外保留真实 build command/build manifest。使用它补 C4 必须由外层先执行 exact C4 完整 source/锁依赖/原 release configuration guard，绑定实际编译产物、ELF hashes、前后 source/config 与本地硬件。仅有 Git HEAD 或一个 native 路径不足以获得 C4 source/binary 资格。本轮没有启动上述任何命令。

### 2.3 Shared-material Sparse 的原 paired campaign

`pon_shared_material_v1.rs:483` 直接调用 `Task::with_preparation`，并在一次函数 `run` 中持有同一个 Task 到所有 cycles 完成。每个 search 首 hit 停止或完整 cap 耗尽，计入 challenge、完整 attempt、trial retention；input/setup、record build、serialization/output 与 verification分列。`--preparation` 会显式选择 v2 schema；它不是名字里含 sparse 却仍走 Dense。

已有 owner：`scripts/ci/run_shared_material_campaign_v2.py`（blob `e12c65f67b8674500b834b26bf7e9a4d2a071a60`），调用 `formal/pon-nakamoto-v1/experiments/shared_cell_operator_v1.py`，并用 `scripts/ci/shared_material_cost_v2.py` 读取结果。

```text
python3 scripts/ci/run_shared_material_campaign_v2.py
  --model-dir <真实model目录> --bundle-hash <实际bundle hash>
  --runner <pon_shared_material_v1的实际ELF> --out <新目录>
```

默认3 repeats产生31 case：24项两target×两arithmetic×Dense/Sparse配对；4项 sparse verifier fanout（3和8次同进程顺序 full replay）；2项 sparse cycles4；1项真实一尝试 exhaustion 负控。该 owner 原固定 child consumer 360s、每 tile native 60s，不能换成另一个实验的300s来冒充此门禁。fanout 的 verifier 是同一进程内顺序调用，不是独立节点或独立管理员。

此 paired campaign 使用实际 model/task/evaluation bundle，而非默认 synthetic zero/one-zero 集合。要测某 canonical zero 材料，可以调用现有 native CLI并提供真实32KiB bytes，但结果应另列为对应 native observation，不能声称跑过上述完整 model campaign。

## 3. canonical zero / one-zero / sparse 到底是否合法

### 关系与材料配方：允许

`pon_work.rs::validate` 只检查长度恰4096及每 word `<q`，`task_id` 对 canonical A/B 编码哈希；无非零、满秩或最小密度条件。[C4 blob `ce1608248d2ee67ed8f5d82a2c5f15942689139b`:174–187]

`qualified_work_task::derive_matrices` 将两份各16KiB材料直接解码为 canonical LE32矩阵，同样无 rank/zero排除；验证 admission 还将原材料hash、导出A/B与 manifest.matrix_task绑定。[crypto `qualified_work_task.rs` blob `f93c80070b75ca1219b174c66db50dbda3003da9`:83–105、221–253]

因此，在精确任务材料被合法承诺的条件下，零或稀疏结构不是违反 W1 关系的作弊。Sparse preparation 先验证所有字段；即使某零乘积本可跳过，也不能隐藏 noncanonical input。

### 普通节点资格：另有必要条件

`mining.rs::prepare_registered_material` 根据当前 parent/height获取状态。固定 maintenance 路径要求当前 task就是 consensus maintenance task，且 model/input bytes恰等于固定 maintenance材料；不能把它替换成任意零矩阵。其余任务走当前 PQ tasks_v5、生命周期签名 lease或 signed manifest admission。材料必须绑模型/输入/task，且通过当前状态的授权和需求资格。[C4 mining blob `4615e6b0c7fa5d088266a378400fa459e9d09c19`:320–430]

`operator_task_policy.rs` 对 `instance_class` 明确接受 `dense | structured | zero`，但还验证当前签名 policy/context、nonce范围和资源分配。声明 `preprocessing=exact-task-input-only` 必须有 prepared_artifact、setup_record、positive reuse_uses；`forbidden` 则要求这些artifact为空且reuse=0。这表明零类和复用是明确建模的许可范围，不是“输入一串零就自动获得普通节点授权”。[blob `a65d081d786a5f9204e9ab458f58009969237c99`:529–578]

本轮未声称当前公开节点已存在允许任意人提交 benchmark zero task的有效 operator policy、live demand/lease或注册记录；这些需要真实运行上下文，不能由离线数学成功补造。

## 4. losing attempt 是否仍付完整 trace

在当前 Sparse API中：是。Preparation只改变 challenge-independent AB/prefix setup；`Task::attempt_with_progress` 对 Dense/Sparse 使用同一个完整 `evaluate_transcript_kernel_with_progress`，结束后才计算 ticket。TargetHit省的是 miss 的 proof allocation/serialization；没有省掉完整合法 trace。当前Task保存A/B/prefix，不保存一个可跨挑战复用的正确trace。[legal_attempt.rs:104–161]

BlockedZero/BlockedOneZero也完整产生原序的所有 transcript digest bytes，但可用输入结构和代数重排降低实际计算/存储成本；不能把“完整trace”解释为“必须执行通用Dense producer同样多、同样慢的算术”。这些方法的 prefix按 exact A/B复用；每新challenge仍重新展开噪声并计算对应完整trace。实际性能需要上述本次 native成本，算法名或运算数不替代测量。

另外，正确trace成本只针对合法 proof。伪造 trace_claim 的攻击者可先做便宜ticket search再迫使victim replay，这条无效输入成本不能重新记成完整合法producer费用；见主审查报告第6节。

## 5. 各 suite 的材料和挑战不可混池

原 legal-v3 / 13-arm reused-v3 的 one-zero counterpart 是 `(row+1)*(column+2)`；15-arm census 是 `(row+1)*(column+3)`。三个 suite 的 challenge domain分别是 legal-strategy-v3 / reused-v3 / work-expensive-v1。相似材料类别名称不代表同一task、nonce stream或采样单位。

每个 suite内部有实际匹配条件。比较其内部arms可以使用同task/stream证据；跨suite只能清楚列出不同材料/挑战/复用单位的独立观测，不能拿比率直接拼成同一固定实验或一个新的 fastest-oracle结果。

## 6. 可立即交执行者的结论

保留原 legal-v3；按已授权计划独立运行13-arm reused-v3，给zero/one-zero已知算法的H4/单target成本。若随后排程Sparse增补，现成15-arm census与shared-material paired campaign都能复用C4源码；优先使用它们的原CLI/reader/真实source+binary绑定。**无必要新增外部Rust harness，无需修改runtime、C4源码、Cargo.lock或原门禁。**

15-arm census补全的是当前已知可执行算法集合中的实际成本，仍不能证明世界上没有更便宜算法。shared-material还需要实际材料目录、bundle与build binding；缺少这些输入时应明确记录缺口，不假造operator authority、真实需求或网络资格。
