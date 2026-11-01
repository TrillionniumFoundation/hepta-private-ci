# R16 证据恢复与复现

本目录包含几个分别冻结的研究 profile。请先恢复并核验已发表证据，再按需要重跑。使用相同 seeds 的重跑是复现，不能增加独立样本数；改变任务、候选、门槛或数据后的新确认需要新的协议与发布冻结。

七类研究状态见 [BLOCKERS_ZH.md](BLOCKERS_ZH.md)。本轮主 D−B、压缩相对 full D 的成本门、value/risk 独立收益门和 pure-Q24 严格持续精度仍未通过；有限子任务通过不改变这些结果。

## 1. 冻结身份

| 范围 | 正式运行前发布并读回的源提交 | 第二次模型/选择冻结 |
| --- | --- | --- |
| R15 继承基线 | `74144a3f5d5c77c953ecdc4708d3d90b56b67d3c` | 继承原冻结，不重选 |
| R16 主任务与支持压缩 | `416a8a47199c129b788875da06d965a52b8fab45` | `SOURCE_FREEZE.json` 绑定原模型 |
| 可达同边缘四族见证 | `d51f323303e83e4220e02cd5565be157db7dc680` | 全部注册族均保留 |
| 合成内容绑定 | `578a2cd37299cb5b299a8a1a4a7eca7c50a77b56` | `038b848df088654323dbbd190d96f79fdace662c` |
| 有限控制与 RESET | `d21b34ac9cfdc517a72e8c54c7fe69fcf9e8c651` | `d4eb4cab43780fad915313494976b4ea3b61b99f` |
| 实际 value/risk 特征成本 | `df19a18ae4984bcc3a23e0bfe1f7f048ce905fa5` | 逐字复用 R15 八份训练源及权重 |
| fast 支持投影 | `4a74cc79584da5302aa8d0bfcd7d01aa66ba0cd7` | 同原 R16 主模型 |
| 固定边界 PDE 与 native Q24 | `4c51e9a068a887fcf80573628e7692a1f84f9c18` | 整数 fixture 在每次验证中保留 |
| Q24＋80 位区间重放 | `44443bbdc2b6e6695bdca2ec728e923c7cdbea22` | 继承上述 native 源码 |

应使用包含全部交付文件的 `research/hcsn-reachable-state-r16-20261101` 分支交付提交。单独 checkout 某一早期源提交可能尚未包含后续结果或其他专项。传入一个格式正确的 SHA 不足以证明远端发布；上述真实发布和读回由原运行流程执行，数值源前后核验另存于 [HYBRID_QUALIFICATION_PUBLICATION.json](numerics/HYBRID_QUALIFICATION_PUBLICATION.json)。

主 `run_01/` 的 128 个原始 gzip 已作为 Git blob 直接提交于 `dd9eaf8d1d10de0261514655343dc476e901cfb3`。其余大型原始证据按以下索引分片保存，不重复发布原始 gzip。

## 2. 环境与新输出位置

从仓库根执行。记录环境为 Python `3.12.14`、NumPy `2.3.5`、SciPy `1.17.0`，另需 `threadpoolctl`。native 编译使用 Rust `1.95.0`、edition 2024。没有 torch 依赖。不同 BLAS/编译器/机器的计时不应被要求逐字相同，也不能直接视为同主机速度比较。

```bash
set -euo pipefail
R16_REPO_ROOT="$PWD"
R16="tools/hcsn/reachable_state_r16_20261101"
R16_REPRO="$R16_REPO_ROOT/r16_reproduction_01"
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
mkdir "$R16_REPRO"
python3 -c 'import sys, numpy, scipy, threadpoolctl; print(sys.version); print(numpy.__version__, scipy.__version__, threadpoolctl.__version__)'
```

`R16_REPRO` 必须是新的输出目录。所有下面的重算输出都放入其中，不覆盖冻结源码、原始证据、已发布汇总或旧失败记录。需要 native 验证时，用实际 Rust 编译器的绝对路径设置：

```bash
R16_RUSTC="$(command -v rustc)"
"$R16_RUSTC" --version
```

若编译器不在 PATH，将 `R16_RUSTC` 设置为可用 `rustc` 的完整路径。`validate_hybrid` 的默认路径是原环境路径，跨机器复现应显式传 `--rustc`。

## 3. 恢复公开原始证据

### 3.1 内容、控制、channel 与 fast

