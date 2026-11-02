# V13：真实预训练音频执行与六情绪演员留出开发参考

本轮取得并实际使用了新的真实预训练音频资产，不再停留于模型卡或下载
尝试：官方TorchAudio2.6.0+cpu `WAV2VEC2_ASR_BASE_960H`，377,664,473字节，
SHA256 `488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d`。
它是LibriSpeech960h自监督预训练并完成ASR微调的模型，**不是原v6强头，
也不是已经合格的情绪或AV绑定参考**。

该实物来自邻项目已完成的官方URL获取，当前真实字节与其保留的acquisition
manifest一致。SHA是那次实际获取时首次记录的字节身份，不冒称上游独立
签名。官方文档说明该模型权重按MIT分发；软件许可与权重许可分别记录。
377MB权重及现成Torch/TorchAudio runtime只读使用，没有重复下载或复制。

## 实际编码与输入边界

`strong_audio.py` 在构造模型前验证checkpoint大小与SHA，仅允许严格本地
加载；官方factory的strict state_dict加载及fairseq辅助轴转换保留。它
使用冻结的Torch/TorchAudio2.6.0+cpu，单CPU线程、eval和inference mode。
没有远程代码或随机权重回退。

`forward001/` 真正执行三次预训练网络：V12保留的一秒真实音频前缀，以及
附加未来NaN/大幅有限载荷的两个版本。hidden、CTC logits和1536维descriptor
逐位一致。已接受窗内NaN、短窗和错误权重均拒绝。它属于历史训练样本的
前向/因果边界检查，不是质量评价。

`cache_contract001/` 又实际解码原始 `1002_DFA_ANG_XX.flv` 的同步一秒窗，
音视频共同源起点0.027秒；先截取native PCM，再resample，最后真实运行
同一官方encoder。其1536维descriptor与邻项目固定TRAIN cache逐位相同，
最大绝对差0。这一同步源窗不同于前述V12烟测的native音频起点，未混淆
两个输入时钟。离线原文件解码是准备过程，不声称实时流式decoder资格。

全部288个真实TRAIN FLV、24演员、89,552,339字节都逐个核size/SHA；
prepared cache、每条descriptor/CTC及source身份均核验。288条完整cache
和实际使用的1536维descriptor都没有字节别名。1536维仅为最后hidden层
均值和总体标准差，不采用CTC字符特征、transcript或二元语句标签。

元数据比对还显示，这288个TRAIN录制与本线已知48及720录制清单的所有
train/validation/test，在actor、recordingID及rawSHA层面交集均为零。
这只是这两份已知清单的核对，**没有补全未知v5/v6排除账本，不能据此
声称新独立确认**。没有打开旧heldout payload用于训练或评分。

## 预声明25次实际拟合

固定源码/协议先在 [PR #4619](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4619)
的远端 `4c2fa0d86b9b09d5b26849b4738458fabc7b2945` 发布，随后root生成
真实publication记录才执行OOF；缺该记录时run会拒绝。来源/输入seal及
原始结果均保留，没有根据OOF结果调参或重选候选。

预声明单一lambda10 centered dual ridge，六情绪为ANG/DIS/FEA/HAP/NEU/SAD。
24个leave-one-actor-out折中，每折只在另23个演员的276条样本上拟合均值、
标准差和全部系数；留出演员12条、每情绪2条。另保存一个全288 TRAIN
拟合头，共25次实际fit。softmax温度固定1，明确尚未做正确率/概率校准。

| 历史TRAIN上的演员OOF开发指标 | 实测 |
| --- | ---: |
| 六情绪正确数 | 105/288 |
| 准确率 | 36.4583% |
| 未校准NLL | 1.680188274 |
| 未校准Brier | 0.789818032 |
| 实际拟合与权重 | 24个留演员头＋1个全TRAIN头 |

`readout001/` 保存全部25份权重、288份原始预测、每折train/held indices、
train actor列表、训练输入/标签哈希、每演员支持度和混淆矩阵。全TRAIN
拟合头没有用训练内准确率来争取采用资格。结果属于新六情绪开发任务，
既不等同缺失v6五类/绑定任务，也不能与旧12条测试数直接组成改善证据。
本轮没有加载validation/test，没有完成强音频原准入、AV绑定或校准参考。

## 完整CPU包络与剩余准入

| 新增不重叠完整waited-worker范围 | CPU秒 |
| --- | ---: |
| 真实三次前向与五项拒绝/未来控制 | 3.314803 |
| 全TRAIN cache/raw身份及真实同步prefix重执行 | 7.875889 |
| 预声明25次拟合、OOF评分与全部写盘 | 0.655452 |
| 合计 | **11.846144** |

这些值包括各worker的启动、导入、已等待的decoder孩子和输出写盘；内部
时钟已包含，不能再次相加。原cache的107.396369 CPU秒准备凭证作为另外
既有setup保留，不冒称本次新推理或零成本。开发、来源检索、未包住的
freeze/hash检查、上游预训练/微调和部分历史准备仍未知，因此完整项目
成本保持null。完整进程族RSS及设备焦耳没有本轮硬件资格，保持null。

预训练权重的可用性、实际执行与边界已取得真实新增证据。原v6强头/完整
历史账本、真正新独立群体、合格强音频及AV参考、完整前端准入仍未闭合。
当前原v6精确commit GitHub查询返回422，匹配branch查询为空，具体有限
查询见 `ORIGINAL_ASSET_LOOKUP.json`，不把它夸大成全局不存在证明。

独立数据/参数复算保存在 `../review/EMOTION_OOF_AUDIT.json`，**320/320通过**。
审计不导入作者fit函数，以eigendecomposition独立重算全部25个lambda10
readout、每折23演员标准化与全部OOF预测。权重最大绝对差2.33e−14，score
5.70e−13，概率1.03e−13；105/288及NLL/Brier均复核一致。其0.990825 CPU秒
外层审核包络由root独审账另外计入，不重复加到上述三个前端执行包络。
这支持登记实现及数据分工，不把执行成功或OOF描述值变成质量门PASS。
