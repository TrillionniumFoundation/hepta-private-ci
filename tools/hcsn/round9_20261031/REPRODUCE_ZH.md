# R9 五项验收的复现入口

从本次交付提交的完整 checkout 根目录运行并记录 `git rev-parse HEAD`。已有结果的核验、原种子重放、重新计时和从源码重新构建是不同工作；重放不会产生新的独立确认样本。所有新输出使用新目录，原冻结文件和失败记录保留。

## 1. 环境与旧权重恢复

| 执行部分 | 本次最终证据中的环境 |
| --- | --- |
| value、dynamics | Python 3.12.14、NumPy 2.3.5、SciPy 1.17.0，单线程 BLAS |
| streaming | 同上，另需 CPU PyTorch 2.8.0+cpu；`--checks-only` 仍会执行原 Torch benchmark |
| native 历史构建 | Rust 1.96.0、LLVM 22.1.2，`x86_64-unknown-linux-gnu` |

用正常渠道准备依赖；下面 `HCSN_PY` 必须能导入 NumPy/SciPy，`HCSN_TORCH_PY` 要替换成实际 CPU PyTorch 环境的解释器路径。共享主机的耗时不保证逐字节复现；没有实测能耗，`energy_joules=null`。

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
HCSN_PY="$(command -v python3)"
HCSN_R9_RUN="$(mktemp -d /tmp/hepta-r9-replay.XXXXXX)"
python3 tools/hcsn/round8_20261031/bundles.py verify value_calibration
python3 tools/hcsn/round8_20261031/bundles.py restore value_calibration
python3 tools/hcsn/round8_20261031/bundles.py verify state_task
python3 tools/hcsn/round8_20261031/bundles.py restore state_task
```

R8 的旧 heads/训练回执在分卷中；`verify/restore` 核验分卷、整包和成员 SHA-256，拒绝覆盖不同字节。稀疏 checkout 还须物化 `bundles.py`、对应 `bundles/*.json`、全部 `.tar.gz.part*`、源码和登记的 round7 `fits_primary` checkpoints。R9 原代码、15 个新 heads、冻结记录已作为普通文件交付；重放无需重新训练。

## 2. value：精确登记树、确认与审计

原实验登记的是局部源码树：round7 顶层只有 `task.py` 和 `oracle.py`。其未改动的 `sources()` 会枚举顶层 Python 文件，所以直接在完整 checkout 调用 `value.run confirm` 会因额外源码而被拒绝。这是实验的路径假设，不是新的科学门槛。

`integration/reproduce_value.py` 按原 `AMENDMENT.sources`、`REGISTERED` 和冻结清单建立独立最小树，核验所有复制文件的 SHA-256，保留历史训练成本回执，加载 15 个新 heads 和 15 个旧 heads。`--output` 必须不存在且在源码 checkout 外；解释器路径不解析掉虚拟环境的启动符号链接。

```bash
# 只准备并实际执行原 verify_registration 和 30 个 heads 的完整性检查。
"$HCSN_PY" tools/hcsn/round9_20261031/integration/reproduce_value.py \
  --python "$HCSN_PY" --output "$HCSN_R9_RUN/value-prepare" --prepare-only
# 完整重放：在另一个新目录执行确认，再执行全部原始记录的审计。
"$HCSN_PY" tools/hcsn/round9_20261031/integration/reproduce_value.py \
  --python "$HCSN_PY" --output "$HCSN_R9_RUN/value"
```

输出分别在新树的 `confirmation/`、`audit/`、`reproduction-logs/`，总回执是 `REPRODUCTION_RESULT.json`。审计原模块没有输出 CLI；helper 显式配置其输出目录后调用原 `run()`。它不覆盖交付的 `value/evidence/confirmation02` 或 `value/audit`。入口的 `passed` 表示重放/完整性成功，不能解释为科学验收全部通过。

`integration/VALUE_REPRODUCER_CHECK.json` 记录本次实际执行的准备检查：66 个文件、原登记校验及 30 个 heads 加载通过；未额外重跑 76,800 个配对比较。主科学结果仍以 `value/evidence/confirmation02/RESULTS.json` 为准，早期失败记录不是最终结果。

## 3. 连续事件：保留 576 格失败和 1152 格扩展

```bash
"$HCSN_PY" -m unittest tools.hcsn.round8_20261031.event_dynamics.test_event_dynamics tools.hcsn.round9_20261031.dynamics.test_dynamics_repair -q
"$HCSN_PY" -m tools.hcsn.round9_20261031.dynamics.audit --output "$HCSN_R9_RUN/repair.json"
"$HCSN_PY" -m tools.hcsn.round9_20261031.dynamics.recovery_scale --output "$HCSN_R9_RUN/recovery.json"
"$HCSN_PY" -m tools.hcsn.round9_20261031.dynamics.clock_scaling --output "$HCSN_R9_RUN/clock.json"
"$HCSN_PY" -m tools.hcsn.round8_20261031.event_dynamics.resolution_audit --output "$HCSN_R9_RUN/spatial.json"
"$HCSN_PY" -m tools.hcsn.round8_20261031.event_dynamics.renewal_resolution --output "$HCSN_R9_RUN/renewal.json"
```

最后一条**预期退出码 1**，必须同时检查有效 JSON 的 `passed=false` 和具体失败门：原 upwind 576 格最大误差约 `0.00531114 > 0.005`。程序崩溃、缺依赖或没有有效结果不能算预期失败。不要用 `&&` 把后续扩展依赖于上一条成功退出，也不要用无条件忽略错误替代核验。

```bash
"$HCSN_PY" -m tools.hcsn.round8_20261031.event_dynamics.renewal_resolution_extension \
  --baseline "$HCSN_R9_RUN/renewal.json" --output "$HCSN_R9_RUN/extension.json"
```

扩展引用原失败结果的摘要，在原门槛下增加 upwind 1152 格；其约 `0.00266434` 的最大误差通过。这个固定模型结果不关闭低噪 CTMC 的已记录拒绝，也不证明非正漂移、一般移动边界或任意耦合过程。

## 4. streaming：实际在线状态与同 NumPy 成本

```bash
HCSN_TORCH_PY=/absolute/path/to/cpu-torch-environment/bin/python
"$HCSN_PY" tools/hcsn/round9_20261031/streaming/reproduce.py \
  --python "$HCSN_TORCH_PY" --output-repo "$HCSN_R9_RUN/streaming"
```

`--output-repo` 必须不存在。入口校验并复制冻结 R8 inputs、heads、历史训练回执以及 R9 源码，顺序运行原 `audit`、`startup`、`numpy_comparison`；它不复制原 streaming 结果。新结果位于新树 `tools/hcsn/round9_20261031/streaming/evidence/v2`。仅需质量/恢复审计时可加 `--checks-only`，但仍须 PyTorch。普通两累积量 exact control 同样通过，不能把通用传播/批处理改进归为解析状态独占收益。

## 5. native：历史二进制重放与源码重建分开

`integration/NATIVE_REBUILD_STATUS.json` 实查发现历史清单的 86 个依赖产物中 84 个已缺失，所以本机当前不能重跑 `build_cached.py`。历史成功构建、11 个测试及其二进制仍保留；`integration/native_executables.tar.gz` 包含 Linux x86_64 GNU-target owner 和测试程序，不是跨平台发行包。

先校验 archive 和成员摘要，再写入一个新目录：

```bash
python3 - "$HCSN_R9_RUN/native-bin" <<'PY'
import hashlib, json, sys, tarfile
from pathlib import Path
base = Path('tools/hcsn/round9_20261031/integration')
meta = json.loads((base / 'NATIVE_EXECUTABLES.json').read_text())
archive = base / meta['archive']
assert hashlib.sha256(archive.read_bytes()).hexdigest() == meta['archive_sha256']
out = Path(sys.argv[1]); out.mkdir(exist_ok=False)
with tarfile.open(archive) as bundle:
    assert set(bundle.getnames()) == set(meta['members'])
    for name, expected in meta['members'].items():
        assert Path(name).name == name
        data = bundle.extractfile(name).read()
        assert hashlib.sha256(data).hexdigest() == expected['sha256']
        target = out / name; target.write_bytes(data); target.chmod(0o755)
PY
```

内容输入包括冻结 `task_value_factorial_20261030/task.py`、`third/memory/reference.py`、`third/memory/checkpoints/memory_full_mass_seed29.npz` 和 `next/full_kernel/baseline_table.npz`。这些文件已核对存在于交付父 `00b94d54a9b85f285298d1a964777bdecfa85385` 的普通 tree，完整 checkout 不需要额外归档；稀疏 checkout 须先物化。`prepare_content.py` 强制核验两份 NPZ 的 SHA-256。

```bash
HCSN_CONTENT_SOURCE="$PWD/tools/hcsn"
"$HCSN_PY" tools/hcsn/round9_20261031/native/prepare_content.py --hcsn-source "$HCSN_CONTENT_SOURCE" --output "$HCSN_R9_RUN/weights.json"
"$HCSN_PY" tools/hcsn/round9_20261031/native/qualify.py --binary "$HCSN_R9_RUN/native-bin/native-owner-r9" --weights "$HCSN_R9_RUN/weights.json" --hcsn-source "$HCSN_CONTENT_SOURCE" --out "$HCSN_R9_RUN/native-qualification"
"$HCSN_PY" tools/hcsn/round9_20261031/native/port_checks.py --binary "$HCSN_R9_RUN/native-bin/native-owner-r9" --weights "$HCSN_R9_RUN/weights.json" --hcsn-source "$HCSN_CONTENT_SOURCE" --out "$HCSN_R9_RUN/native-port-checks"
```

从空缓存重建依赖请用父 [R8 复现说明](../round8_20261031/REPRODUCE_ZH.md) 第 5 节的 `native_owner/bootstrap.py --source-root <pinned-main> --existing-build <new-inputs> --cargo-cache <genuine-cache>`。上游固定为 `732e934ba496d90fbe042b8d41d479ef901643e5`、Rust 1.96.0；`--existing-build` 名称沿用旧接口，但目录必须尚不存在。随后按该文档执行正常的 `cargo fetch --locked`、R8 build，重新登记依赖身份，再编译和测试 R9。**这个完整 clean Cargo → R9 构建链本轮没有验证**；R8 bootstrap 不是 R9 新二进制的构建证书。

## 6. 不执行实验的最小只读核验

```bash
python3 - <<'PY'
import json
from pathlib import Path
root = Path('tools/hcsn/round9_20261031')
acceptance = json.loads((root / 'integration/ACCEPTANCE.json').read_text())
print('overall:', acceptance['overall_status'])
for priority in acceptance['priorities']:
    print(priority['id'], priority['overall_status'], priority['summary'])
PY
```

精确数值、对应 JSON Pointer 和源文件摘要均在 `integration/ACCEPTANCE.json`。最小原证据入口是 `value/evidence/confirmation02/RESULTS.json`、`value/diagnostics/RESULTS.json`、`dynamics/evidence/final_repair.json`、`streaming/evidence/v2/results.json`、`streaming/evidence/v2/numpy_comparison.json` 和 `native/evidence/qualification-final/REPORT.json`。验收仍区分 support、contradicted、open；重放不改变原门槛或扩大适用域。