| Bundle | 恢复的原始 gzip 数 | 分片数 | 压缩档案字节数 |
| --- | ---: | ---: | ---: |
| `content/raw_evidence/` | 24 | 3 | 1,072,266 |
| `control/raw_evidence/` | 16 | 3 | 1,340,739 |
| `channel/raw_evidence/` | 128 | 22 | 10,513,859 |
| `fast_raw_evidence/` | 64 | 17 | 7,780,976 |

每个目录的 `INDEX.json` 保存分片顺序、每片/整包 SHA-256、原路径、原大小与原文件 SHA-256。分片上限为 480,000 字节。恢复程序依次检查这些内容，逐字写回仓库内原路径；遇到内容不同的既有文件会拒绝覆盖。

```bash
for R16_BUNDLE in content/raw_evidence control/raw_evidence channel/raw_evidence fast_raw_evidence; do
  python3 -m tools.hcsn.reachable_state_r16_20261101.archive_evidence restore \
    --bundle "$R16/$R16_BUNDLE" \
    --destination "$R16_REPO_ROOT"
done
```

主 `run_01` 原始数据已经直接存在，不需再次从 bundle 恢复。control 的八份 `run_01/training/*.json.gz` 属于已冻结选择证据，直接发布；上面的 control bundle 只保存 `run_01/confirmation/`。

### 3.2 Hybrid 完整执行和恢复证据

每个 hybrid profile 的最小发布集合由自己的 `PUBLICATION_FILES.json` 决定。两个正式 profile 各有六个文件：`HYBRID_VALIDATION.json`、`EVIDENCE_INDEX.json`、发布清单及三片 `EVIDENCE.tar.gz.partNNN`。这些片保留 full/prefix/resumed、所有 native 调用、公开 tape、模型、参考、拒绝路径和进程收据的原始字节。

| 正式 profile | 索引中的原文件数 | 原文件字节数 | 档案字节数 |
| --- | ---: | ---: | ---: |
| `hybrid_qualification_163211` | 257 | 6,468,595 | 1,306,870 |
| `hybrid_qualification_163213` | 247 | 6,387,032 | 1,268,297 |

Hybrid 的索引格式与一般 raw bundle 不同，不要把它传给 `archive_evidence.py`。以下代码对所有已发布 hybrid 索引按顺序核验分片、整包和原文件，再恢复到各自原目录；仅恢复普通文件，并拒绝路径越界和不同内容覆盖。

```bash
python3 - <<'PY'
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

root = Path('tools/hcsn/reachable_state_r16_20261101/numerics/results')
digest = lambda data: hashlib.sha256(data).hexdigest()
for profile in sorted(root.glob('hybrid_*')):
    index_path = profile / 'EVIDENCE_INDEX.json'
    if not index_path.is_file():
        continue
    index = json.loads(index_path.read_text())
    chunks = []
    for part in index['parts']:
        assert Path(part['path']).name == part['path']
        data = (profile / part['path']).read_bytes()
        assert len(data) == part['bytes'] and digest(data) == part['sha256']
        chunks.append(data)
    packed = b''.join(chunks)
    assert len(packed) == index['archive_bytes']
    assert digest(packed) == index['archive_sha256']
    expected = {row['path']: row for row in index['files']}
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(packed)), mode='r:') as archive:
        for member in archive.getmembers():
            assert member.isfile() and member.name in expected and member.name not in seen
            target = (profile / member.name).resolve()
            assert target.is_relative_to(profile.resolve())
            data = archive.extractfile(member).read()
            row = expected[member.name]
            assert len(data) == row['bytes'] and digest(data) == row['sha256']
            if target.exists():
                assert target.read_bytes() == data, f'Different existing evidence: {target}'
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            seen.add(member.name)
    assert seen == set(expected)
    print(profile.name, len(seen), 'files verified and restored')
PY
```

纯 Q24 的其余证据直接发布。`fresh_161102719/733` 若出现在旧快照，是 `development_161102719/733` 的重复副本，不是第二次运行；见 [DUPLICATE_DEVELOPMENT_PATHS.json](numerics/DUPLICATE_DEVELOPMENT_PATHS.json)。

## 4. 核验当前源码与继承模型

下面只读取 manifest。主、fast、channel 的清单都同时包含依赖/模型哈希；native/hybrid 为文件列表。内容和控制的确认入口还会核验各自源码及模型/选择清单。

