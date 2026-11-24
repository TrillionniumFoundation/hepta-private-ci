# Hepta Neuron 权重级研究审计与 QVI 原方法复跑

审计日期：2026-11-24。范围是实际读取的研究源码、原结果和新完成的 CPU 复跑；Pocket4 正在运行的交易模型状态由主代理另行核验。

## 已读取的精确来源

- hepta-private-ci #6987：draft/open，未合并，head `bceb3d93c49442341a10afd751384182b46081e3`，base `1c5125c5462a45a1b91170ebad82f348e282df92`。
- #6995：draft/open，未合并，head `07c8994f2402a58f6b59eb648c801fc40c6e2b96`。它是 ZIP 依赖资格叠加，不是新的权重能力实验；PR 描述保留 14 个 cargo-deny 告警。
- 最新 HCSN 研究索引：`evidence/hcsn-qualification-blocker-audit-20261123` 的 `qualification/hcsn_ci_readbacks/integrated-blockers-20261123/CURRENT_ZH.md` 与 `HCSN_SCOPE_ZH.md`。
- 本轮原方法复跑科学源固定为 `610f91087b598656f7f3913e600c705b95bf071f`；比较协议 SHA-256 `6df773f53cf63158598a3b307352234eafad5dcfdb694eb797c01326eafceb68`。13 份源/数据文件的本地 Git blob 散列均与 GitHub 原件相同，映射见 `source_provenance.json`。

## 三类模型必须分别解释

1. Pocket4 交易 scorer/adapter 是实际交易模型；不能将下面两个研究模型的结果转移到它。
2. Renewal-policy 五 checkpoint（fit 11/23/37/53/71）：85→tanh(48)→4，4324 网络参数和8个固定物理参数。输入为43公共特征、33 latent mass、9 forecast bank；network.w1 [48,85]、b1 [48]、w2 [4,48]、b2 [4]。前三输出是 WAIT/READ/REPAIR，第四是 Belief logit。SUBMIT_0/1 分数由同一 sigmoid 输出生成 `1-2p` 和 `2p-1`，因此没有独立 Call/Put 两头。任务是固定deadline的符号预测，非 First-Passage 目标；latent CTMC 具有 endogenous renewal，REPAIR只修传感器，不重置 latent。
3. 连续 HCSN/QVI 两细胞诊断：每个cell有 mu、sigma、discount、log_reset、refractory、gain、maintenance、spike_cost 八参数；传播支持 signed mark 和 reset_map。这里存在可直接利用的物理坐标和边界方程，但没有借此证明交易scorer拥有同样参数。

NDU 是上述任务中实际净效用和资源代价的决策目标/采用准则。读取的这些checkpoint中没有一个可随意称作“独立NDU价值神经头”的额外张量。

## 既有端到端证据

### Q 的行动级机会很大，固定权重族的收益未成立

在同目标、同196维head、同预算的 `wsp_20261122_next` 研究中，Q_ORACLE 回收 GEN 96.38%的机会缺口，Belief-only仅0.60%；这定位了评分关系，没有定位唯一权重故障。DIRECT 每fit重复相同16提案8轮，640槽并非640独立编辑，所有候选变化为零。BP 在新SELECT平均增加0.020014，但五fit全部违背预设逐world损失0.05门，最坏−0.599948，所以两家最终KEEP。

`wsp_oracle_distill_20261122` 在相同统计量、同ridge目标/半径比较精确谱解与128步PGD。直接法训练目标从0.026733降到0.017136，但IID净效用−0.037194、OOD−0.051070。梯度同样退化。更好拟合oracle scores不保证hard-policy效用改善。

#6987 的单标量共同位移三个 continuation bias，GEN五fit全提高；IID效用−0.005535，OOD+0.003502，最坏OOD−0.381346，仍KEEP。同标量Adam为IID+0.002906/OOD−0.014994；full-network BP为−0.018646/−0.026825。后两种训练目标/支持不同，不是完整同成本因果速度比较。

已知有限law下 action-veto 另有实效：complete Vπ veto直接提案80world改善22、不退化；best first action Qπ 改善60、不退化。费用翻倍后部分策略又退化，说明 law/成本错误不能用神经权重编辑补偿性宣称已修好。

矩形不确定性规则下42/80新任务可接受task-specific三bias编辑，38保留；这依赖该任务完整图和给定不确定性集合。只用initial representation转移编辑的封存方法在新80world改善15、退化15、相同50，均值−0.00391663；zero-dev-loss selector仍KEEP。

### 人工故障修复与自然能力提升分开

盲测提供五匿名网络、32 trusted reference logits，隐藏单元已置换/变号。单次agent程序修复4个人工损坏模型并保留clean模型，15个scalar变化恢复5179个heldout state decisions。一个hidden输入符号故障由四个outgoing weights补偿，恰说明功能修复不识别唯一物理根因。这是有可信参照的故障恢复证据，不是从任意大网络裸权重自动发现自然能力缺陷。

### 最新真实任务结果继续指向表示、成本和保持限制

最新HCSN索引记录，12个新来源、48窗口的前瞻试验中，QVI相对固定/普通可学习阈值效用仅+0.00278，单侧p=.75；未达到来源保持门。既有27个正确动作的19维读出设计矩阵精确满秩19，若要求这些连续分数逐点完全不变，可用线性编辑方向只有零向量。这应先作可行性诊断，不能靠重复训练越过数学约束。

## 本轮实际复跑：解析两坐标编辑

