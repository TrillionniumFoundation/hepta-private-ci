# R16 编译型金融算子：恢复后的独立验证与完整成本

本目录保存恢复后的 C++ 候选、新协议、新独立样本、全部原始数值、独立检查器和新的 CPU 计时。**新独立集上，FP64 与显式双字 FP32 各通过 768/768 行、128/128 参数点；普通单字 FP32 仅通过 155/768 行、0/128 完整参数点。** 双字 FP32 仍需要显著更多计算：同一 C++ 模板和同一自动微分实现下，完整金融评估中位成本是 FP64 的 **22.6962 倍**。

这里通过的是有限 CPU 数值协议。它不授予普通 FP32、GPU、能耗、全模态任务、网络训练或相对 Transformer 的优势结论。

## 证据身份与此前数据丢失

- 已安全持久化的 Python R16：`1e91c5cf18272505508b9ce880fd34879bb6a546`，其原始 512 行独立验证和约 93.65 倍 Python 成本仍保留，结论不被本目录覆盖。
- 恢复源码 checkpoint：`4e97fd84fa1d78e96a96b408b0698f40f362ce88`。
- 在任何新候选/参考计算前发布的新协议 checkpoint：`086baf3ee2ca51c20ac732d069d46b39fc37b918`。
- 新协议 SHA256：`76480c80df71700c7a39906936521e5542ddc9c788282ea3a165dffafa7dc1f0`。
- 新输入 manifest SHA256：`517ce163008c82ff1eab432a5b0e6e59e5b7aebfa28fc8b6184c449d1f5010b5`。
- 恢复可执行库 SHA256：`a96fbe8ee36be2fdaa2a5894462f415f9724acf199ae31745c471092c26f6615`，与重置前最后记录的可执行库逐字节一致。

共享执行环境重置前，旧 C++ 的 768 行完整原始验证、原始分支观测和 36 个计时批尚未上传，已经丢失。不能把旧汇总或哈希当作可重新审查的原始证据，也不继承旧独立准入。`DATA_LOSS_AND_RECOVERY.md` 保留该事实。`HISTORICAL_SMOKE_TOOL_OUTPUT.json` 是少量实际幸存的旧工具输出，只有 9 条初始 smoke 观测，不能补足丢失的数据或原失败 port 的完整源码快照。新 36 批计时是新的测量，未复刻或伪造旧时钟。

## 精度与算子合同

`kernel.cpp` 用一个金融公式模板和固定 10 列前向自动微分，分别实例化 native `double`、native `float`、显式 `Pair{float hi, float lo}`。五个输出依次为边界、equity、F、G、debt；Jacobian 为 5×10，列为九个参数和状态。

`compensated32` 的 primal 和 tangent 都是两个 FP32 字，获得扩展有效尾数，绝不是普通单字 FP32。固定常数准备、独立高精度参考和 double 基线可以使用更高精度。C API 将已经舍入成 FP32 的最终值精确提升成 double 作传输，这不增加金融运算精度。Pair 禁止由运行时 double 参数构造。

Jacobian 是在这些已表示输入处对连续数学公式的导数近似，不是对 FP32 舍入映射逐位求导。log-distance 坐标固定 x，asset 坐标固定 V，并保留边界随参数变化的链式导数。

编译使用 GCC 13.3.0，完整命令、编译器身份和源前后哈希在 `RECOVERED_BUILD.json` 中。禁止 fast-math、重结合、倒数替换和隐式 FMA contraction；要求 `FLT_EVAL_METHOD==0`。`RECOVERY_INSTRUCTION_INVENTORY.json` 对此二进制 35 个具名 Pair/primitive 函数作了静态 inventory，未发现 SD/PD 双精度算术，11 个 float→double 转换位于输出传输。该 inventory 只是支持性证据，不是关于任意编译器或外部数学库内部实现的形式证明。

