# 已训练 HCSN 与真实 native owner 的执行绑定

`results/attempt001` 已完成，结果为通过。事前固定的对象是 `fixed/selective_copy__value_jg__seed881101`；工具独立重算第 48、96 步验证预测的 FP64 交叉熵，按最小值、完全相同时取较早步骤的规则选中第 **96** 步。它没有根据正式测试分数更换模型，没有新训练，也没有读取正式 test/OOD 预测或标签。输入探针仅重复首个训练样本的 `x` 和原始 `dt`。[来源绑定](results/attempt001/BINDING.json)、[完整结果](results/attempt001/RESULT.json)

## 来源与不可变标识

执行前核对了外部固定 INDEX 的成员分片、所需七个研究文件、15 个注册科学源码、原 hosted 预检、绑定包六个文件和 native binary。运行后的 `source_unchanged=true`。预先准备的绑定包见 [PREPARED.json](PREPARED.json)，实际输入、源码及权重记录见 [BINDING.json](results/attempt001/BINDING.json)。

| 对象 | 固定标识 |
|---|---|
| 绑定工具封存提交 | `d8b94bd750b4c52bd253b81285acc6c4a2dbeacf` |
| 内容训练源码提交 | `c9063043d088b6b469e740b9b6f341f3faea3928` |
| 研究协议 SHA256 | `911067f668c94a68ca41af710e1977005806dad202fbf18f32bda580b077a27b` |
| 发布归档 INDEX SHA256 | `8002a5ed5d6f3c0b30486097123432d570f67056790f72a93d707add9153ca1d` |
| 所选权重 NPZ SHA256 | `d7b1b428bf1a19cd28efb2a678b1a7e60248d301f674dba3f99d0cd1e8f8b686` |
| Native 源码提交 | `5898cd8b0f724c3152b6cc52856721f72e5e08be` |
| Native 源码清单 SHA256 | `6addea031fa9ba2ca403137d8d10da6088c255474c681b106d9a2706c645dd09` |
| Native binary SHA256 | `1dc702aea6a448ad84407aeb71dc8f23066205fab79fe7c6859fc02c55e6f7a5` |

权重归档为 81,693 字节，其中参数张量为 81,632 字节。外部来源固定先于本次执行；对任意本地输入自行计算哈希不构成相同的来源证明。[绑定合同与复现命令](README.md)、[native vendor 清单](../../hcsn_free_boundary_v1/native_vendor/MANIFEST.json)

## 连续状态、恢复与真实决策

长度 128 的逐 token 流在第 37 步保存完整数值状态，由新 Python 进程重新加载权重与状态后执行余下输入。后缀 logits 与最终状态均逐位一致；批量与流式 logits 最大绝对差为 \(2.3842\times10^{-7}\)，argmax 分歧为 0。中断点不应期质量为 0.273509，因此检查覆盖了有不应期质量的状态恢复。该序列最大概率质量缺陷为 \(4.2026\times10^{-8}\)。[结果的 `stream` 字段](results/attempt001/RESULT.json)

本次实际启动 **7 个 native owner 进程**：连续运行、三步前缀、新进程恢复各一个，加上四个消息干预进程。连续运行与“3 步＋恢复后 3 步”的神经状态逐位一致，事件动作、checkpoint、事件摘要和 readout 等登记语义字段一致；物理耗时没有要求逐位一致。二者均真实执行五次 KEEP，然后 STOP。停止后的神经读取入口拒绝请求，新增神经调用为 0；owner 也拒绝终止后的新 tick。重复事件的幂等验证通过。各进程成本收据均记录退出码 0，owner 权限保持 `DENY_ALL`。[结果的 `native` 与 `causal` 字段](results/attempt001/RESULT.json)

四组干预使用同一未标注训练序列中的实际高、低 \(J-G\) 状态，固定 owner 前缀和其他消息字段。阈值取二者中点 0.5297019631，仅交换连续价值消息：

