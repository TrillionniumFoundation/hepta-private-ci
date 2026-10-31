# ABC4：真实文字／语音的两次信息获取反馈

本报告是已执行、已封闭的完整结果。冻结方法详见 [METHOD.md](METHOD.md)。

## 结论

完整 768 个串行请求、同批实际 WAV 的独立 Whisper 评分和冻结统计均已完成，执行/策略 replay 检查通过。**三个预登记主门槛均未通过**；没有追加样本或修改候选、价格、成功率边际、观察器或统计规则。

| 预登记比较 | 估计与名义 98.3333% 区间 | 门槛结果 |
| --- | ---: | --- |
| priced CE：反馈 − fixed10 | -0.016334 [-0.036160, +0.002492] | 未通过 |
| priced CE：反馈 − initial-only | +0.012178 [-0.009887, +0.034586] | 未通过 |
| exact success：反馈 − fixed10，百分点 | -4.296875 [-8.203125, -0.781250] | 未通过 |

反馈平均 online wall 比 fixed10 少 0.187572 秒，其描述性 95% 来源区间为 [-0.268430, -0.109857] 秒。反馈的 P95 为 2.709459 秒，fixed10 为 2.460995 秒。在研究价格 lambda=0.05 下，平均时间节省没有建立足以覆盖质量差异的风险效用增量；成功率保留区间整个低于零。

三策略的物理完成率、语义可解析完成率和跨模态事实一致性都是 100%，任务 exact success 仍不同。这些指标分别刻画完成、一致与正确，不能互相替代。完整数值和身份见 [RESULTS.json](RESULTS.json)，完整阶段成本见 [COSTS.json](COSTS.json)。

## 这轮改变了什么

上一轮真实文字／语音原型没有建立学得反馈超过强固定策略的增量。本轮先运行实际发音／冗余控制开发试验，发现 Vosk 与独立 Whisper 对动作的偏好发生反转，保留该负结果，随后将新动作改为是否支付真实成本获取额外语音证据。

每个请求先提交中性前缀，再取得并识别第一段必需语音 cue。第一个决策 gate 可以额外取得 cue 2，再提交数量／颜色。第二个 gate 可以额外取得 cue 3，再提交方向。已提交文本和 PCM 均不可改写。先取得的信息经同一共享状态影响多个后续事实；输入语音 cue 是源 owner 预采样后按动作释放的受控证据，并非外界实时传感器。

四条常量 query 序列 00、01、10、11，以及初值策略和反馈策略，都拥有相同的语义融合和内容更新权利。正式对照使用 selection 实际执行后最强的常量路线。初值策略能从同样四条路线中选择，但必须在第一段语音 cue 释放前决定。反馈分别在两个实际 gate 决定。full 反馈在第二 gate 前识别刚提交的真实语音，cue-only 反馈完全省略该操作及所有相关特征。

此比较检验自适应信息获取的整体质量／成本增量。没有新做同成本 semantic-clamp 消融，因此不将整体差异独立归因于共享语义机制本身。

## 独立来源、状态与信息边界

来源为 nine 到 sixteen 的数量、四种颜色、四个方向的 128 个不同事实组合。旧轮次使用 one 到 eight；本轮没有把旧测试重命名为新测试。角色为 development 8、fit 32、selection 16、qualification 8、evaluation 64。每个 evaluation 来源具有两模板、两组预定带噪 cue 情景，以及三种所选策略，合计 768 请求。来源聚类保留全部模板、情景和策略。

公开状态含 82 个特征，包括初值词类别、共享后验、已经观察到的语音类别及不确定性／历史摘要。策略仅收到 detached Frame，不收到 owner、来源 ID、目标事实、RNG、未释放 cue 或事后结果。cue-only 在全部特征计算前将 previous_audio_fact 置为空，衍生 missing／一致性特征也无法保留该 probe。elapsed 是成本记录而不是策略输入。

每个可选动作先写入并 fsync 决策，随后才允许 cue WAV 实际生成、持久化和 Vosk 识别。没有直接返回隐藏任务真值，没有用 sleep 构造动作代价。所有 final 生成完全关闭后，Whisper 才观察同一批输出 WAV。

## 实际条件值训练

固定 gamma=2、研究价格 lambda=0.05。最终净效用为 U-lambda*T，T 是同一实际输出的完整 online wall time；效用 U=.6*(text fact accuracy+audio fact accuracy)/2+.2*nonmissing agreement+.2*joint exact success。

训练与 selection 的实际音频测量来自 Vosk，记为 U_fit；final 主测量来自独立 Whisper，记为 U_eval。两者使用同形效用公式，但不是同一个已知质量标签。本实验拟合 Vosk 代理条件值，再检验向独立测量的迁移，没有证明拟合的 Z 已等于 U_eval 的真实条件指数期望。独立指测量模型和执行角色分离，不是声学模型训练语料完全独立的保证，也没有替代人工评听。

