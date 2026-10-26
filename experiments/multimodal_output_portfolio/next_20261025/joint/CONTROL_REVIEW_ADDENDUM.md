# 独立静态复核：V3.1 资格适配与实际 codec 身份

复核者：`control_next`。本记录只涉及静态源码与文件身份检查，没有运行模型、ASR、codec 或打开任何新的确认来源，也没有改变实验源码、协议、门槛或结果。它补充既有 [联合静态审查](../native/JOINT_STATIC_REVIEW.md) 与 [身份修复复核](../native/JOINT_REVIEW_ADDENDUM.md)，不替代实际独立资格和正式确认。

## 两个已复核版本

| 阶段 | `joint/evaluate.py` SHA256 |
| --- | --- |
| V3.1 资格适配 | `cfc12edbf87929eeba8eb48ef720d41c39fec9fa846a712af8502948cec3fd36` |
| codec 身份增补 | `249c009240a0929dd01ce0e0af07eb5fd8cd842d1925460516059d85e6d75a94` |

第二次复核逐项比较了这两个版本。差异只新增实际 codec 路径与文件身份登记、运行前检查、向 `write_media` 显式传入绑定路径和运行后复核；未改变观察器组合规则、训练模型、来源、计分或统计门槛。

## V3.1 资格适配

当前生产资格记录的 `version` 仍为 `v3`，即使其静态执行守卫已另立 V3.1；评价器按实际生产 schema 检查，没有误要求一个不存在的 `v3.1` 字段。冻结要求独立资格完成、300 个实际录音、来源与全部观察器开发独立、命名的 `PRIMARY=consensus_or_single_v3`、准确率达到原 `.85` 门槛，而且 `primary_eligible` 必须为真。组合器只使用实际转写：一致时取一致结果，仅一个非空时取该结果，分歧或双空时拒绝。目标标签不进入这项组合决策。

资格 registration 必须绑定 `ENSEMBLE_SELECTION_V31.json` 的实际 SHA；该 selection 的全部冻结依赖还会逐项核验。资格 `observers.json` 中两个 Whisper 模型的 manifest SHA 必须等于实际传入 `audio_assets` 中的对应 manifest，随后核验 manifest 所列资产字节。正式运行在开放新来源前，再次核验冻结输入及实际参数目录的路径、SHA。该链条保持了“获得资格的观察器就是实际运行的观察器”的身份连续性。

六个训练 arm 仍必须恰好构成 `17/29/43 × mean/entropic`。每个 arm 绑定训练 registration、原训练源码、实际 checkpoint 路径和 SHA；同一 seed 的两个 arm 必须具有相同初始参数和外生 schedule 身份。此处没有重新执行训练或读取模型参数。

## codec 身份增补

冻结阶段通过 `shutil.which` 查找 `ffmpeg`、`ffprobe`，解析实际绝对路径，并将两个可执行文件的字节 SHA 纳入 `frozen_candidate_sha256`。运行器先复核全部冻结输入，再比较实际解析路径与 protocol 的 `codec_executables`，随后才开放正式来源。

实际生成调用把绑定路径显式传入 `carrier_media.write_media`。该函数执行真实 PNG/WAV/MP4 写入，并以相同的显式路径做 lossless readback，核验图像、音频、mux 音频和视频帧字节，以及四秒的 presentation clock。评价结束前再次检查全部冻结文件 SHA 和当前 codec 查找结果。

`observe_bundle` 的额外读回仍调用 `read_media` 的默认 `which` 路径。所审查代码没有修改运行环境，在固定研究 host/PATH 的边界内使用相同可执行文件；此复核不声称能抵抗恶意 host 的瞬时路径替换，也不声称两个 executable SHA 已完整固定操作系统、所有动态链接库或部署性能。

只读检查时的实际可执行文件身份：

| 路径 | SHA256 |
| --- | --- |
| `/usr/bin/ffmpeg` | `ed16af623947494a72e284b6eb8ff225f2da22b38b5d5069c2fd4b4ba3384e41` |
| `/usr/bin/ffprobe` | `272f6ebc634a63d9c8b4ca68e964119d980f25154e5aa2c35e5487da48e9a58f` |

## 相关复核源码身份

| 文件 | SHA256 |
| --- | --- |
| `media/qualify_ensemble_v31.py` | `523471d953b1f41352db34ce5b79538887c053de54921c21e270528000da2525` |
| `media/ensemble_event.py` | `671c93468a02b036c806630f8c22beaeff2181d22437b7d3ad08403fd65abc58` |
| `media/ENSEMBLE_SELECTION_V31.json` | `bf70bd1d69ce42c0f2161eb589b7dcf061d6c7a51f68b16c88a322bfbacdbaaf` |
| `media/runtime.py` | `032aea2fcd90f05974c7655c0bb0a73009665d9a43ed4e20ced3f6024163d76a` |
| `closure_20261025/media/carrier_media.py` | `466a164c787295a219720103346276354288d92a595043a3fc56849bae750f7c` |

## 结论与范围

在上述两个明确版本中，未发现此次 V3.1 schema/PRIMARY 适配或 codec 身份增补的阻断性错误。该结论是实现与证据绑定的静态复核，不授予观察器统计资格，也不宣称 joint 模型获得质量、成本或四模态成功率收益。

原有范围保持：固定三 seed 面板、24 个 writer/speaker connected cluster、构造数字任务和有限语音 decoder、采样训练与 greedy 执行之间的策略差异，以及固定 arm 顺序下成本只能作描述性比较。新的正式来源仍须在候选与协议冻结后按原门槛执行。
