# 已保存 TRAIN 证据的机制分解

只读取 d1 的全 TRAIN 均值、既有 decoder NPZ 与源清单。没有重建输入，
没有 encoder/head 请求 forward、训练、抽样、validation 或正式数据。
闭合的参数delta/测试身份审计不再重做。代码、全部数值在 analyze.py 与
aggregate-mechanism.json；所有192物理源、3072行原评分均纳入，没有挑子集。

## 能定位的事件，不能定位的请求

NPZ只含模型和Adam；train-manifest只含哈希/重建profile，没有输入、label、
source ID逐行映射。result.json 的 TRAIN score 只存六个全局均值；service
用 observe=False，per_row为空，仅保留96行成本和第一条抽样输出。
没有逐行p/q、各头正确率/argmax margin、逐行reward/Z、greedy转移名单。
所以**不能指出损失集中在哪个物理源/指令/某一个头，也不能恢复历史逐行
概率变化、severity排序或条件entropic值**。可另行做带新推断身份的TRAIN
重算，但本轮没有做，不能把它冒充原来存下来的数组。

可以从保存均值识别一些完整的输出事件概率。记U=raw utility、J=joint
success、C=consistency、M=pixel MSE。由原效用公式且quality clip未触发：

`S = [U-.3J-.1(1-4M)+.35(1-C)]/.3 = E[p_text,true + q_image,true]`

则共同正确=J，仅一头正确=S−2J，两个都错=1−S+J，错而一致=C−J。
对三个保存decoder穷举全部12×12×12固定score support：解码类别都为
0..11，最大像素距离<.121631<.25；负reward恰好是“两个都错且不一致”。
因此该负尾质量=1−S+2J−C。这里只重算了固定十二码decoder的scoring
support，不是请求预测，也没换评分器；head边缘概率仍只能识别**和**。

## 同sampler的最终N−A，全部seed

| sampler | seed | Δ共同正确 | Δ仅一头正确 | Δ错而一致 | Δ负reward尾质量 | greedy净增加错误行 |
|---|---:|---:|---:|---:|---:|---:|
| IID | 11 | +.003097535 | −.003895060 | +.000821828 | −.000024303 | +5 |
| IID | 23 | +.005636589 | −.005493294 | −.000103895 | −.000039399 | +1 |
| IID | 47 | +.002976014 | −.003727937 | +.000769939 | −.000018016 | +5 |
| Stratified | 11 | +.003103093 | −.003174077 | +.000093701 | −.000022716 | +1 |
| Stratified | 23 | +.004861956 | −.005251688 | +.000418207 | −.000028475 | +2 |
| Stratified | 47 | +.004457864 | −.004545036 | +.000113487 | −.000026315 | −1 |

分层N在三个seed的“两个都错”质量还分别增加.000070985/.000389732/
.000087172。可见共同正确和平均两头真类概率和提高，同时少量错误变得更
一致；不能把一致性提高等同全部内容正确。IID seed23是这个代价的反例，
其错而一致/两个都错均下降，不能隐去或推广为所有seed同机制。

这不是逐请求“从一错变两错”的转移矩阵，因同一行的A/N联合信息未存。
例如stratified seed11是11→12个greedy错误，但实际变更status的行数只可
界为[1,23]，绝不等于已找到那“一行”。相对endpointwise best A，分层N
净增加greedy错误为2/2/1行，三者仍全负；其来源、margin、严重度未记录。

## 均值收益来自什么，不能归因什么

精确均值恒等分解为 `ΔU=.3ΔS+.3ΔJ−.4ΔM+.35ΔC`。

| Stratified seed | 两头边缘和项 | joint bonus项 | pixel质量项 | 不一致惩罚项 | 总ΔU |
|---|---:|---:|---:|---:|---:|
| 11 | .000909633 | .000930928 | .000048247 | .001118878 | .003007685 |
| 23 | .001341667 | .001458587 | .000061455 | .001848057 | .004709766 |
| 47 | .001311208 | .001337359 | .000057317 | .001599973 | .004305857 |

这是评分恒等分解，非因果效应分解。主要是边缘正确概率和、joint bonus与
减少不一致；decoder完全相同，pixel质量小收益来自抽到的image码分布。
哪个头单独贡献多少不能由S、J、C、M唯一反解，JSON仅给距离支持下的
宽泛marginal界，不能挑某个界当实际头归因。

另一个可以严格核对的是**固定reward的非单调性**：对每个目标y与错误码k，
`R(y,k,k)−R(y,y,k)=.05`，全部132组合/每decoder都成立。观察到的三个
decoder还有 `R(y,k,k)−R(y,k,y)` 在[.001367,.042072]内均为正。
即错而一致比这两类“仅一头正确”更高分；来源是原.35不一致惩罚大于
.3单头正确奖励。reward_geometry.py/json穷举全support，不是新请求或
改变utility。这给出与wrong-agreement上升相容的结构性权衡，**A也受同一
偏好影响，不能因此证明N的因果路径或那些greedy错误的位置**。
共同正确J和真类概率和S仍提高，不能把全部N增益描述成只在钻一致性分数。