```bash
python3 - <<'PY'
import hashlib
import json
from pathlib import Path

root = Path.cwd()
r16 = root / 'tools/hcsn/reachable_state_r16_20261101'
for name in ('SOURCE_FREEZE.json', 'FAST_SOURCE_FREEZE.json',
             'channel/SOURCE_FREEZE.json', 'numerics/PUBLISH_MANIFEST.json',
             'numerics/HYBRID_PUBLISH_MANIFEST.json'):
    entries = json.loads((r16 / name).read_text())['files']
    pairs = entries.items() if isinstance(entries, dict) else (
        (entry['path'], entry['sha256']) for entry in entries)
    count = 0
    for relative, expected in pairs:
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected, relative
        count += 1
    print(name, count, 'hashes matched')
for base, name, key in (
    ('content', 'run_train_01/FROZEN_MODELS.json', 'source_hashes'),
    ('control', 'run_01/TRAINING.json', 'source_sha256')):
    manifest = json.loads((r16 / base / name).read_text())
    for relative, expected in manifest[key].items():
        assert hashlib.sha256((r16 / base / relative).read_bytes()).hexdigest() == expected, relative
    print(base, 'source hashes matched')
PY
```

Hybrid 原正式运行在入口外另核验了全部 13 个源/协议文件，运行前后都匹配。其冻结入口本身只核对 native manifest 和 hybrid 提交字符串格式，故应保留这项外层检查，不把它误写成入口自动提供了全部发布验证。

## 5. 先重算统计与有限合同

以下命令不生成新的主确认世界，输出位置均为新目录。

```bash
python3 -m tools.hcsn.reachable_state_r16_20261101.statistics \
  --run "$R16/run_01" --output "$R16_REPRO/MAIN_SUMMARY.json"
python3 -m tools.hcsn.reachable_state_r16_20261101.channel.statistics \
  --input "$R16/channel/run_confirm_01" --output "$R16_REPRO/CHANNEL_SUMMARY.json"
python3 -m tools.hcsn.reachable_state_r16_20261101.reachable \
  --output "$R16_REPRO/REACHABLE.json"
python3 -m tools.hcsn.reachable_state_r16_20261101.compression_checks \
  --output "$R16_REPRO/COMPRESSION_CHECKS.json"
python3 -m unittest tools.hcsn.reachable_state_r16_20261101.content.test_contract
python3 -m tools.hcsn.reachable_state_r16_20261101.numerics.test_interval_replay
```

`compression_checks` 同时在其新输出目录保存 trace。主统计以 8 个拟合为独立单位；不是把 6,144 个任务查询当独立拟合。内容/控制/channel/fast 的独立单位同样按各自协议固定。可达见证必须保留全部四族，包括没有严格最优答案差的 `free_drift`。

主算子可识别性可以只读调用，避免覆盖已发表文件：

```bash
python3 - <<'PY'
import json
from tools.hcsn.reachable_state_r16_20261101.identifiability import run
result = run()
print(json.dumps({key: value for key, value in result.items() if key != 'operators'}, indent=2))
PY
```

应复得 6/8 精确算子等价、仅 2 个潜在非零差、双侧符号翻转 p 的下界 `0.5`。不要通过删除同 Q 普通模型改变这项判断。

### 独立 raw 审计入口

下面重读原证据并另存新审计结果；不重新执行正式世界，也不覆盖原审计收据。主/channel 审计独立重建分数、观察与统计，范围不包括重新求解每个规划动作。

```bash
python3 -m tools.hcsn.reachable_state_r16_20261101.audits.independent_main_audit \
  --run "$R16/run_01" --summary "$R16/results/CONFIRMATION_SUMMARY.json" \
  --output "$R16_REPRO/INDEPENDENT_MAIN_AUDIT.json"
python3 -m tools.hcsn.reachable_state_r16_20261101.channel.independent_audit \
  --run "$R16/channel/run_confirm_01" --summary "$R16/channel/run_confirm_01/SUMMARY.json" \
  --output "$R16_REPRO/INDEPENDENT_CHANNEL_AUDIT.json"
python3 - <<'PY' > "$R16_REPRO/INDEPENDENT_FAST_AUDIT.json"
import json
from tools.hcsn.reachable_state_r16_20261101.audit_fast_independent import run
print(json.dumps(run(), indent=2, sort_keys=True, allow_nan=False))
PY
python3 - <<'PY' > "$R16_REPRO/INDEPENDENT_HYBRID_AUDIT.json"
import json
from tools.hcsn.reachable_state_r16_20261101.numerics.audit_hybrid_independent import fraction_cases, raw_audit
result = dict(exact_fraction_checks=fraction_cases(),
              formal_saved_evidence=[raw_audit(seed) for seed in (163211, 163213)])
print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
PY
```

