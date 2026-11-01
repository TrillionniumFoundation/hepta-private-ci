# HCSN R12：统一金融、再生与内容状态的研究实现

本目录以 R11 的完整 He–Xiong 算子为基础，把内容分布、首达后的二阶段恢复、复位与实际读取决策放进同一有限生成元。训练使用 Torch 矩阵指数，公共控制器使用确定性条件期望，在线候选调用 Rust uniformization；另有同一生成元的 Rust Gillespie 事件执行与跨进程恢复。

**研究结论：有限模型的一致性、内容梯度和原生执行已贯通；本次预注册确认没有证明解析核心相对强普通核心的净增益，也没有通过保守成本准入。** 纯 FP32、连续首达精度、实际内容任务及生产资格仍有明确缺口。

阅读入口：

- [中文主报告](REPORT_ZH.md)：模型、实际结果、设计决策和未闭合项。
- [确认汇总](evidence/SUMMARY.json)：八个独立拟合的 2×2、区间、精确符号翻转与 Holm 校正。
- [原始协议](PROTOCOL.json)、[实施细节](IMPLEMENTATION.json)、[确认前冻结](evidence/FREEZE.json)。
- [完整数值检查](numerics/NUMERICS_ZH.md)、[实际梯度与网格检查](verification/VERIFICATION_ZH.md)。
- [原生实现与成本](native/NATIVE_ZH.md)、[理论适用范围](theory/PROPOSITIONS.md)。
- [机制行动检查](mechanisms/REPORT.md)、[独立复核](review/REVIEW_ZH.md)。
- [确认后数值并列动作修复候选](tie_resolution/REPORT_ZH.md)：与原冻结结果严格区分。

## 固定来源

- 基线：`b426b83eb5fd27487c8dba3f90fe9af0dff615e1`。
- 协议先行提交：`2f9104e5f0fc2802b093d04aeb42ea4bece21de7`。
- 源码与全部 24 份拟合参数先于确认提交：`7d2ca44c315d2a05790d0520c70b70f5e10bba6d`。
- 完整金融代码：`../calibrated_operator_r11_20261031/numerics/kernel.py`，原件未修改。
- 没有修改生产 `NeuronRuntime`、Cargo 依赖或默认执行路径。

## 环境与重现

已执行环境为 Python 3.12.14、NumPy 2.3.5、SciPy 1.17.0、PyTorch 2.10.0+cpu、mpmath 1.3.0、Rust 1.95.0。所有拟合限制一个计算线程。未执行 GPU 或焦耳计费。

在本目录建立 Python 环境并安装 `requirements.txt`。PyTorch 的 CPU wheel 来自 `https://download.pytorch.org/whl/cpu`。原生编译器通过参数显式指定：

```bash
python native/build.py --rustc /path/to/rustc-1.95.0
python control/test_controller.py
python native/test_native.py --output reproduce/native_audit
python native/test_contract.py --fixture development/native_fixture.json --output reproduce/native_contract
```

训练、日志和大型原始数据按归档保存；[归档索引](evidence/ARCHIVE_MANIFEST.json)列出逐文件哈希和精确路径。归档的成员路径均相对于本目录：

```bash
tar -xzf evidence/TRAINING_ARTIFACTS.tar.gz
tar -xzf evidence/OPERATOR_EVIDENCE.tar.gz
tar -xzf evidence/NATIVE_EVIDENCE.tar.gz
tar -xzf evidence/TASK_EVIDENCE.tar.gz
python statistics.py --input evidence/CONFIRMATION.json
```

新的独立运行必须使用新的输出目录；程序拒绝覆盖已有冻结和确认结果：

```bash
python run_fits.py --output reproduce/new_campaign --workers 3
python evaluation.py --folder reproduce/new_campaign
python statistics.py --input reproduce/new_campaign/CONFIRMATION.json
```

`FREEZE.json` 绑定源码、拟合参数与实际动态库。原实验的动态库哈希不会因为本机重新编译而自动获准替换；新的构建与拟合需要自己的冻结。CPU 预算按实际进程时间执行，更新数会随环境变化，不能要求重跑权重逐位相同。

## 文件职责

| 文件／目录 | 职责 |
|---|---|
| `contract.py` | 完整 HX 一阶 AD 桥接、有限生成元、联合内容状态、收益与成本 |
| `models.py` | 15 参数分布核心、GRU、连续对角 SSM |
| `training.py` / `run_fits.py` | 固定 CPU 拟合、验证选择、确认前冻结 |
| `data.py` | 因果观测、配对世界、实际 READ 访问 |
| `control/` | 公共有限时域 DP、独立策略枚举与边缘化检查 |
| `inference.py` / `native/` | 真实 Rust 传播、观察、事件与恢复 |
| `evaluation.py` / `statistics.py` | 冻结后 2×2、普通参照、模型相同的 HMM 参照、验收 |
| `verification/` | 端到端梯度、不可识别方向、连续误差和动作反例 |
| `numerics/` | 不修改原门槛的 FP32 修复候选与完整失败记录 |
| `mechanisms/` | 相关性、恢复、金融干预和边缘化的实际动作检验 |
| `review/` / `tie_resolution/` | 独立复核与确认后的数值修复候选 |

归档不包含重新编译即可得到的可执行文件；保留其哈希、编译回执及历史精确源快照。原始失败、旧组合与新冻结组合分别保存，不借用彼此的通过结论。