通用 Pair 仍有范围限制，例如已知 `sqrt(0)` 及大数 Dekker splitter overflow 见证；有限注册金融域的通过不能升级为通用双字数学库证明。F/G/debt 的默认常量扩展不具有全局 C1 性质。代码不据此宣称完整神经元状态动力学已经闭合。

## 新独立验证

`RECOVERY_CASES_V1.json` 使用此前未打开的 PCG64 seed **2026110127**，128 点 jittered Latin hypercube；九个参数先采样，再一次量化到 FP32。每点固定六个状态：log-margin 0、局部 Taylor/blend 区内状态、log-margin 1，以及 MP80 边界上下约 1e-6 和固定资产 100。参数域、有效性规则、状态规则、源/二进制/编译记录哈希、门槛都在计算前冻结。

MP80 oracle 直接计算归档 literal A5/A7 公式；Jacobian 用 `1e-18` 和 `5e-19` 两个相对步长的高精度差分，使用归档的 FP32 输入十进制 round-trip 编码约定。指标逐元素取 `abs(actual-reference)/max(1,abs(reference))`。

| 模式 | 值门槛 | Jacobian 门槛 | 通过行 | 完整参数点 | 最大值误差 | 最大 Jacobian 误差 |
|---|---:|---:|---:|---:|---:|---:|
| FP64 | 2e-8 | 2e-5 | 768/768 | 128/128 | 7.37318e-11 | 2.72874e-7 |
| 普通 FP32 | 8e-7 | 2e-5 | 155/768 | 0/128 | 0.141436 | 613.957 |
| 双字 FP32 | 8e-7 | 2e-5 | 768/768 | 128/128 | 5.66184e-8 | 1.01239e-5 |

全部 128 点满足预先登记的独立域规则，没有删除拒绝点。所有普通 FP32 数值失败行保留。步长减半最大误差为 `1.468842855850744e-34`，原门槛为 `1e-12`。

`recovery_check.py` 在廉价检查后重新计算每一行全部五值与 50 个偏导，逐项与已存 MP80 参考一致，再从原始 candidate/reference 数值重新算误差。它不信任 writer 的汇总。还记录了 **15,360** 个 asset 差分邻点的分支归属，包含 **165** 个资产 default 行。

log-margin=0 的 **128** 行明确采用续行侧右导数：额外三点右侧差分验证该约定。它不是跨 default 拼接的经典双侧导数。asset 方向所有差分邻点必须保持原分支，精确 seam 或无法判定的点会明确失败，不通过删除样本来取得 pass。

独立 reviewer 的预验证 receipt 与故障注入脚本位于 `independent_review/`。本目录另有 12 项 preflight 见证，利用首个参考调用前的 sentinel 验证缺行、错维、NaN、参数/源/参考替换等被拒绝；这些 synthetic 控制的金融数值调用数为零，不能充当数值通过证据。

## 已打开样本回归与原失败见证

`recovery_regression_v1/` 使用安全远端归档的原 432 行开发矩阵及已打开的 Python 512 行参考，属于回归。

| 样本 | FP64 | 普通 FP32 | 双字 FP32 |
|---|---:|---:|---:|
| 原 18×24 开发矩阵 | 432/432，18/18 点 | 164/432，0/18 点 | 432/432，18/18 点 |
| 已打开 Python 512 行 | 512/512，128/128 点 | 74/512，0/128 点 | 512/512，128/128 点 |

原 432 行中有 419 个独特输入、13 个重复输入，并只有 2 个资产 default 行；不能把行数当作独立样本量。新增独立集专门增加了边界和 default 邻域覆盖，但仍然不是整个参数盒上的统一误差证明。

五个原失败输入按 case、坐标和实际 FP32 状态字匹配到开发回归行 66、69、95、192、239；FP64 和双字 FP32 均通过，普通 FP32 均失败，见 `RECOVERY_WITNESS_COVERAGE.json`。原普通 FP32、Python 稳定代数失败尝试及其原始证据仍在安全发布的 Python R16 capsule；本目录不改变其门槛或标签。

