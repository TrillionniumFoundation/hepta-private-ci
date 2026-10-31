# R11：原始因果内容训练与双通道对照

**结论：已经完成真正的内容训练和冻结后独立生成的 heldout 检查；当前结果没有证明解析双通道的独立净收益。24 个预先定义的净效用对照，名义多重比较下限为正为 0/24。**

这是小型 synthetic raw-symbol 实验，不是 CREMA-D 原始音视频、完整 He–Xiong 再生神经元或生产 Hepta 的验收。模型参数真正更新，输出改变真实消费前缀和停止时机；“只增加特征但不改变动作”不再是本实验的失败原因。

## 实际执行

- 两项任务：保留被标记的二元符号；从逐步抵达的带噪符号判断类别。所有模型只看同样的符号、当前 dt、已经出现的 marker/query。没有外加精确后验或未来统计。
- 五个模型：ordinary、ordinary_dual、matched_slope、analytic_single、analytic_dual；各 782 个可训练参数、12 维状态和 1 个 validation 校准温度。single 对照将第二投影用于内容候选调节，未计入无用占位参数。
- 每模型固定 320 次 Adam 更新；五个独立训练 seed，合计 50 个训练模型。epoch、温度、STOP 阈值均只用 validation 选择。所有模型冻结后才创建 test、72 步长序列 OOD、时间/噪声偏移 OOD，每条件每 seed 768 个独立生成案例。
- 统计单位是五个独立训练/数据 seed；先重抽 seed、再在 seed 内成对重抽案例。不把 3,840 个案例称为 3,840 个独立训练模型。24 项比较 = 2 任务 × 3 条件 × 4 个对照。

## 固定完整前缀的内容质量

每格均为五个 seed 的均值。NLL、Brier 和 ECE 越低越好；Brier 为两个类别的平方误差和。

|任务|条件|模型|准确率|NLL|Brier|ECE|
|---|---|---|---:|---:|---:|---:|
|marked_memory|test|ordinary|0.9992|0.0282|0.0016|0.0008|
|marked_memory|test|ordinary_dual|0.9995|0.0200|0.0010|0.0005|
|marked_memory|test|matched_slope|0.9997|0.0111|0.0005|0.0003|
|marked_memory|test|analytic_single|0.9927|0.1816|0.0145|0.0072|
|marked_memory|test|analytic_dual|0.9966|0.0679|0.0069|0.0042|
|marked_memory|ood_long|ordinary|0.9997|0.0098|0.0005|0.0003|
|marked_memory|ood_long|ordinary_dual|0.9992|0.0325|0.0016|0.0008|
|marked_memory|ood_long|matched_slope|0.9997|0.0095|0.0005|0.0003|
|marked_memory|ood_long|analytic_single|0.9924|0.1604|0.0151|0.0049|
|marked_memory|ood_long|analytic_dual|0.9953|0.1084|0.0094|0.0054|
|marked_memory|ood_shift|ordinary|0.9781|0.8186|0.0437|0.0219|
|marked_memory|ood_shift|ordinary_dual|0.9794|0.8559|0.0411|0.0206|
|marked_memory|ood_shift|matched_slope|0.9865|0.4837|0.0271|0.0136|
|marked_memory|ood_shift|analytic_single|0.8474|2.6171|0.2964|0.1417|
|marked_memory|ood_shift|analytic_dual|0.9141|1.9463|0.1672|0.0784|
|noisy_evidence|test|ordinary|0.9732|0.0871|0.0438|0.0145|
|noisy_evidence|test|ordinary_dual|0.9740|0.0884|0.0432|0.0152|
|noisy_evidence|test|matched_slope|0.9745|0.0878|0.0440|0.0130|
|noisy_evidence|test|analytic_single|0.9714|0.0926|0.0479|0.0145|
|noisy_evidence|test|analytic_dual|0.9698|0.0859|0.0461|0.0127|
|noisy_evidence|ood_long|ordinary|0.9898|0.0355|0.0168|0.0071|
|noisy_evidence|ood_long|ordinary_dual|0.9906|0.0342|0.0155|0.0076|
|noisy_evidence|ood_long|matched_slope|0.9885|0.0359|0.0170|0.0064|
|noisy_evidence|ood_long|analytic_single|0.9867|0.0422|0.0202|0.0075|
|noisy_evidence|ood_long|analytic_dual|0.9867|0.0416|0.0207|0.0064|
|noisy_evidence|ood_shift|ordinary|0.8474|0.4675|0.2484|0.0923|
|noisy_evidence|ood_shift|ordinary_dual|0.8497|0.4737|0.2449|0.0913|
|noisy_evidence|ood_shift|matched_slope|0.8341|0.4900|0.2684|0.0973|
|noisy_evidence|ood_shift|analytic_single|0.8143|0.5382|0.2991|0.1105|
|noisy_evidence|ood_shift|analytic_dual|0.8057|0.4855|0.2879|0.0907|