Q1 的训练目标是 exp[-2*(U_fit-lambda*(T-tau1))]。在按来源持出的每个 fold 上，三个 Q1 种子的正值先取平均，再按动作取最小。Q2 的共同目标为 exp[2*lambda*(tau1-tau0)] 乘上述 continuation。所有 Q2 种子共用该目标，与部署时 ensemble 决策顺序一致。没有使用 mean(min per seed) 代替 min(mean ensemble)。

Vosk 置信度在相同 PCM 的重放之间也略有变化，因此不同 route 的独立执行不被当作完全相同状态。每一条真实历史只为已经执行的动作提供标签，其他动作 mask。source fold 把一个事实的所有 route、模板和情景放在一起。OOF 模型与全部 fit 来源上的 refit 模型仍不同，不能据此声称均匀 Bellman 误差界或全局最优。

full 与 cue-only 各为三个种子的两 head ensemble，每 seed 两个 head 共 5,444 参数。initial-only 每 seed 5,572 参数。三个种子在部署时形成一个策略，不能增加 final 独立样本量。cue-only 的训练成本用实测 prefix probe 时间做组件扣除；selection 和 final 都实际省略该操作并重新计时。

## 开发失败记录与 observer qualification

发音 pilot：8 个 development 事实、3 模板、3 rendition，72 个实际 WAV。compact 的 Vosk/Whisper exact 为 20/24 与 24/24；explicit 为 24/24 与 21/24；redundant 为 22/24 与 20/24。该负迁移结果没有删除，也没有把 Vosk 更高分当作独立质量提升。

VOI pilot：前 4 个 development 事实、2 模板、2 cue 情景、4 路线共 64 条实际路径。00/01/10/11 的 Whisper success 为 50%/50%/93.75%/93.75%。这是开发信号，不是 confirmatory 证据；优化 fixed 的开发成本仅为矩阵成本扣除实际 prefix probe 的估计。

qualification v3 在执行前发布。8 个独立 qualification 事实、2 模板的 16 个正确输出，Vosk 和 Whisper 的 fact/exact 均为 100%；16 个 wrong-number 输出的实际音频 false exact acceptance 为 0；16 个 silence 和 16 个 truncated-prefix 的实际音频 semantic completion 为 0。阈值是预登记点门槛，不是总体精度置信证书。v1/v2 在运行前发现 observer 控制定义和源码身份需要修正，未执行任何 qualification 请求；完整修订记录保留。

## Selection 与 final 结果

Selection 完成 448 请求，严格验证 16 来源×2模板×2情景×7策略的唯一 key、每策略 64 请求、index 和 row hash、策略 replay，并拒绝任何 Whisper 输入。固定候选与反馈变体各自按 Vosk priced CE 选择，结果为 fixed10 与 cue-only；没有使用 selection 结果 refit 模型。

| Selection 候选 | Vosk raw CE | Vosk priced CE | Vosk exact success | 平均 online wall 秒 |
| --- | ---: | ---: | ---: | ---: |
| fixed00 | 0.780683 | 0.716180 | 59.3750% | 1.313868 |
| fixed01 | 0.829775 | 0.723789 | 65.6250% | 2.133778 |
| fixed10 | 0.910952 | 0.804208 | 82.8125% | 2.152314 |
| fixed11 | 0.910952 | 0.761307 | 82.8125% | 3.029337 |
| initial-only | 0.873206 | 0.770693 | 76.5625% | 2.104369 |
| full feedback | 0.879887 | 0.763161 | 76.5625% | 2.361574 |
| cue-only feedback | 0.872413 | 0.788126 | 75.0000% | 1.699377 |

选中的反馈在 selection 上没有超过最强固定候选：priced CE 差 -0.016082。这个不利结果完整保留；没有修改 lambda、成功率边际、模型或候选集。Selection 负责选择预定候选，不充当最终独立 Whisper 确认。

| Final 策略 | raw CE | priced CE | exact success | 平均质量损失 | 输出 CVaR90 | 来源均值 CVaR90 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 所选 fixed10 | 0.933125 | 0.829192 | 88.6719% | 0.046094 | 0.407813 | 0.223437 |
| initial-only | 0.901116 | 0.800680 | 83.2031% | 0.069531 | 0.423438 | 0.239062 |
| cue-only feedback | 0.907043 | 0.812858 | 84.3750% | 0.064844 | 0.423438 | 0.270313 |

质量损失是 1−U_eval，未减去资源价格；CVaR90 是最坏 10% 的精确经验尾均值，边界样本按所占比例计入。来源均值尾部先在同一事实的四个模板／情景行内取均值，再计算尾均值。

