# 复现入口

先从已固定 v8 来源恢复历史 v3。当前恢复器接受原包所记录的只读 checkout 路径，并核对全部期望源/成员哈希；它不会替换已存在但不同的目标文件：

```bash
python3 experiments/hcsn_v10_closure_20261101/frontend/recover_historical.py --source /path/to/verified/source-checkout --repository /path/to/this-repository --receipt /tmp/historical-recovery.json
```

新 Library 包应独立保存并提取；不要覆盖本仓已有另一条 `hcsn_v9_followup_20261101`。包内 v9 的 `persistent_av/results002/async_av/INPUTS.json` 是下面 `--v9-evidence` 的数据身份依据。固定包/远端身份见 `RECOVERED_PACKAGE.json`。

三个阶段使用同一新输出目录，依序执行。每条应由上层 `economics/stage_meter.py` 的实际支持接口独立包裹；命令只给出被计量的 worker，不把内部时间再加到外层：

```bash
PYTHONPATH=/tmp/hcsn-torch-runtime "$CODEX_PRIMARY_RUNTIME_PYTHON" -m experiments.hcsn_v10_closure_20261101.frontend.historical_audio_reference --stage prepare --output /tmp/new-audio-results --v9-evidence /path/to/extracted/experiments/hcsn_v9_followup_20261101
PYTHONPATH=/tmp/hcsn-torch-runtime "$CODEX_PRIMARY_RUNTIME_PYTHON" -m experiments.hcsn_v10_closure_20261101.frontend.historical_audio_reference --stage train --output /tmp/new-audio-results --v9-evidence /path/to/extracted/experiments/hcsn_v9_followup_20261101
PYTHONPATH=/tmp/hcsn-torch-runtime "$CODEX_PRIMARY_RUNTIME_PYTHON" -m experiments.hcsn_v10_closure_20261101.frontend.historical_audio_reference --stage evaluate --output /tmp/new-audio-results --v9-evidence /path/to/extracted/experiments/hcsn_v9_followup_20261101
PYTHONPATH=/tmp/hcsn-torch-runtime "$CODEX_PRIMARY_RUNTIME_PYTHON" -m experiments.hcsn_v10_closure_20261101.frontend.audit_audio_reference --output /tmp/new-audio-results
```

本次解释器已有 Torch 2.15.0+cpu；只读路径 `/tmp/hcsn-torch-runtime` 属于本执行环境。其他环境须提供相同依赖，不能把该路径当成已包含的模型资产。所有输入、演员和标签都是旧开发材料。