Hybrid 入口同时使用独立小型 Fraction fixture 与保存的正式轨迹/缓存；不会重新生成正式 seeds，也不会把这些小 fixture 计作任务确认。原内容独立审计结果和其逐档哈希见 [INDEPENDENT_CONFIRMATION_AUDIT.json](content/INDEPENDENT_CONFIRMATION_AUDIT.json)，内容生成/预测可按下一节的冻结模型命令完整复现。

## 6. 完整重复原确认

### 主 2×2 与压缩

```bash
python3 -m tools.hcsn.reachable_state_r16_20261101.supervise \
  --freeze-commit 416a8a47199c129b788875da06d965a52b8fab45 \
  --output "$R16_REPRO/main"
python3 -m tools.hcsn.reachable_state_r16_20261101.statistics \
  --run "$R16_REPRO/main" --output "$R16_REPRO/main/SUMMARY.json"
```

该 runner 原样执行 namespace 16，8 fits × 两域 × 64 世界 × 9 臂。保留 16 个完整子进程收据、128 个 raw shard 和失败路径；任何失败不得生成只含成功世界的科学对比。

### 内容：复用已发布模型

```bash
python3 -m tools.hcsn.reachable_state_r16_20261101.content.campaign confirm \
  --source-commit 578a2cd37299cb5b299a8a1a4a7eca7c50a77b56 \
  --model-commit 038b848df088654323dbbd190d96f79fdace662c \
  --frozen "$R16/content/run_train_01/FROZEN_MODELS.json" \
  --output "$R16_REPRO/content_confirm"
```

这将重跑原 3,072 个 episode。要检查拟合过程，可另用 `content.campaign train --source-commit <上述内容源提交> --output <新的训练目录>`。重新训练所得文件含新计时，文件哈希会改变；不能给新文件套用旧模型发布 SHA。新的科研确认仍需先发布新模型清单。原已发布确认的三个准确率下界门只适用于合成绑定，不能解释为 HX 优势或开放域语义能力。

### 有限控制与 reset

```bash
python3 -m tools.hcsn.reachable_state_r16_20261101.control.campaign confirm \
  --training "$R16/control/run_01/TRAINING.json" \
  --receipt "$R16/control/run_01/PUBLICATION.json" \
  --output "$R16_REPRO/control/CONFIRMATION.json"
```

训练清单引用的是 `control/run_01/training/*.json.gz`；确认读取原选择，并在新输出父目录写新的 `confirmation/`。每 fit/域 256 个基础 episode、7 臂，共 4,096 个基础 episode。需要重做有限候选搜索时，遵循 [control/README.md](control/README.md) 的 train →真实选择发布→freeze→confirm 顺序。所有候选成本和落选结果都必须保留。

### Channel 的真实特征成本

```bash
for R16_SEED in 151101 151103 151107 151109 151113 151117 151119 151123; do
  for R16_DOMAIN in iid ood; do
    python3 -m tools.hcsn.reachable_state_r16_20261101.channel.campaign confirm \
      --source-commit df19a18ae4984bcc3a23e0bfe1f7f048ce905fa5 \
      --seed "$R16_SEED" --domain "$R16_DOMAIN" \
      --output "$R16_REPRO/channel/${R16_SEED}_${R16_DOMAIN}"
  done
done
python3 -m tools.hcsn.reachable_state_r16_20261101.channel.statistics \
  --input "$R16_REPRO/channel" --output "$R16_REPRO/channel/SUMMARY.json"
```

这些是原 namespace 17 的 1,024 个共享世界。四臂应继续复用旧 weights，各自只计算实际需要的特征；首次风险 augmented expm 不可从计时中删除。若另做完整进程计时，另存新收据；源码里的 worker body 计时不包含全部 interpreter/import 开销。

### Fast 同语义实现