## 消费/停止动作与完整成本

固定读取任务必须等待 query，故 marked_memory 的停止点不构成自由决策。noisy_evidence 的执行器确实停止取下一帧，runtime 不接收标签；分类结果完成后才评分。

|条件|模型|任务效用|平均读取帧|已执行批量推理 CPU 秒/768 例|
|---|---|---:|---:|---:|
|test|ordinary|0.881809|8.29|0.007949|
|test|ordinary_dual|0.863659|11.31|0.009527|
|test|matched_slope|0.872988|8.01|0.010878|
|test|analytic_single|0.869326|10.60|0.020292|
|test|analytic_dual|0.870564|9.41|0.014003|
|ood_long|ordinary|0.898523|8.47|0.014407|
|ood_long|ordinary_dual|0.832641|21.09|0.020377|
|ood_long|matched_slope|0.894093|8.33|0.017117|
|ood_long|analytic_single|0.888548|11.42|0.024883|
|ood_long|analytic_dual|0.894150|10.02|0.022279|
|ood_shift|ordinary|0.592203|13.15|0.010463|
|ood_shift|ordinary_dual|0.586610|15.34|0.013578|
|ood_shift|matched_slope|0.561501|13.24|0.016538|
|ood_shift|analytic_single|0.512931|15.99|0.021661|
|ood_shift|analytic_dual|0.524064|15.96|0.021192|

task utility = 2×是否正确−1−0.005×读取帧数−0.001×已耗任务时间。net utility 另按预先给定 CPU 价格 0.001/秒计入运行 CPU 和模型开发成本（摊销于 10,000 次查询）。这两个价格和摊销量是合同选择，不是部署经济规律。此处成本包括训练、validation、校准、真实停止消费；仿真数据生成、固定前缀诊断、反事实干预、证据写入另在实验总进程时间内计量。没有能耗或孤立请求尾延迟测量。

|模型|平均开发 CPU 秒/模型|
|---|---:|
|ordinary|0.764440|
|ordinary_dual|0.777808|
|matched_slope|1.016466|
|analytic_single|1.614039|
|analytic_dual|1.561793|

训练/确认实验进程合计 CPU 70.104 秒、wall 70.172 秒、峰值 RSS 79.62 MiB。统计汇总及本次只读复核为另外的后处理，没有混入推理成本。预算是同 optimizer updates；没有声称同 CPU 下获胜。

## 配对净效用差

下表均为 analytic_dual 减对应 control；括号为嵌套 bootstrap 95% 区间。精确原始 seed 数值及名义 24 项校正下限在 SUMMARY.json。

