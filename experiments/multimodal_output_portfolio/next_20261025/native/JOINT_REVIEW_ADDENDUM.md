# Joint 静态审查补充：两处冻结身份缺口已修复

本补充保留 [JOINT_STATIC_REVIEW.md](JOINT_STATIC_REVIEW.md) 对当时版本的事实记录，不改写原审查。复核的 [joint/evaluate.py](../joint/evaluate.py) SHA256 为：

`bf2992eae62232946f37f96e1cc4381720523973b2ea45e98fca9a5e279d6256`

## 修复一：训练结果绑定实际评价模型

`freeze` 现在要求恰好存在 `17/29/43 × mean/entropic` 六个 arm。训练结果必须绑定未变化的 registration，registration 中 18 个训练源码身份逐项校验；每个 seed 的两个 arm 必须具有相同 initial parameter SHA 与 exogenous schedule SHA。每个 arm 的 seed、profile、实际 checkpoint 绝对路径和当前 SHA 都必须等于训练记录，之后才登记正式协议。

除静态检查外，本审查以 stdlib 对现有 `/tmp/hepta-ndu-next-joint/training-001` 的 registration、六个 checkpoint 文件、三个 seed 的配对记录和 18 个训练 source pin 做了只读核对，全部匹配。该核对没有导入 Torch 或加载模型参数。

## 修复二：独立 ASR 资格绑定实际运行资产

`freeze` 现在读取独立资格的 `observers.json`，将其中 `base.en` 与 `small.en` 的 manifest SHA 分别与实际传入 `audio_assets` 下的对应 manifest 比较。接着逐个核对 manifest 所列的实际模型、tokenizer 等资产 bytes 与 SHA，并把资格 receipt 和实际文件纳入正式冻结清单。运行器仍在开放来源前校验冻结清单，并单独校验实际执行参数对应的路径。

因此，原审查提出的“只检查登记路径，却可能从另一个实际参数目录加载同名模型”的缺口，在所审查版本中已经关闭。这里确认的是代码中的检查路径；不把这次静态审查说成运行了 ASR 或重新授予了它的统计资格。

## 范围保持

没有修改训练冻结字节、没有运行训练/模型/ASR、没有打开新的确认来源。原审查关于完整正则目标、采样训练与 greedy codec 评价差异、固定三 seed 面板、24 个 writer/speaker connected cluster、有限数字语音和构造运动视频的科学限制仍然适用。这两项身份修复关闭的是可执行证据的绑定缺口，不改变训练或质量结果。