```bash
python3 -m tools.hcsn.reachable_state_r16_20261101.fast_checks \
  --output "$R16_REPRO/FAST_ENGINEERING.json"
python3 -m tools.hcsn.reachable_state_r16_20261101.fast_campaign \
  --freeze-commit 4a74cc79584da5302aa8d0bfcd7d01aa66ba0cd7 \
  --output "$R16_REPRO/fast"
```

第一条重放旧状态做工程检查，第二条复现 namespace 18 的 512 世界。旧/新查询比较只忽略 `checkpoint_sha256`；belief 容差固定 `2e-11`。不得因新实现更快而改掉其仍慢于 full D 的原成本结论。原始确认 CPU 比是某主机测量，另机重跑不要求完全复得计时比。

### PDE、pure-Q24 与 hybrid

```bash
python3 -m tools.hcsn.reachable_state_r16_20261101.numerics.pde_convergence \
  --output "$R16_REPRO/PDE_CONVERGENCE.json"
for R16_SEED in 163201 163203; do
  python3 -m tools.hcsn.reachable_state_r16_20261101.numerics.validate_q24 \
    --rustc "$R16_RUSTC" --seed "$R16_SEED" \
    --output "$R16_REPRO/q24_${R16_SEED}"
done
for R16_SEED in 163211 163213; do
  python3 -m tools.hcsn.reachable_state_r16_20261101.numerics.validate_hybrid \
    --rustc "$R16_RUSTC" --seed "$R16_SEED" \
    --source-commit 44443bbdc2b6e6695bdca2ec728e923c7cdbea22 \
    --output "$R16_REPRO/hybrid_${R16_SEED}"
done
```

pure-Q24 `Q24_VALIDATION.json.passed` 是算术、支持、诊断精度与恢复检查的组合；它包含“严格合同必须正确拒绝”的检查。这个布尔值不是“原 1% 门槛完成全部事件”。必须另外读取 `strict_guard`：原正式 seeds 分别完成 22/33 条后拒绝。

Hybrid 使用同一原门槛，通过显式且付费的高精度重放完成全部 549 条。重放事件数是 549，不是回退次数 20/19。验证包含另进程 prefix/resume、损坏 cache、不同 tape 和既有输出目录拒绝；外层进程 CPU 已含其等待的 native 后代。checkpoint/hash 不提供授权、防回滚或完整生产 owner 的恢复证明。

## 7. 结果与成本验收

| 正式 profile | 应读取的门与原结果 |
| --- | --- |
| 主确认 | `results/CONFIRMATION_SUMMARY.json.primary_passes = false`；所有压缩成本门 false；同 Q 等价 1,024 世界 |
| 内容 | 三域 `domain_gates = true`；合成绑定限定范围 |
| 有限控制 | 四个主要有限收益门 true；ordinary_same_q_dp 全轨迹等价；连续最优性 false |
| Channel | 四个 Holm 检验的收益门均 false |
| Fast | 旧/新等价与质量门通过，相对 old 工程速度通过，相对 full 成本收益 false |
| Pure-Q24 | 有限算术/恢复检查通过，原严格持续精度拒绝保留 |
| Hybrid | 两个正式有限 tape、原精度门及受信恢复通过；生产总门 false |

成本复核以 [RESEARCH_COST_LEDGER.json](results/RESEARCH_COST_LEDGER.json) 为入口。每条列出来源、字段或计算式、记录范围及不可相加的嵌套分项；源回执另有 SHA-256。原正式主 child `403.835366 s`、内容 train+confirm child `27.484839 s`、channel worker child `44.974841 s`、fast child `64.113695 s` 都已包含各自函数体，不能再叠加。有限控制仅有 `0.738031771 + 2.299238360 s` 函数体下界。数值 `45.838639815 s` 汇总包括开发、失败与正式验证，正式 hybrid 的 full 单次执行成本是其中部分。

总账另计有收据的独立审计和开发工作；当前记录并不包含所有工作。人工、工具后台、未计时命令、部分打包/上传、网络和硬件能耗保持未测。R15 八个旧拟合函数 `25.714870610 s` 单列为历史异机成本，其 learned/calibration/selection 计时是内部组成项，不再重复相加。合成动作费也不能当 CPU、能耗或生产费用。

当前环境的只读计量可用性检查见 [RUNTIME_MEASUREMENT_AVAILABILITY.json](results/RUNTIME_MEASUREMENT_AVAILABILITY.json)：未暴露 powercap 能量文件，`nvidia-smi` 不可用；它没有产生焦耳数或网络服务性能测量。
