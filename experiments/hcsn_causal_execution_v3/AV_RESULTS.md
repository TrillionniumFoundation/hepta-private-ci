# AV 内容充分性与普通共同前端：本轮结果

本轮普通特征模型能够拟合 AV recording-binding 的训练关系，但**仍未建立可靠的跨 actor 绑定能力，也未获得合格的共同情绪 encoder**。所有结果来自已有的 CREMA-D 低分辨率预处理特征及既往已见的测试 actors；不能作为新 actor 上的确认性结果，更不能归因于解析 HCSN 核心。[完整结果](results/av_probe/summary.json)

## 1. 固定实验与选点

使用原有 train/validation/test 分割：训练 4 actors、24 clips，验证 2 actors、12 clips，测试 2 actors、12 clips。每个 actor 的 DFA 句有六种情绪各一条。情绪任务每 clip 一个标签；binding 每 clip 配一个同录制正例、一个同 actor deranged 负例，因此分别有 48/24/24 pairs。重复配对不会增加独立 actor 数。

冻结四类普通特征：单模态前缀 moments（96 维）、双模态 moments 外积（2,304 维）、因果 as-of 配对的时序互相关（1,280 维），以及三者组合（3,680 维）。对每类固定六个 ridge 正则化值与五个温度，共 **120 candidates/task、240 candidates**。标准化与参数拟合只使用训练数据；验证 CE 最小者获选，同分保留声明顺序中的第一项。两个任务均完成选点、写入 checkpoint 与选择记录后，才打开本轮测试预测和干预。既往测试结果及部分原始数据元信息早已被观察，本轮不声称新鲜留出确认。[冻结协议](results/av_probe/protocol.json) · [两个任务选点完成记录](results/av_probe/SELECTION_COMPLETE.json)

协议 SHA-256：`8c6721f7376150cca5b604bd016d195eea94394a98bbf17f10dbbd0bb5f1259b`。
冻结执行源码 SHA-256：`890001592133a414e22863e903d10f62c927558938f6fcc0afa30a36d63ea127`。

## 2. 主要结果

| 任务 | 验证集选中的普通模型 | 训练准确率 | 验证准确率 / CE | 旧测试准确率 / CE |
| --- | --- | ---: | ---: | ---: |
| AV 六分类情绪 | moments，ridge α=0.1，温度 0.25 | 100% | 33.33% / 1.287940 | 41.67%（5/12）/ 1.877591 |
| AV 同录制 binding | combined，ridge α=0.1，温度 0.5 | 100% | 75% / 0.610472 | 54.17%（13/24）/ 0.728022 |

预定的探索性前端筛查线分别为情绪验证准确率 50%、binding 75%。情绪未通过；binding 仅在验证集上达到该筛查线，旧测试的 54.17% 不能支持通用绑定能力。3,680 维相对 48 个训练 pairs 的容量足以拟合训练样本；100% 训练准确率只排除了“这种普通交互表示也无法拟合训练关系”，不能代替泛化证据。[情绪选择记录](results/av_probe/async_av/selection.json) · [binding 选择记录](results/av_probe/av_binding/selection.json)

| 测试 actor | 情绪准确率 | binding 准确率 |
| --- | ---: | ---: |
| 1023 | 66.67%（4/6） | 58.33%（7/12） |
| 1040 | 16.67%（1/6） | 50%（6/12） |

两个 actor 的描述性重采样区间分别为情绪 [16.67%, 66.67%]、binding [50%, 58.33%]。独立 actor 只有两个，这些区间不能当作可靠的总体置信区间；尤其不能把 binding 的下端为 50% 解读为已证明超越机会水平。[逐样本情绪预测](results/av_probe/async_av/test_normal.npz) · [逐样本 binding 预测](results/av_probe/av_binding/test_normal.npz)

## 3. 干预与内容边界

| 条件 | 情绪准确率 / CE | binding 准确率 / CE |
| --- | ---: | ---: |
| 正常 | 41.67% / 1.877591 | 54.17% / 0.728022 |
| 缺音频 | 16.67% / 2.526231 | 50% / 0.702896 |
| 缺视频 | 25% / 1.865753 | 50% / 0.726083 |
| 模态内内容打乱 | 25% / 1.420886 | 54.17% / 0.806379 |
| 模态错配（情绪）／仅元数据（binding） | 25% / 1.921019 | 50% / 0.701634 |