原目标为A的内生边界降低0.01，保持A初态0.72时B的49个输出。可改A放电成本K与B输入偏置c，其他不动。QVI残量F(b;theta)对K的系数严格为1，因此在合法内点根范围内：

`K_new = K_old - F(b_target; theta_old)`。

再将A发往B的线性输入变化从c扣除。数值为ΔK=0.019345554018888933、Δc=0.009195251723316866。原求根、有限续生传播和验证仍执行，省去的是外层参数优化。

运行环境：Python3.12.14，隔离安装Torch2.10.0+cpu，单CPU线程。沿原脚本一次预热和五次交替计时；原科学协议未改。

| 方法 | 边界误差 | 锚点49输出最大变化 | 反传闭包次数 | 完整调用中位秒 |
|---|---:|---:|---:|---:|
| KEEP | .01 | 0 | 0 | .074264405 |
| 结构化直接编辑 | 2.22e−16 | 2.78e−16 | 0 | .079543336 |
| 同初值联合L-BFGS | 5.12e−11 | 1.67e−10 | 6 | .157437582 |

完整进程墙钟4.984132秒，child user4.516984秒，system.445607秒，peak RSS300480KiB。直接法与BP完整调用比值约0.5052；它是这个给定目标的CPU诊断，不是模型训练/交易收益加速比。下载/安装和工具交互成本另行发生，不包括在科学计时中。

新结果SHA-256：`cd59a3e8094663c115eebcf676581d25ad1e45d6caf2f472941fda5f84403253`。独立无Torch Lambert-W和括区求根复算原三臂/12受方输入，最大误差3.33e−16。

## 本轮额外消融：单锚点保持的界限

这是对同一封存候选的事后机制诊断，不当作新的泛化确认。固定21初态（.56至1.4网格加原锚点/原额外初态），八臂、每点49输出。没有优化、选模型或调目标。

| 臂 | 边界目标误差 | 锚点输出最大变化 | 21点最大输出变化 |
|---|---:|---:|---:|
| DIRECT | 2.22e−16 | 2.78e−16 | .007229361 |
| BP | 5.12e−11 | 1.67e−10 | .007229361 |
| 仅成本 | 2.22e−16 | .011640374 | .011779424 |
| 仅偏置 | .01 | .011541817 | .012114744 |
| 半剂量 | .004981019 | .000015441 | .003596512 |
| 反向 | .020156185 | .000112944 | .007079983 |
| 同范数随机方向 | .002133424 | .028420158 | .028975179 |

只有联合DIRECT/BP通过原目标和锚点门，所有非零臂都不满足21点保持。独立标量路径核验168组source boundary、receiver start和receiver末端不应期概率，最大误差5.00e−16；49项完整数组来自原Torch实现。

全域输入保持还有解析反例：源初态x→∞时，有限期限内触及概率趋零，所以B输入变化趋于Δc+0.31Δb=0.006095251723316795，而非零。单个常数bias无法抵消全部初态的非线性触及信号变化。21点完整输出反例已经实测。

第一次附加消融在全部forward后因NumPy bool_不能JSON序列化而退出；失败源和记录保留在`replay_20261124/ablation`。仅转成Python bool后，以相同候选、固定网格重做并保存`ablation_attempt002`，不改原三臂复跑结果。

## 可落地的下一步与最小Rust接口

先做结构判定和可行性，避免把所有失败当作可调权重问题。每个edit plan必须绑定模型全文hash、来源图/张量语义、目标、保持集合、dtype/算术顺序和成本边界。优先对已证明的条件线性/解析逆映射产生候选；调用方传入目标不自动等于真实任务目标。

QVI内核最小接口可返回成本候选和来源残量，不需要Tensor：输入八个有限F64参数、目标b，使用原稳定kappa和原残量；检查positive sigma/discount/gain/spike_cost、正不应期、reset−b在原内点范围，计算K_new，重新解根核对。接收方bias的验证必须绑定具体anchor及完整传播law。多anchor无法同时满足时返回KEEP或可行性失败，不能自动扩大参数范围/改变目标。

完整任务比较应划分：TRAIN/GEN仅构造与局部识别；DEV仅一次选择；candidate/hash/协议封存；FINAL新来源或未来时间一次评价；最终keep/adopt结果与失败候选都保留。至少比较KEEP、结构直接法、相同支持/目标的梯度法、成本/偏置单独恢复、反向/半量/同范数控制；用每来源/每checkpoint统计，不把大量同源状态当独立样本。计入读取、候选搜索、验证、oracle/law准备和部署运行成本。

## 主要链接

- https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6987
- https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6995
- https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bceb3d93c49442341a10afd751384182b46081e3/tools/hcsn/wsp_stop_value_and_blind_20261122/README.md
- https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bceb3d93c49442341a10afd751384182b46081e3/tools/hcsn/wsp_20261122_next/RESULT_INTERPRETATION.md
- https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bceb3d93c49442341a10afd751384182b46081e3/tools/hcsn/wsp_oracle_distill_20261122/README.md
- https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bceb3d93c49442341a10afd751384182b46081e3/tools/hcsn/wsp_20261122_next/semantic/joint_deploy.py
- https://github.com/TrillionniumFoundation/hepta-private-ci/blob/evidence/hcsn-qualification-blocker-audit-20261123/qualification/hcsn_ci_readbacks/qvi-conditional-edit-20261123/README_ZH.md
- https://github.com/TrillionniumFoundation/hepta-private-ci/blob/evidence/hcsn-qualification-blocker-audit-20261123/qualification/hcsn_ci_readbacks/integrated-blockers-20261123/CURRENT_ZH.md
