# 多值收益与交付后数值反馈：独立有限机制实验

## 范围与冻结设计

这是从 `ab417dfc97aad4fd51e2ae77515936d6ef6464b7` 出发的新合成有限任务，
不改写原 V6、joint 确认、原生 owner 或既有准入结果。协议、种子、收益表、
成本、七个比较臂在运行前写入 `PROTOCOL.json`，执行前再次将协议和源码哈希
固定到 `evidence/FROZEN_REGISTRATION.json`。

任务有四个公开 cue、三个隐藏类别、四个语义输出动作。错误的严重度不同，
显式表达不确定性可取得部分收益；不同动作与传输故障还有不同成本。
这些是声明的任务效用单位，不是实测毫秒或能耗。实际 CPU、wall 时间另列。
第一份输出的损害不会因重发而被抹除。隐藏类别只交给 episode 完成后的评分器。

实际训练了 12 个 categorical posterior logits 和 2 个反馈策略参数，分别进行了
600 次 numpy 梯度更新，保存参数并重新加载，校验了前后哈希。训练 posterior
使用 4096 个合成样本；反馈策略使用 96 个真实落盘、读回并配对重发的样本。
输出采用确定性 text、PNG、PCM tone WAV、未压缩 AVI codec。音频不是自然语音，
视频只是移动标记；这些 codec 没有接受神经训练，不代表自然全模态生成能力。

## 执行结果

一次预定运行完成 256 个独立合成 case × 7 臂，即 1792 个 episode，实际产生
11248 个媒体文件。每个 episode 都完成了先交付、读回、持久化数值反馈，
再选择 stop 或 repair 的顺序。实际重新生成的内容再次读回；stop 保留已存在
输出。反馈是无需隐藏标签的交付一致性代理，绝不作为隐藏类别的新证据。

| 臂 | 平均净收益 | CE，γ=1.5 | 严重损失 `< -3` | 重发次数 |
| --- | ---: | ---: | ---: | ---: |
| mean + numeric | 0.448008 | -4.335841 | 7 | 79 |
| risk + numeric | 0.298125 | 0.183161 | 0 | 79 |
| risk + zero | 0.215156 | 0.112241 | 0 | 256 |
| risk + shuffled | -0.237031 | -3.112777 | 11 | 79 |
| risk + 完整同信息 history | 0.298125 | 0.183161 | 0 | 79 |
| risk + 固定总是重发 | 0.215156 | 0.112241 | 0 | 256 |
| risk + 固定停止 | -0.481250 | -3.336070 | 17 | 0 |

mean 按 cue 选择 `[0,1,2,3]`；risk 选择 `[3,3,2,3]`，因此这个多值任务
可以识别风险偏好的影响。risk 牺牲部分平均收益换取较小尾部损失。
与 mean 的配对 CE 差为 4.519001，预定 97.5% bootstrap 区间为
`[1.206287, 5.423048]`。这只是此合成分布、一次训练及有限样本的区间，
不是任意任务或训练种子的保证。

数值反馈使 177/256 个后续动作相对置零发生变化，平均净收益差为
0.082969，区间 `[0.075229, 0.090938]`。置零策略实际上与固定总是重发
逐 episode 等效；不能将二者当作两个独立证据。shuffled 保留完全相同的
数值边际分布，改变 104/256 个动作。

**同信息 history 强对照与 numeric 逐 episode 完全相同，收益差及区间均为
0。**因此结果证明这条数值计算路径能在交付后改变行为并避免无用重发，
没有证明它拥有超越普通历史控制的独特 NDU 收益。

## 核验与证据

- 实际观察到六种语义收益和 23 种净收益，保留了全部失败、尾部与负比较。
- 原二值等成本任务的 mean/risk 等价负对照通过。
- 复用 `advance_20261026/control/bellman.py`；在每个 cue 的完整可观测树上
  与 32 种非预知策略穷举相符。这个结论仅针对提供的合成转移律。
- 4 项定向测试通过，包括 ffprobe/ffmpeg 对真实 AVI 的独立解码、跨 codec
  故障读回、私有目标接口拒收和参数更新。
- 独立重新计算 1792 个私有评分，重新哈希全部评价媒体；256 个 case 的
  所有 risk 臂接收完全相同的第一份公开观察。
- `evidence/RAW_EVIDENCE.tar.gz` 保存完整运行数据、媒体、每步记录、参数与
  manifest；16632 个 archive member 在关闭归档后逐项重算哈希。
  归档 SHA-256 为 `10f45e51bccd599cbdbd93041d4fbaae9f9713ce681282d07bcdfea8b56b6c8a`。

```bash
python -m unittest experiments.multimodal_output_portfolio.repair_20261026.risk_feedback.test_mechanism -v
python -m experiments.multimodal_output_portfolio.repair_20261026.risk_feedback.run --output /tmp/hepta-risk-feedback-new-run
```

需要 numpy、Pillow，定向独立视频验证还需要 ffmpeg/ffprobe。版本和二进制
身份见 `evidence/ENVIRONMENT.json`。本次运行约 4.33 秒 wall、4.61 秒 CPU，
不包含依赖安装或独立核验。旧 checkpoint 重现、自然任务收益、原生 owner
接线、完整神经生成训练和全局最优性仍不由本实验关闭；`all_blockers_closed=false`。
