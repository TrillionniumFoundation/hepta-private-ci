# Hepta 连续边界图文编码器

`port.py` 中的 `PortEncoder` 只通过四个时间位置、每位置八个标量把第一层的样本信息送到第二层。图像输入为批量 32×32 RGB 原始像素，文字输入为至多 24 个训练词表 ID。两个模态各自产生一个单位长度的 32 维向量，其点积给出图文匹配分数。

第一个群体层对每个位置和群组输出归一化对数边界 `b = log(B(P)/B0) = log1p(kappa*u)`。驱动 `u` 取自当前输入、前一时刻边界和前一时刻两项价格反馈的有界组合。四个存活状态经带吸收边界的转移表推进，当期首达质量进入不应期，前一期的不应质量按固定分布回注。存活质量加权的 E 和 L 价格来自冻结的精算表。在模型中 L 代表违约条件下计价的损失。金融论文的经济含义、跨层连接和复位机制分别在定价假设与神经网络设计中解释。

调用 `lower` 可以取得发送端的连续边界。调用 `serialize` 得到真正经过接口的浮点或无符号整数数组。接收端只调用 `decode` 和 `upper`，跨层没有传入图像、词、样本 ID、前一层隐状态或跳接。在固定参考边界 B0 时，归一化对数与实际 B 一一对应。将一批样本的所有边界钳至相同值，就能直接验证输出与原始输入之间的链路。

```python
from pathlib import Path
import torch
from port import PortEncoder

net = PortEncoder('literal', 32, 4171, vocabulary_size, Path('law4.npz'))
image, text = net(pixels_uint8, word_ids)
loss = torch.nn.functional.cross_entropy(15 * image @ text.T, paired_indices)
loss.backward()

net.eval()
with torch.inference_mode():
    boundary = net.lower(pixels_uint8, word_ids)
    transmitted = net.serialize(boundary)
    image_replay, text_replay = net.upper(net.decode(transmitted))
```

示例损失适用于批内每份描述仅出现一次。配套训练入口 `train_port.py` 对相同描述组成的多个正例使用对称对比损失。默认 FP32 的每个图像或句子发送 128 字节；8 位变体发送 32 字节。浮点模式直接经过普通反向传播。8 位实验使用直通梯度估计，推理时以实际 8 位编码验证重放。硬脉冲对照把每个位置的 64 个阈值事件打包成 8 字节，每个样本也为 32 字节。传输字节数可以直接测量，能耗和事件稀疏执行需要另外的硬件实验。

`external.py` 和 `nocaps.py` 固定输入、去重和词表。各次真实训练在 `selected.json` 保存所有源码验证端点和权重指纹；`confirm_port.py` 从已经封存的权重重放两种字节格式，执行钳位、打乱、词汇难负例与逐图推断。图文输入端始终保持相同的四个块。改变时间分辨率、隐藏通道规模或域外词表会定义另一项实验。