固定support中的负reward约[−.298653,−.257943]。用其上下界与已识别尾质量，
负reward部分的均值改善最多占最终raw增益：IID三个seed .302%/.254%/.257%；
stratified .278%/.221%/.219%。因此“均值提升主要来自减少严重负reward”
不符合这些保存证据。该尾部的相对概率下降虽大，绝对质量很小。
它不排除风险梯度对训练路径有影响；缺少每请求Z，不能从无条件尾质量
算出平均CE_rho、倾斜tail梯度、CVaR或风险目标改善，更不能把跨请求mean
移进log来重建它们。

## 128步已有同方向现象，不能只怪最后一步

同128步/同draw prefix时，N-stratified相对A的错而一致增量已经为
.000236987/.001137313/.001509266；greedy净增加错误0/12/9行。
最终分别为+1/+2/−1行，继续训练总体减少了错误，且与A的差距往往缩小。
这些并不支持把现象单独归因为末步抖动或简单提前停在128步；不据此
选择另一个有利checkpoint。它们也不证明wrong-agreement质量就是greedy
损失所在的那些行，缺少逐行映射仍是明确边界。

## 一个最小、可证伪的训练候选（未用于TRAIN）

提出**固定初始reference的CE-anchor control variate**，A/N同时使用，仍
固定rho1.5、anchor.2、同原效用。动机只是：N更强的效用梯度尺度下出现
错而一致代价，可检验标签anchor的随机梯度噪声是否加重该代价；当前
证据没有证明这个因果链，不改CE系数或惩罚wrong-agreement的评分。

设g_B(theta)为原完整小批量梯度，h_B(theta0)为同idx/view/importance weights
在共享base theta0的**未乘.2** CE梯度，H(theta0)为全TRAIN/两视图均值。
用 `g'_B=g_B+.2*(H−h_B)`。条件于当前theta，其pre-clip期望仍是原完整
目标梯度。reference只有共同base一个，不刷新、不扫窗口/权重。Norm5
clipping和Adam照旧；不把pre-clip无偏说成Adam更新无偏。
control-variate背景可参见[Johnson和Zhang的SVRG原文](https://papers.nips.cc/paper/4937-accelerating-stochastic-gradient-descent-using-predictive-variance-reduction)。
这里仅校正CE anchor且固定一个reference，不照搬其强凸收敛结论，也不
声称该论文证明本神经生成器或本候选有效。

仅准备了纯梯度校正函数anchor_cv.py和四项手造代数测试，没有缓存reference
或对实际模型应用。完整reference统计、基准CE小批量pullback、缓存、原生
dispatch和校正运算都必须真实计费；A同获此方法。每步额外校正本身为
3E scalar ops及3E finite checks，E=7288；reference计算远大于这小项，不能
漏算。可缓存base每行hidden/dhidden/两个CE logit梯度约4.3MB/seed，避免
储存逐行7288维全梯度；所有source/view均包含，不能只缓存难例或好例。

它可能失败：reference随theta移动变旧，或原anchor/utility噪声负相关，
control variate会**增加总梯度方差**；手造测试明确包含这个反例，而不保证
降方差。先做下述单次固定TRAIN只读诊断；如果N任何seed/同sampler终态
总pre-clip方差不降，或数值参考均值不守原目标，就不进入新训练，不挑
较好source/seed重说通过。若以后另行批准一次TRAIN对照，保留全部源与seed，
要求N相对有效A的raw/joint/完整净值收益不靠削弱A，且wrong-agreement和
greedy不恶化；否则否定此候选，不扫系数或改评分器追通过。
reference全均值的独立dense核对预置rtol=1e-10、atol=1e-12，不因结果调松。
若另批新TRAIN，用原器/CV×A/N四组同结构同帽配对，不能把旧d1的有利
波次当作新时序对照；任何NDU独有增益还须看完整交互而非只看N单组提升。
CV不改变上述reward排序；若代价是稳定目标下的权衡而非优化噪声，它不应
被期望修复该权衡。这本身是候选可能失败的原因，不能转而偷偷改评分系数。

## 小型TRAIN方差/时序诊断提案，不执行

唯一拟议只读run：从原profile重建一次**原TRAIN**并逐hash校验，固定现存
final十二模型/三个base权重；不训练、不构造validation/test，不调用旧formal。
所有3072行/192源都记录p/q、greedy margins、源/目标/指令映射、逐请求
Z和原reward分解，并标记为新重算推断，不能回填旧日志。一次固定32个
新诊断minibatch，比较原梯度与CV的配对方差；同source与view全集计算
reference，所需额外梯度和内存均计费。不因方差不好增加batch/seed。

另四个固定Williams波次，48个四源cohort、所有12模型真实PNG服务；记录
每行输出码/PNG哈希与native/encode/JSON/资源成本，不挑最快波。上限
**30物理CPU秒、8B声明model/service units**，A/N各同15秒/4B且共同准备
全归因，留存≤64MiB；原库按已有hash复用、不重编译以刷时间。不合帽
保留partial后结束这一次诊断，不自动重跑。该规模只是提案，未执行。

它能估现有固定模型下的源/cohort与四波噪声，**不能**估32个随机三-tuple
完整预算block之间的方差，更不能把它升级为正式确认。无需等待大确认
才能继续源代码或已存证据研究；这个新的重算诊断仍需父会话确定执行范围。