## 新的同后端成本

`RECOVERY_CPU_COST_V1.json` 保存全部 **36** 批新 wall/process 原始读数。原 18 参数点×3 状态组成 54 行，一个计时批重复 50 次，共 2,700 行。六个模式/复用条件各先完整 warmup，再用六轮轮换顺序计时；共 16,200 warmup 和 97,200 timed evaluations。所有三模式均计算完整边界、五值和 50 个偏导。失败批会记录且不能进入完整评估成本比。

| 条件 | FP64 中位 µs/状态 | 普通 FP32 中位 µs/状态 | 双字 FP32 中位 µs/状态 | 双字/FP64 |
|---|---:|---:|---:|---:|
| 每状态重新计算边界 | 10.7490 | 8.26642 | 243.962 | 22.6962× |
| 每组三状态复用边界 | 10.1009 | 7.04316 | 215.298 | 21.3148× |

全部批次成功且重复结果确定，复用与不复用的所有值/Jacobian 逐位一致。代价比是此单机 CPU 实现的描述性观测，包括相同 C API/Python 分配开销；没有 GPU、能耗或生产吞吐的推断。普通 FP32 作为数值不合格的诊断基线保留。仍显著较慢的同后端成本是未关闭的问题。

## 最小复现与退出码

下面命令在本目录执行，使用新输出路径；发布的原始证据应保持只读。已安装依赖时，`--oracle-pythonpath .` 足够，因为 mpmath 仍通过正常 Python import path 加载；独立安装到其他目录时传那个目录。

```sh
python -m pip install -r requirements-recovery.txt
python -B recovery_eval.py --protocol RECOVERY_PROTOCOL_V1.json --protocol-sha256 76480c80df71700c7a39906936521e5542ddc9c788282ea3a165dffafa7dc1f0 --output local_raw --oracle-pythonpath .
python -B recovery_check.py --protocol RECOVERY_PROTOCOL_V1.json --protocol-sha256 76480c80df71700c7a39906936521e5542ddc9c788282ea3a165dffafa7dc1f0 --evidence local_raw --oracle-pythonpath . --output local_check.json.gz
python -B recovery_regression.py --protocol RECOVERY_PROTOCOL_V1.json --protocol-sha256 76480c80df71700c7a39906936521e5542ddc9c788282ea3a165dffafa7dc1f0 --output local_regression
```

只审已发布的证据可跳过 writer，直接把 checker 的 `--evidence` 指向 `recovery_validation_v1`，使用新 receipt 输出名。这会独立重算完整参考，不只读取已经写好的 `gate_passed`。

- `recovery_eval.py` 的退出码 0 **仅表示完整写出诊断证据**，绝不是科学 gate 通过。
- `recovery_check.py` 的退出码 0 要求 frozen F64 与双字 FP32 两模式所有行通过；1 表示拒绝/失败。普通 FP32 的完整失败记录不被删除，也不提升为准入。
- `recovery_regression.py` 的退出码 0 只表示两个已打开集合的 required modes 回归通过。
- `recovery_cost.py` 的退出码 0 只表示成本 receipt 写出；不能用它替代数值 gate。记录失败批时也不会将失败耗时当作完整评估优势。
- preflight 和 instruction inventory 各自的退出码仅属于对应窄检查。

所有输出为 create-only。协议、输入、源、build receipt、binary 和原始 evidence 哈希会在检查前后绑定。用 `build.py --output rebuilt.so --receipt rebuilt_build.json` 可另行重建；冻结验证针对随附 binary 的精确哈希。不同编译器产生的新 binary 需要明确的新构建身份和回归，不能暗中覆盖 `recovered.so` 并沿用原哈希。

此独立集合现已打开。今后任何数值调参只能把它当回归；新候选独立验证需要另一个计算前冻结的集合。
