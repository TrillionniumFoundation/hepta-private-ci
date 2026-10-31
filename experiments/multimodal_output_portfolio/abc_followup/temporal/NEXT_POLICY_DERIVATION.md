# 下一步草案：公开状态下的语义不变查询守卫

**状态：严格的条件推导与小型纯函数检查，尚未成为本轮 final 候选，也没有真实性能结果。**

这一方向在本轮 768 个 final 请求仍在生成、任何 final 质量结果尚未读取时提出。
本轮已冻结的 fixed10、initial-only、cue-only feedback、来源、价格、主检验及执行顺序均不变。
新增的 `invariance_guard.py` 和 `invariance_tests.py` 不在本轮 final 的执行 source pins 中，
也没有被 `Policy`、`run.py` 或其他实际生成入口调用。这里的单元检查不计作新任务、真实音频请求或独立 N。

## 1. 直接使用实际公开融合规则

考虑一个有 K 个类别的事实，公开 posterior 为 p，当前 winner 为 m。
下一次 cue 解码为类别 y 时，当前 `state.incorporate` 使用

\[
p_i'=\frac{p_i\ell_y(i)}{\sum_k p_k\ell_y(k)},\qquad
\ell_y(i)=\begin{cases}q&i=y,\\\beta&i\ne y,\end{cases}\qquad
\beta=\frac{1-q}{K-1}.
\]

这里的 q 必须是实现真正采用的有效质量，不能把源 owner 的 nominal 质量直接代入：

\[
q_{\mathrm{eff}}=0.85\times0.98+\frac{0.15}{K}.
\]

| 事实 | K | cue2 有效质量 q | 非匹配 likelihood β | 最大对手翻转 odds 阈值 R=q/β |
| --- | ---: | ---: | ---: | ---: |
| 数量 | 8 | 0.85175 | 0.0211785714286 | 40.2175379427 |
| 颜色 | 4 | 0.8705 | 0.0431666666667 | 20.1660231660 |
| 方向 | 4 | 0.8705 | 0.0431666666667 | 20.1660231660 |

表格按十进制显示；实际函数按与现有融合相同的浮点表达式计算 q。
这是一条公开、预定的融合算子，不是已经校准为真实任务概率的 posterior。
以下推导只需要算子本身，不需要它在统计意义上完全正确。

## 2. 保持 winner 的严格充分条件

当前 q≥1/K，所以 R≥1。对任一竞争类别 j≠m，最不利的下一解码是 y=j。
公共更新后的 odds 为

\[
\frac{p_m'}{p_j'}
=\frac{p_m}{p_j}\frac{1-q}{q(K-1)}
=\frac{p_m/p_j}{R}.
\]

因此，只要对所有竞争类别均有

\[
\frac{p_m}{p_j}>R
\quad\Longleftrightarrow\quad
p_m\frac{1-q}{K-1}>p_jq,
\]

任何下一解码都不能改变 m。交叉乘积形式还避免了 p_j=0 时的除法问题。
若解码正好为 m，winner 更占优势；若解码为其他类别，逐一检查对应竞争者即可。
若某个事实没有被解码，便不施加 likelihood；精确算术下原 posterior 保持不变。
实际实现仍执行 normalization，因此 missing 也进入数值枚举检查。

严格不等式排除了依赖 tie-break 的证明。若将来改成 q<1/K 的反信息算子，
最不利分支会改变，不能照抄当前 R 阈值；需要重新推导，例如同时考虑 R 与 1/R。
当前实验的 cue2 不属于这种情况。

这没有访问真实未来 cue。它同时考虑**所有可能的解码类别和 missing**，
不是先看到实际未来结果后再挑一条最优路径的 oracle。

## 3. 为什么必须检查三个事实以及固定后续路线

本草案的参考是固定路线 10：gate0 获取 cue2，gate1 不获取 cue3。
守卫候选只在 gate0 决定是否将它改成 00；gate1 必须恒为 commit，
也不额外识别已经提交的 prefix。

从**同一个已经取得 mandatory cue1 的公开 gate0 Frame** 出发，
数量、颜色、方向三个事实都满足不变条件时，获取任何 cue2 都不能改变三个 winner。
`chunk_text` 的第一个 chunk 仅由数量、颜色与模板决定；第二个 chunk 由方向与模板决定。
所以，两条路线的两个意图文本 chunk 完全相同。中性前缀已经属于共同历史。

