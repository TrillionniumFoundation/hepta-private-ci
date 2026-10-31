# 本轮经济性测量的适用范围

本文审阅冻结协议、计量实现和进程计数器，不读取正式测试预测，不选择模型或调整参数。
正式质量结论由全部作业结束后的预登记分析给出；本说明不提前判定任何模型获胜。
依据为 [protocol.json](results/study001/protocol.json)、[training.py](training.py)、[cost_meter.py](cost_meter.py) 和 [analysis.py](analysis.py)。
协议 SHA256：`643320e6d8e081df54e0ef8362de95d1eebddbd5b026f4e2373cf33d97a183c1`。
登记规模为 168 个作业、3 个配对种子、最多 3 个并发 worker，每个训练进程限制为 1 个 CPU 计算线程。

## 先满足质量条件，再讨论节约

比较必须保持同一 condition：任务、宽度、登记更新数、batch size、学习率和训练 CPU 预算。
同一 condition 内还必须分别比较同一长度或缺失模态 case、相同输入与标签哈希、完整的三个配对种子。
checkpoint 只能按验证集交叉熵选取；不能将不同长度、缺失情形或筛选出的有利种子混成一个优势数字。
预登记非劣条件同时要求：准确率差的名义 95% 区间下界 ≥ −0.02；交叉熵比的区间上界与均值比均 ≤ 1.05。
只有通过该质量条件，且 whole-worker CPU 配对比值的 95% 区间上界 < 1，才可报告该 condition 的 CPU 节约。
区间基于三个配对种子；未作多重比较校正，不能据此宣称跨任务、跨宽度的普遍优势。
参数数量最大相对差 ≤ 5%、训练 CPU 最大相对差 ≤ 10% 是机制归因的额外匹配条件，不能由相同名义宽度推定。
固定更新数、实际更新数相等、相同训练 CPU、相同 whole-worker 成本是不同条件，应分别展示。
`equal_cpu` 的 15 秒预算约束训练循环 CPU，最多超出一个已完成 minibatch；它不约束验证、启动、最终推理或总 wall。
AV 分支为 15 个作业；其 48 个 clip 沿用既有演员分割，属于开发验证，不能当作新未触碰泛化证据。

## 成本账目及禁止重复相加的部分

| 字段或账目 | 实际范围 | 比较限制 |
| --- | --- | --- |
| `child_user_seconds + child_system_seconds` | `wait4` 的 worker CPU；包含启动、导入和全部任务阶段 | 主总账；包括该 worker 已回收的子进程 |
| `wall_seconds` | 启动命令至回收退出 | 共享主机、并发和调度影响延迟 |
| `training_cpu_seconds` / `training_wall_seconds` | minibatch 数据取样、前向、反向、优化更新 | worker 总账的子项；验证和 checkpoint 不在此训练时钟内 |
| `worker_body_*` | 函数入口至最终 summary 写入前 | worker 总账的子项；排除其导入和最终写入 |
| `supervisor_cpu_seconds` | meter 启动、轮询与回收子进程 | 另列开销；排除 meter 自身启动导入及凭证序列化 |
| `child_peak_rss_bytes` | Linux `wait4` 报告的最大 RSS | 含运行时与训练等阶段；不是并发进程 RSS 之和 |
| checkpoint bytes | 模型、优化器、RNG 等恢复材料的磁盘字节 | 不等于推理模型权重或在线状态内存 |
| frontend preparation | 共享的原媒体下载、解码、特征准备记录 | 单列一次；不能每个 worker 重复收取，也不能隐去 |

正确的 worker 总成本就是该 worker 的完整 receipt；不能再加内部 training、validation 或 inference 时钟。
研究总账可合计互不包含的 worker CPU、单列 meter 开销和一次共享准备；失败尝试也应披露。
如果另用外层 meter 包住整个调度器，其已回收后代 CPU 会包含内层 worker，外层与内层总额不能相加。
三个 worker 并发时，worker wall 之和不是研究 makespan；应另报调度器 elapsed wall，峰值内存也不能按 worker 峰值求和。
环境安装、研究准备、未回收的外部进程和云服务资源没有完整计量，不能将局部账目称为完整研发成本或货币成本。

## 已有实际进程与硬件计数器观测