| 神经状态 | 实际状态的 \(J-G\) | 发出的价值消息 | 实际动作 |
|---|---:|---:|---|
| 低值状态 | 0.451508 | 0.451508 | STOP |
| 高值状态 | 0.607896 | 0.607896 | KEEP |
| 高值状态，换低值消息 | 0.607896 | 0.451508 | STOP |
| 低值状态，换高值消息 | 0.451508 | 0.607896 | KEEP |

这证明已训练网络的价值消息能经真实 IPC 因果地改变 owner 决策。该探针使用单独登记的工程停止目标；五次 KEEP 后停止还包含显式工程预算。它没有测得分类最优停止策略或停止带来的任务效用收益。神经计算仍在 Python/PyTorch 中执行，原生进程负责消息验证、持久化、决策和终止约束；不能据此宣称已经实现编译后的原生神经内核。[执行协议](PROTOCOL.json)、[驱动实现](driver.py)

## 序列长度与成本范围

三个独立测量子进程分别处理长度 32、128、512，batch size 均为 1。批量推理预热一次、记录三次；逐 token 推理记录一次。以下是这台主机的参考实现测量，不是跨机器统计或架构吞吐排名。[三个长度的原始测量](results/attempt001/RESULT.json)

| 长度 | 批量墙钟中位数 | 逐 token 全序列墙钟 | 逐 token 单步 p50 | 该长度完整子进程 CPU |
|---:|---:|---:|---:|---:|
| 32 | 18.626 ms | 110.888 ms | 2.987 ms | 1.536225 s |
| 128 | 66.273 ms | 380.845 ms | 2.886 ms | 1.936523 s |
| 512 | 254.968 ms | 1547.297 ms | 2.867 ms | 3.755105 s |

全部长度的 logits 有限、argmax 分歧为 0；最大批量／流式差异为 \(4.7684\times10^{-7}\)。各时刻的**持久神经数值状态为 484 B**，包括 elapsed、content、活动／不应期概率质量和 boundary。这是固定 batch、固定模型下的状态张量统计，不包括权重、输入、输出、临时张量、Python 对象、native 日志及 checkpoint，也不包括训练 BPTT 图；不能据此声称总内存随序列长度不变。[规模测量的 `state_scope`](results/attempt001/RESULT.json)

外层 `wait4` 对整个 worker 及已回收后代记录 **12.164039 CPU 秒、12.418240 墙钟秒**，包含解释器导入、来源验证、全部恢复／长度／native 子进程、IPC 与执行记录写入。上述子进程和推理时钟均嵌套在这一总量内，不能重复相加。该计时排除启动器自身、依赖安装、此前归档下载恢复及事后本文整理；启动器另记录至收据处 CPU 0.037541 秒。`ru_maxrss=256076 KiB` 是该 `wait4` 的进程峰值统计，既不是 484 B 状态大小，也不是进程树同时占用内存之和。[完整成本收据](results/attempt001/WHOLE_WORKER_COST.json)

执行环境为 Python 3.12.14、PyTorch 2.8.0+cpu；CUDA 不可用，没有读取到能量计数器，Joules 保留 `null`。本次是 CPU 参考执行证据，不能推出 GPU 加速、能耗优势、优化后硬件上限或基础模型规模可行性。[硬件观察](results/attempt001/HARDWARE.json)

## 主要结果文件

| 文件 | SHA256 |
|---|---|
| [RESULT.json](results/attempt001/RESULT.json) | `6d42c2675f30dfdea8884eca2931f4e15129dc29ca1c3251982b14902ffdb732` |
| [WHOLE_WORKER_COST.json](results/attempt001/WHOLE_WORKER_COST.json) | `e424b0dea500cfad28ae78c1d67d085bdd242c9a78d7a920d28622b8a5df0bb8` |
| [BINDING.json](results/attempt001/BINDING.json) | `b52dea7080ff7db6c814db2047c024e9b140c5aa1de89c6cd9645de6c262d0ee` |

原始执行目录共 83 个文件、409,192 字节，包含各子进程、消息、状态和成本记录。本文件是执行完成后的说明，不修改原始记录、实验协议或科学验收门槛。