|任务|条件|对照|均值差|95%区间|停止点变化/3840|答案变化/3840|
|---|---|---|---:|---|---:|---:|
|marked_memory|test|ordinary|-0.005208|[-0.012500, 0.001575]|0|16|
|marked_memory|test|ordinary_dual|-0.005729|[-0.013021, -0.000521]|0|15|
|marked_memory|test|matched_slope|-0.006250|[-0.013021, -0.000521]|0|14|
|marked_memory|test|analytic_single|0.007813|[0.000000, 0.018229]|0|29|
|marked_memory|ood_long|ordinary|-0.008854|[-0.019271, -0.000000]|0|19|
|marked_memory|ood_long|ordinary_dual|-0.007813|[-0.018229, 0.001562]|0|21|
|marked_memory|ood_long|matched_slope|-0.008854|[-0.019271, -0.000000]|0|19|
|marked_memory|ood_long|analytic_single|0.005729|[-0.005729, 0.016667]|0|33|
|marked_memory|ood_shift|ordinary|-0.128125|[-0.210938, -0.061979]|0|370|
|marked_memory|ood_shift|ordinary_dual|-0.130729|[-0.210964, -0.059375]|0|377|
|marked_memory|ood_shift|matched_slope|-0.144792|[-0.214596, -0.090625]|0|356|
|marked_memory|ood_shift|analytic_single|0.133333|[-0.008333, 0.281784]|0|460|
|noisy_evidence|test|ordinary|-0.011245|[-0.027772, 0.004681]|2951|81|
|noisy_evidence|test|ordinary_dual|0.006905|[-0.021069, 0.045499]|3005|96|
|noisy_evidence|test|matched_slope|-0.002424|[-0.012199, 0.008732]|2427|87|
|noisy_evidence|test|analytic_single|0.001238|[-0.012250, 0.013464]|2044|67|
|noisy_evidence|ood_long|ordinary|-0.004374|[-0.020534, 0.015297]|3017|79|
|noisy_evidence|ood_long|ordinary_dual|0.061508|[-0.020399, 0.209347]|3098|76|
|noisy_evidence|ood_long|matched_slope|0.000056|[-0.012363, 0.016426]|2477|61|
|noisy_evidence|ood_long|analytic_single|0.005601|[-0.006018, 0.016267]|2160|51|
|noisy_evidence|ood_shift|ordinary|-0.068139|[-0.097778, -0.036771]|2851|450|
|noisy_evidence|ood_shift|ordinary_dual|-0.062546|[-0.100207, -0.019878]|2772|481|
|noisy_evidence|ood_shift|matched_slope|-0.037437|[-0.064202, -0.012487]|2625|458|
|noisy_evidence|ood_shift|analytic_single|0.011132|[-0.017909, 0.043284]|1829|311|

0/24 的名义校正下限为正，不应宣称双通道必要性或解析动力学独立优势已被证实。五个 seed 下，2,000 次 bootstrap 的校正尾部仅约四个抽样点；所报区间是描述性/名义区间，不能冒称精确有限样本 FWER 保证。

## 数学与因果性边界

- analytic_dual 的两个输出来自同一冻结 drift/variance 的上下**单边**首达概率。它们允许同一路径触及两面，不能相加当竞争概率。仅 analytic_dual 的输出均值之和就达到 1.15450（逐 arm 复核见 CONTENT_AUDIT.json），正好展示这个区别。它们不等于 equity/default value，也不是完整 regenerative reset/refractory 网络。
- matched_slope 只在每个实际 dt 的 a=b=0 处匹配两通道值和对 a、b 的偏导；不声称全域函数或全部训练轨迹一致。局部匹配误差 5.6e−17。
- 所有模型的独立方向有限差分梯度误差最高 1.4e−11；修改未来帧不改变此前输出。三组投影在全部 50 个选定 checkpoint 均发生非零改变，checkpoint 身份均不同。
- 两个解析输出是同样输入的确定性函数，只能改变归纳偏置；不会自动增加任务信息。移除某通道后动作/预测变化只证明计算依赖，不能证明重新训练后该通道不可替代。真正的训练对照包含 analytic_single 和 ordinary_dual。
- 对 150 组评估逐项只读重算，概率、标签配对、实际读取数、准确率、NLL、效用及计价均与存证完全相同，最大误差为 0。

## 交付与复现

代码为 models.py、study.py、summarize.py；完整合同、源码 SHA256、冻结 checkpoint 身份在 evidence/confirmation_01 的 PROTOCOL.json、REGISTRATION.json、FREEZE.json。SUMMARY.json 与 RESULTS.json 保留全文。原始数据、checkpoint、逐更新日志、逐案例结果会压入确定性 archive chunks；INDEX.json 保存原 member 路径、字节数、SHA256、所属归档，并逐项读回核验。restore_evidence.py 可在新目录还原精确字节。

剩余未证实项是研究结论本身：在强普通对照、真实因果媒体和更广任务上存在稳定净收益。当前负面结果应保留，而不是通过更换测试集、降低对照或改 acceptance 来“关闭”。