只检查第一个 chunk 的数量／颜色是不够的：cue2 还可能改变稍后才输出的方向。
检查全部三个事实，才覆盖这条固定后续路线的延迟语义影响。

守卫没有通过时，保留路线 10。守卫通过时，posterior 的数值、confidence、
observations 长度和 first_action 仍会不同，不能称完整 state 相同。
如果后续 gate1 再根据这些量自适应选择动作，以上两-chunk 论证不再自动成立；
必须另行证明后续动作与输出也不变。

## 4. 数值实现：枚举实际算子，保守处理 ties

[invariance_guard.py](invariance_guard.py) 提供纯函数 `public_fixed10_guard(frame)`。
它不接收 owner、目标事实、真实未来观察、分数、WAV 或路径；输入必须是当前 pipeline
中 mandatory cue1 之后、任何可选动作之前的 detached gate0 Frame。

每个事实分别枚举 K 个解码类别和一个 missing。当前融合按事实独立更新，
所以只需 9+5+5=19 次一维公开更新检查，而不是向环境请求 225 个真实 cue。
每次严格复用当前 `likelihood`、乘法、normalization 与 NumPy argmax 的算术次序。
任何 winner 改变，或任何更新产生非唯一最大项，均保守保留路线 10。
后者甚至会拒绝当前 NumPy tie-break 恰好保持旧 winner 的情况。

程序没有用四舍五入后的表格阈值做提前通过判断。这样可以避免“理论阈值通过，
实际浮点 argmax 却因边界舍入改变”的误用。该有限检查依赖当前事实划分、融合实现、
数值类型和固定后续路线；将来集成时仍应绑定这些源码和环境身份。
它不是对任意未来平台的机器证明，也不是完整运行时状态或物理媒体的等价证书。

[invariance_tests.py](invariance_tests.py) 实际调用当前 `incorporate` 和 `chunk_text`：

- 在两种模板上分别枚举全部 225 种三事实解码组合，包括 missing，检查认证后的两个 chunk 相同。
- 用冲突的公开历史验证守卫拒绝跳过，并找到实际融合会改变文本的反例。
- 检查阈值两侧、相邻浮点数、明确 tie 与不合法状态；没有替换融合函数或伪造文本等价结果。

执行命令：

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  /workspace/scratch/2b3c256bef7d/speech-env/bin/python -B -m \
  experiments.multimodal_output_portfolio.abc_followup.temporal.invariance_tests
```

本工作区使用其已有 speech-env Python 的绝对路径执行。4 项检查通过，
测试框架报告 0.042 秒。全部是人工构造的公开概率向量／类别更新；
没有加载 TTS、Vosk 或 Whisper，没有读取任何 final 记录，也没有产生真实语音性能证据。

## 5. 这条推导没有证明什么

**条件意图文本相同**与以下结论不同：

- 不同真实请求的 mandatory cue1 可能有不同的实际 ASR 观察，因此两次执行不一定从同一个 Frame 出发。
- 未证明实际 TTS 的 PCM、独立终端 ASR、最终 joint success 或跨模态任务效用完全相同。
- 意图内容可能在两条路线中同样错误；相对该公开融合基线的不变性不是绝对任务正确性保证。
- 守卫本身耗时，未触发时还会增加控制开销；减少操作数不自动证明实际 wall time、尾延迟或 priced CE 改善。
- 没有证明学得的反馈策略胜过该守卫，也没有证明它是整个动作族中的全局最优策略。

后续若要实际评价，应另行冻结策略、来源、所有强参考、同输出完整串行成本与独立评分，
如实处理不同真实请求的观察差异，并保留 guard 执行成本。不能复制基线媒体后把生成费用记成零，
也不能把本轮 final 的不利结果通过换策略覆盖。未另行注册前，这份草案不授权重用已打开结果作为新的确认性留出证据。

当前已完成的是公开模型中的推导、可执行纯守卫和边界检查。真实性能与经济收益仍未建立；
本轮 768 请求的原始候选、原始主检验和失败保留规则继续有效。