binding 的单模态完整输入字节边缘精确相等检查通过；任一模态本身无法提供配对标签。模型不把 actor、clip ID、情绪标签、绝对时钟、age、总长度或总时长作为特征。去掉任一模态或仅保留元数据时结果为 50%，但内容打乱后准确率没有下降，因此当前正常条件的微弱增量还不能解释为可靠的时序绑定。

本任务是同录制识别。每 actor 的固定 DFA 句只有六种情绪各一条，within-actor 负配对还改变情绪；不能据此分离一般语义绑定、情绪一致性和录制特征。低分辨率全帧 DCT/log-mel 特征、有限 actors 和验证网格选择都限制外推。

## 4. 可供因果执行器调用的接口

`av_probe.py` 的热推理接口只依赖 NumPy：

```python
from experiments.hcsn_causal_execution_v3.av_probe import load_encoder, predict_prefix

model = load_encoder("selected_encoder.npz")
probabilities = predict_prefix(model, accepted_x, accepted_observed)
```

调用者只传入已经 READ 的 40 维观测行。编码器只消费前 16 维内容及模态/可用性标志，忽略原始预处理中的 16:32 delta、age 和时钟；因此不会借用未 READ 观测产生的继承 delta。跨模态配对在已接受的视频到达时使用最近已接受的音频。moments 和互相关只在当前已观察前缀内计算，没有按未来完整序列长度重采样。该实现每次重新计算前缀特征，执行成本必须按实际调用计量。[源码](av_probe.py) · [行为验证](av_probe_tests.py)

选中模型：[情绪 encoder](results/av_probe/async_av/selected_encoder.npz) · [binding encoder](results/av_probe/av_binding/selected_encoder.npz)。本轮情绪前端仍未通过验证筛查，不能把它标为“强共同 encoder”；binding 模型也只能作为执行接口诊断候选。

## 5. 执行成本与证据

本轮运行体耗费 **1.496584 CPU 秒、1.497001 wall 秒**，包含预处理数据读取、候选拟合/选择、当前预测及证据写入；起点位于初始运行时导入之后。进程峰值 RSS 为 **208,676 KiB**，该峰值包含已导入运行时。CPU/wall 记录不包括解释器启动和初始导入，也没有重做原始媒体解码或测量网络、设备能量。因此它是组件运行体记录，不能称为完整端到端成本。[成本字段](results/av_probe/summary.json)

保存全部 240 个候选参数、480 份 train/validation 逐样本预测、两个选中 checkpoint 及全部测试干预预测。4 个行为测试通过，覆盖拒绝读取的 payload 不影响输出、继承 delta/age 不影响输出、真实内容/顺序会改变特征，以及空/单模态前缀可执行。

独立重算确认全部候选指标误差为零、选点确为最小验证 CE、checkpoint 哈希和冻结源码身份一致。初次独立审核遗漏实现中 CE 的 `1e-15` 概率下限，导致一个未选中的极端 bilinear candidate 不一致；保留了原失败记录，纠正审核公式后通过，没有改模型、选点或结果。[原审核记录](results/av_probe/verification.json) · [纠正后的审核记录](results/av_probe/verification_corrected.json)

## 6. 复现

从仓库根目录，在具备 NumPy 与上游数据模块所需 PyTorch 的 Python 环境执行。原运行使用 PyTorch 2.8.0+cpu；下列输出目录必须尚不存在，避免覆盖原证据：

```bash
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
python -m experiments.hcsn_causal_execution_v3.av_probe \
  --output experiments/hcsn_causal_execution_v3/results/av_probe_replay

PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
python -m unittest experiments.hcsn_causal_execution_v3.av_probe_tests
```

输入位置为 `experiments/hcsn_task_value_v1/results/async_frontend001/data/`。源训练与验证 NPZ 的哈希已写入冻结协议；训练数据的统计、选择规则和原始预测均可独立重算。下一步的主要障碍仍是更充分、可泛化的共同 AV 内容前端及更多独立 actors，而非给当前近机会水平的绑定器继续叠加解析动态后宣称解决识别问题。
