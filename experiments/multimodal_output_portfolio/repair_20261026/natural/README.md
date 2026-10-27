# 自然语音与真实视频：小规模感知/计算控制实验

本实验实际使用真实朗读语音和带人工跟踪标注的视频，研究是否值得追加计算。
它没有训练全模态生成模型，也不验证语音合成、自然视频生成或复杂图文推理。
LibriSpeech 与视频是两个独立任务，不能拼接成同步多模态任务。

## 来源与冻结

- 语音：`openslr/librispeech_asr`，固定 revision
  `71cacbfb7e2354c4226d01e70d77d5fca3d04ba1`，原始 FLAC 与转录。
  validation 的 4 位 speaker、12 条用于拟合；test 的另外 8 位 speaker、
  24 条用于评价，speaker ID 没有交集。
- 视频：`opencv/opencv_extra`，固定 commit
  `579424605134b7d7027377bdc51f3c23536c4414`，原 WebM、gt 和 yml。
  David 拟合，Dudek/Faceocc2 评价；每个来源 160 帧。按 yml 正确对齐
  原视频起点：David 第 300 帧，其余第 1 帧，对应 gt 首行。
- ASR：冻结 `Systran/faster-whisper-tiny.en` revision
  `0d3d19a32d3338f10357c0889762bd8d64bbdeba`，CPU int8。神经参数没有更新。
  上游 Whisper 预训练是否见过这些公共录音，不能由此样本划分证明。

全部 96,510,742 字节的下载来源、内容哈希和分配见
`evidence/SOURCE_MANIFEST.json`。运行前冻结协议与源码，最终重新校验所有
输入和模型字节。原先 PyAV 19.0.2 与 faster-whisper 1.2.1 的
`metadata_errors` 接口不兼容；失败发生在首条语音输出之前。保留原失败和
完整视频结果，将 PyAV 固定为 16.1.0 后只恢复未开始的语音阶段，未重跑
视频或修改科学协议。

## 自然语音结果

控制器先运行 greedy，通过 segment mean log-probability 决定是否追加 beam-5。
阈值仅在 fit 数据上选择，结果为 `-0.4`。所有 test 文本都实际生成、写入
UTF-8 文件并重新读回，之后才与私有参考转录计算词错误率。

| 策略 | micro WER | 实际调用 | 总 wall 秒 | 总进程 CPU 秒 |
| --- | ---: | ---: | ---: | ---: |
| 固定 greedy | 5.3933% | 24 | 12.3476 | 40.2150 |
| 固定 beam-5 | 4.4944% | 24 | 13.7034 | 42.9715 |
| 动态追加 | 4.4944% | 32 | 15.8197 | 51.8903 |

动态策略改善了 greedy 的 WER，但与固定 beam-5 同质量且消耗更多计算。
**本轮没有取得相对最强固定对照的效率优势。**首次 greedy 和后续完整重算
的成本均已计入，没有把规划/首次调用当作免费。模型加载另耗约 0.190 秒。
CPU 和 wall 是本次共享主机的实际观测，外部负载未控制，不作稳健速度保证。

这是 8 个独立 test speaker 的小样本，不将 24 条或更细 token 数当作
独立来源，不作总体统计优越性结论。仅拟合一个 gate 参数，未训练 ASR。

## 真实视频结果

使用首帧允许公开的目标框初始化冻结模板，之后仅根据真实像素局部或全局
NCC 搜索；后续人工框在 TRACK.json 写入并读回之后才供评分器使用。
fit 选择阈值 `-1.0`，即本轮动态策略选择保留局部搜索。

| 独立测试来源 | local / global / dynamic 的平均 IoU | local / global / dynamic 全局搜索次数 |
| --- | ---: | ---: |
| Dudek | 0.850753 / 0.850753 / 0.850753 | 0 / 159 / 0 |
| Faceocc2 | 0.841236 / 0.841236 / 0.841236 | 0 / 159 / 0 |

所有策略在这两个片段上给出完全相同的轨迹。全局搜索没有带来额外质量，
动态策略也没有超过更便宜的固定 local；这项负结果完整保留。
各次实际解码、控制、总 wall 时间在 RESULT 中分列。独立测试来源数是 2，
不是 318 个评价帧。算法是模板跟踪，不是语义视频理解或神经视频生成。

## 核验和复现

72 个 test 转录结果、24 个 fit 转录结果及 6 个视频评价结果均独立重算。
定向词编辑距离和模板搜索测试通过。`RAW_EVIDENCE.tar.gz` 包含原失败、
原视频运行、恢复后的全部转录与控制记录、源注释及 manifest，关闭归档后
逐项复核 291 个 member；SHA-256：
`42d3936bfd9d52225d9bc564fa31341b7c37b0da1b333e2a2d9bd43e11966686`。
大型公共模型及原始视频/语音以固定来源和哈希记录，不重复加入 Git 证据包。

```bash
python -m experiments.multimodal_output_portfolio.repair_20261026.natural.fetch --output /tmp/hepta-natural-assets
python -m experiments.multimodal_output_portfolio.repair_20261026.natural.run --assets /tmp/hepta-natural-assets --output /tmp/hepta-natural-new-run
python -m unittest experiments.multimodal_output_portfolio.repair_20261026.natural.test_natural -v
```

运行依赖 numpy、scipy、Pillow、faster-whisper 1.2.1、PyAV 16.1.0、
ctranslate2 4.8.4，以及 ffmpeg/ffprobe。`recover_speech.py` 仅允许重现本次
已识别的依赖故障恢复，不是重新选择测试样本或修改实验的入口。