取已完成的 [cpu_mqar_transformer_w16_s31067 receipt](results/study001/meter/cpu_mqar_transformer_w16_s31067.json) 说明计量器确实工作，不用于模型优劣比较。
该进程于 2026-10-31 01:54:26 UTC 结束，returncode=0，已由 `wait4` 回收。
实测 user=19.712555 秒、system=0.393236 秒、CPU=20.105791 秒、wall=20.642260 秒、peak RSS=319,811,584 bytes。
meter supervisor CPU=0.258682 秒；block input/output operations 分别为 161,952 / 38,384，不能据此换算字节。
该凭证 SHA256 为 `578056796fa0ade7db4438f64f997e4395118e10aa705c5295eac22c19f0a5a4`。
子进程 `/proc` I/O 的有效样本为 0，该例记录 `FileNotFoundError`；独立负载验证还观测到 `PermissionError`。
因此 read/write bytes 为 `null`，不是 0；这反映当前容器可见性限制，不能解读成零内存流量或零磁盘访问。
meter 观测的 `/dev/nvidia*` 与可读 RAPL energy 接口均为空；GPU 和 physical joules 保持 `null`。
真实写读负载、退出 7、超时和拒绝覆盖的验证见 [meter verification](results/async_frontend001/cost_meter_checks002/VERIFICATION.json)。

## 异步输入、推理时间与状态内存

前端已验证 48 个原 clip、13,723 个原生时间事件、48/48 前缀检查；没有统一时间网格或未来插值。
其准备函数记录 CPU=13.463281 秒、wall=28.767469 秒，包含已回收的解码进程；不是完整生命周期成本。
这些时钟排除先前首 clip 下载与预检、解释器导入、测试、计量器验证、最终审计和环境工作，详见 [final verification](results/async_frontend001/FINAL_VERIFICATION.json)。
固定源媒体共 13,411,707 bytes，保存 NPZ 共 3,442,630 bytes；网络传输耗时不等于网络能耗。
已登记 `training.inference` 是 CPU 上 batch=1、一次预热后五次整段前向，使用 `torch.no_grad()`。
32/64/128 长度的合成计时通过重复输入构造；该计时本身不证明长序列泛化或新增信息的处理质量。
AV 计时使用首个载入样本的有效长度，不是全部演员、长度分布或真实实时采集延迟的统计。
`persistent_numeric_state_bytes` 数的是返回状态的张量逻辑字节；`persistent_storage_bytes` 数去重后的底层 storage。
二者只覆盖返回的持久状态，排除参数、优化器、输入、整段输出和辅助轨迹；须与 whole-worker peak RSS 分列。
有限的 `no_grad` 状态大小不意味着训练/BPTT、所有辅助输出或整个前向实现具有常量内存。
当前 Transformer 未实现用于该测量的在线 KV state，故状态字段 `None` 表示未提供，不能作 0 字节参与比值。
整段前向延迟不是逐 token decode 延迟；不能由当前实现推断优化 KV-cache、FlashAttention、GPU 或融合 kernel 的部署速度。

## 尚不能验收的硬件与部署主张

| 主张 | 本轮缺少的直接证据 |
| --- | --- |
| 更低焦耳或功耗 | 同一硬件、同等质量、包含空闲基线和测量边界的可读能量计或外部功率仪 |
| 更高 GPU 吞吐或更低显存 | 实际 GPU、同步计时、对应 kernel、batch/precision 配置和显存峰值测量 |
| 事件稀疏带来硬件节约 | 实际跳过的算子与访存、硬件执行轨迹；连续状态或事件数本身不构成节能证据 |
| 分布式通信更少 | 实际多设备/多机拓扑、collective/消息字节、等待与能耗；当前没有这些运行 |
| 大模型线上更经济 | 同等任务质量、服务 batch、上下文、吞吐与延迟目标下的训练及服务实测 |

`training.inference.network_bytes=0` 的范围仅为本地单进程模型执行；不是分布式基线通信测量，communication joules 仍为 `null`。
可选的极小补充是正式矩阵结束后，在单独进程中加载预先指定 checkpoint，用训练集第一条 AV clip 做 batch=1 串行 no-grad 推理。
保存冷启动 receipt、预热后五次 CPU/wall、有效事件数及两种状态字节；固定 dtype/thread/source，不新训练、不读测试预测、不选择有利样本。
该补充只能检验串行实现和现有计量口径；在正式质量条件通过前，仍不能形成跨模型经济性结论。本文未执行该补充。
