# 真实音视频 encoder 的新演员确认

本包检验当前 signed/QVI HCSN 能否在真实配对音频和视频上训练 encoder，并与相同宽度的 Transformer、LIF 作小规模直接对照。它不改旧主实验、通信实验或原 CREMA-D 负结果；不等于全模态基础模型验证。

## 已固定的任务

三个模型各 3 seeds：31011、41011、51011。每个模型有独立的音频、视频 encoder，共同的六类 emotion head；embedding 为 32 维。每个 encoder 都先经过 130→8 的线性层和 tanh。共同 frontend 和分类 head 按相同 seed 初始化。

| 模型 | 序列核心 | 输出给32维 projection 的特征 |
|---|---|---:|
| HCSN | 8个独立人口单元；signed-only；QVI+value/risk；mixed；合格 fast uniformization/Newton | 20维 receiver 特征的时间均值 |
| Transformer | 1层，宽8，2 heads，FF16，causal mask，dropout0 | 8维 token 的时间均值 |
| LIF | 宽8，0.9 leak，真实0/1 threshold/reset，recurrent连接，fast-sigmoid surrogate backward | 8维 spike 的时间均值 |

相同宽度不是相同参数量或相同内存。HCSN 删除了旧二类 readout，避免把无用 head 计入学习；结构掩码、活跃参数、实际物理人口状态与进程峰 RSS 分别报告。Transformer token 状态和 LIF 膜/脉冲状态的逻辑字节不是总训练内存。

每臂最多 256 次真实 Adam 更新、batch16、lr0.003、clip2，600 attempted-update CPU 秒为安全上限。触发上限的运行明确记为 censored；不会写作相同更新数的完整试验。统一 loss 为 fused CE + 0.25(audio CE + video CE) + 0.5 symmetric InfoNCE，温度0.1。每64步评估dev，按最小 fused CE 选择，step0初始模型也属于候选。

## 数据与时间契约

固定复用原已审计的 16 train actors / 384 clips、6 dev actors /144 clips 的32×128低层特征缓存。原公开的8 test actors不复用为新确认。新演员按固定盐哈希从三份已核演员清单外的23候选中选8位：1074、1021、1007、1075、1018、1009、1030、1006。

每位演员4句×6种情绪，共192 clips；官方 CREMA-D commit `1658cd342dff90010aa843eaeebd53610a08b1dc` 的逐媒体LFS SHA和字节在下载前登记。新媒体登记总量68,564,335 bytes；包括失败传输在内的有界上限150,000,000 bytes。演员新颖性只对这三份实际检查过的历史清单成立，不声称扫描过所有历史分支的所有实验。

音频为64维log-mel加64维一阶差分，视频为16×16灰度DCT的8×8系数加差分；固定原 decoder 作全片共同区间重采样。低层均值/方差仅用旧训练演员。真实elapsed/dt保留在审计metadata，但模型只接收128模态坐标 + 全片统一的 t/31、1/32 两个时钟坐标。HCSN dt=.25 是归一化模型时间；这是 offline encoder。

早期未冻结方案曾拟给两模态输入同一真实片长；审查发现这可以成为配对捷径，在任何 AV fit 或新确认评分之前修正。原提案源、数据和修订理由保留。任务的数据入口逐元素拒绝非canonical时钟。另在all9 seal之后计算不训练的duration-only检索负控，不能把它当模型能力。

## 评估与封存

三类模型的九个完整终态、源码、数据摘要、初始/selected/last checkpoint及worker退出回执全部验证并seal后，才允许任何test模型评分。每个test worker重新验证全九槽，必须领取唯一claim。失败保留在三seed分母；没有test驱动重训或重选。数据解码在训练前完成，不能说测试媒体此前从未读取；保护的是模型评分与选模隔离。

报告 fused/audio/video 的accuracy、macro-F1、CE、Brier、ECE10，以及双向paired-recording R@1/R@5/MRR（全gallery和同actor gallery）。另报告跨actor情绪语义检索：删除查询演员的全部gallery记录，以相同acted emotion作为相关项，计算class R@1与mAP。寻找同一记录与跨演员语义关联是两个指标，不能互相代替。

独立后处理不导入Torch、模型或训练metrics，从原始保存logits/embeddings重新计算所有指标，并核对完整seal、预测SHA、标签、actor、clip与时钟数据。三个seed与八位演员是不同来源轴；只报描述性均值/SD和同seed配对差，不把192 clips当192位独立演员，不凭一个最佳seed声称架构优势。

## 复现

Linux operator runner使用`resource`及Linux的`ru_maxrss`单位；core数学保持Python/Torch代码。使用固定原依赖闭包与合格 fast 文件 SHA `a92d7cc45af0ccf1e1c2629ee9fe8ef1d4b0bc6dba335bbdc53cd909c42d80b3`。任何输出目录都必须是新的，既有结果不可覆盖。以下变量为示例绝对路径，不复用原确认集来冒称新的未见确认。

```bash
python -m qualification.hcsn_closure_av_20261125.acquire restore --root /absolute/av-data
python -m qualification.hcsn_closure_av_20261125.acquire register --root /absolute/av-data
python -m qualification.hcsn_closure_av_20261125.acquire acquire --root /absolute/av-data
python -m pip install --target /absolute/av-decode-deps --no-deps --only-binary=:all: scipy==1.17.0
PYTHONPATH=/absolute/av-decode-deps:/absolute/repo python -m qualification.hcsn_closure_av_20261125.prepare --root /absolute/av-data
python -m unittest qualification.hcsn_closure_av_20261125.tests -v
python -m qualification.hcsn_closure_av_20261125.campaign prepare --root /absolute/av-smoke --data /absolute/av-data/prepared_model_clock_v2
python -m qualification.hcsn_closure_av_20261125.campaign smoke --root /absolute/av-smoke --parallel 3
python -m qualification.hcsn_closure_av_20261125.campaign prepare --root /absolute/av-run --data /absolute/av-data/prepared_model_clock_v2
python -m qualification.hcsn_closure_av_20261125.campaign run --root /absolute/av-run --parallel 3
python -m qualification.hcsn_closure_av_20261125.analysis --root /absolute/av-run --source /absolute/repo --output /absolute/av-summary
```

`retime.py`仅用于本次保留旧提案缓存的单次迁移；干净重建直接用最终`prepare.py`，不重复解码。固定原train/dev运输commit为 `dca9febc8143c682077fe27d40dbeaa1137bcaa4`，逐part和逻辑文件双重SHA验证。原ODbL/DbCL声明及CREMA-D归属随cache保留。原始外部媒体不塞入Git；精确官方commit、LFS校验清单、获取回执、特征cache、normalization和decoder可供核验。

CPU费用分 update、fit body、完整worker、阶段child和协调器层；嵌套值不相加。媒体获取、依赖安装、解码、预检、旧提案修正、失败和等待也留原回执。能量未测。运行中结果不提前填为成功。