| Final 策略 | online wall 均值秒 | P50 秒 | P95 秒 | CPU 均值秒 | gate0 query rate | gate1 query rate | 平均可选 query 数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 所选 fixed10 | 2.091748 | 2.070817 | 2.460995 | 2.079595 | 100.0000% | 0.0000% | 1.000000 |
| initial-only | 2.029916 | 2.058508 | 2.399828 | 2.017641 | 77.7344% | 14.4531% | 0.921875 |
| cue-only feedback | 1.904177 | 1.994462 | 2.709459 | 1.892200 | 55.8594% | 20.3125% | 0.761719 |

独立评分覆盖 768/768 请求、153 个独特的完整 WAV；615 次仅复用相同完整-WAV hash 的 target-free 转录。每次生成都实际执行，每个请求仍按自己的目标计算指标，统计单位保持 64 个事实来源。生成、评分、策略 replay 和完整 census 均无执行错误。

## 预登记统计与价格敏感性

三个主 gate：feedback 相对所选 fixed 的 priced CE 下界大于零；feedback 相对 initial-only 的 priced CE 下界大于零；feedback 相对 fixed 的 exact success 下界不小于零，零容忍边际。每项名义 98.3333% 双侧 percentile 区间，共三项 Bonferroni 家族。4,000 次 source-group bootstrap，保留一个事实的全部相关行。

价格网格 0、.025、.05、.1、.2 × 两参考的十比较，每项名义 99.5% 区间。参考固定在 .05 的 selection 结果，不因其他价格重新挑选。另给出 [0,.2] 的 41 点经验 break-even scan。价格未经外部用户资源价值校准，不把某个价格下的正结果称作普遍经济收益。

本次 strict success 区间没有退化；其整个区间低于零。有限来源 bootstrap、固定 pretrained voice、有限模板与近似 observer 均限制外推；不能将 768 请求、模板重放或三个 critic seeds 当作独立来源数。

### 冻结价格网格结果

| 价格／wall 秒 | 参考 | feedback 的 priced CE 差 | 名义家族 10 的 99.5% 区间 |
| ---: | --- | ---: | ---: |
| 0.000 | fixed | -0.026082 | [-0.051253, -0.004134] |
| 0.000 | initial | +0.005927 | [-0.019991, +0.033209] |
| 0.025 | fixed | -0.021086 | [-0.045407, +0.000869] |
| 0.025 | initial | +0.009140 | [-0.016859, +0.035744] |
| 0.050 | fixed | -0.016334 | [-0.040529, +0.006119] |
| 0.050 | initial | +0.012178 | [-0.013589, +0.038280] |
| 0.100 | fixed | -0.007569 | [-0.032014, +0.016807] |
| 0.100 | initial | +0.017713 | [-0.008361, +0.045345] |
| 0.200 | fixed | +0.006958 | [-0.021174, +0.038582] |
| 0.200 | initial | +0.026500 | [-0.006370, +0.058092] |

十个区间的下端均不为正；更高价格下的正点估计没有建立确认性的净收益。
预定 41 点扫描中，相对 fixed10 的经验点估计跨零位于 [0.145, 0.150]。这只描述本批样本的点估计，不是置信区间，也不是经外部校准的经济 break-even 证书。完整扫描保留在 RESULTS.json。


## 完整成本、身份和复现

全部阶段成本如下。开发 pilot 使用其已记录的内部计时，fit 数据列为两 worker 的全局墙钟和汇总 CPU，其余列为完整精确子进程成本。矩阵 wall 不等于 worker wall 总和；RSS 峰值分别列出，不加和。内部时钟与完整子进程成本是嵌套范围，不重复计入。

| 阶段 | Wall 秒 | CPU 秒 | 峰值 RSS（MiB） |
| --- | ---: | ---: | ---: |
| 发音开发 pilot | 128.767455 | 128.552108 | 未列出 |
| VOI 开发 pilot | 317.902966 | 316.701371 | 未列出 |
| Fit 数据 512 路径 | 1056.345882 | 2093.634433 | 分别 475.21/477.97 |
| Critic / initial ensemble fit | 10.422590 | 10.408702 | 54.94 |
| Observer qualification | 106.937746 | 106.689864 | 647.89 |
| Selection 448 请求 | 1432.772136 | 1426.985485 | 478.10 |
| Selection choice | 0.411070 | 0.408467 | 45.59 |
| Final registration | 1.600863 | 1.599035 | 150.89 |
| Final generation 768 请求 | 2349.711228 | 2339.657325 | 509.09 |
| 独立 Whisper scoring | 99.924960 | 99.748347 | 316.50 |
| 冻结 analysis | 3.009644 | 3.005580 | 290.25 |

仅 512 条真实训练路径收集加条件值拟合，核心训练 wall 阶段合计 1066.768472 秒、CPU 2104.043135 秒；开发、选择与资格验证另行列明，不能把 10 秒的神经拟合独称全部训练成本。

单请求 online clock 从 owner 构造开始，到最终 WAV 序列化和精确已提交片段读回结束，包含真实 cue 合成／持久化／识别、策略和输出提交。模型加载、terminal measurement、每案例容器目录建立与最终审计记录写入在该 clock 外，已纳入完整阶段成本。音频播放、外部网络交付和历史声学模型预训练不在本轮计时范围。P50/P95 是已封闭输出可用的生成时间，不是音频播放结束时间。

Final protocol 与 selected policy identity 在 commit `f6c29042d885bab12840196aab37aeb61f14e619` 于 2026-10-25 09:04:46.988Z 发布。Final 实际登记于 09:05:14.540995Z，随后执行。根据已登记时间加完整 wall 的近似，起初与 root 的 2-CPU repair evaluation 重叠约 108.252458 秒；之后另有 8.989925 秒的 native candidate collection 与 3.794168 秒的 native analysis。它们属于其他实验，不加入本表成本。全部请求、顺序和时钟保留，没有事后删除或修正。该元数据不是完整宿主利用率追踪，也不把共享宿主声称为隔离硬件。

最终报告保存源码／协议／selected model 身份、成本与聚合结果；原始 WAV、逐请求记录和模型参数不归档 GitHub。源码与 source manifest 让方法和训练计划可重建，但真实 wall time 是本机此次执行结果，不能由 hash 保证跨环境重复。

## 证据边界

本轮训练的是小型条件值策略；声学生成器固定，文本为有限任务模板。没有声称开放式文字生成器或声学基础模型训练、全模态模型完成、Merton/HJB 全局最优性、生产 native admission 或普遍经济价值。未通过的科学 gate 保留为未建立证据，不通过更改门槛或覆盖失败来关闭。

## 证据身份与验证入口

- [freeze-v3/evaluation_protocol.json](freeze-v3/evaluation_protocol.json)：final 发布前的假设、模型、来源、观察器和执行源码 pins。
- [POLICY_SELECTED_IDENTITY.json](POLICY_SELECTED_IDENTITY.json)：七候选 selection、完整 census 与所选 fixed10 / cue-only 身份。
- [POLICY_FIT_IDENTITY.json](POLICY_FIT_IDENTITY.json)、[QUALIFICATION.json](QUALIFICATION.json)、[DEVELOPMENT_SUMMARY.json](DEVELOPMENT_SUMMARY.json)：拟合、资格与两个开发 pilot。
- [RESULTS.json](RESULTS.json)、[COSTS.json](COSTS.json)：固定分析的必要聚合证据与完整精确过程成本；不含逐请求矩阵、WAV 或参数权重。
- [provenance](provenance/DATA_GENERATION_SOURCE_IDENTITY.json)：实际旧 fit-generator 源码及 AST 范围；其他源与修改记录同时保留。

Final protocol SHA-256：`b7ef440308a497448d02af1445582c8175a2acb0c3d87dd151092a17fc1a64a8`。

选定 policy SHA-256：`c9e26b1a984b247f06b74b27ff5118adc6cd0c229d339332d783c1e25d83db4d`。

闭合生成 index SHA-256：`5233f1b5058517f5a1b1344e3dcdcd1685efd6da327e31223d47865a0c0b302e`。

闭合独立 scores SHA-256：`fd122a488a38f0f4645cf2e506271f1c10b58bd26180ada4e45a95bb6b988834`。

原始固定 analysis SHA-256：`3ecaf546d95968ebd8b6509ffe447c86761912c7c891750186894111193abc10`。

原始分析的来源级数组留在本地；公开 RESULTS 省略它们，同时保留原始分析身份和全部主统计。CI 未作为门槛或等待条件。执行前的 6 项边界检查、完整 selection 身份检查，以及本次固定 analysis 的来源／策略完整 census 与 policy replay 均已完成。

## 已提出但未参与 final 的下一步

[NEXT_POLICY_DERIVATION.md](NEXT_POLICY_DERIVATION.md) 在 final 质量尚未读取时提出公开 posterior 的语义不变查询守卫，并附纯函数与真实 fusion 枚举检查。它只覆盖同一 gate0 history 下相对 fixed10 的两个意图文本 chunk；没有参加本轮 768 请求，未证明 PCM、独立 ASR、成功率、真实时间或经济收益。4 项纯检查不构成新的真实任务样本，不能替本轮三个未通过主门槛关闭收益证据。
