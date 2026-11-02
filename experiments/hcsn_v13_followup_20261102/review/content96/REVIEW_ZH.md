# V13 静态内容 96 条件独立复核

审计技术结果：PASS。仅复核当前新训练的固定模型在已暴露 VAL/TEST 上的描述性历史重放；不是新的独立确认。quality_acceptance、all_blockers_closed、production_activation 均保持 false。

独立脚本仅使用 NumPy/stdlib，不导入作者评估器或聚合器、不训练、不选择模型/seed、不打开额外源数据、不计算置信区间。NLL 从原始 logits 以 stable logsumexp 重算；all 为全部 sequence×6-prefix 等权均值，final 为第6 prefix，先按10个dependent accepted orders汇总object，再与原作者object表逐项核对。

96 个唯一条件、36 个固定最终 checkpoint、全部 seeds 13301/13303/13307、1,728 条 object metrics 均完整。核对96个raw SHA256、136个publication gate文件SHA256/Git blobs、全部weights与TRAIN元数据、CANDIDATES/PLAN及source/protocol seal。当前HEAD `5913e31f16760b19a507860ef139f83eb8ce4089` 下199个评估证据文件逐个验证Git blob，其中96个raw。远端↔本地外部核验由root完成，本脚本只复核现存本地Git对象及记录映射。

原source remote `4c2fa0d86b9b09d5b26849b4738458fabc7b2945` 对应本地f77ee树；candidate/dependency remote `f810ee199755d139f5b8c08187efc41cbd7839c9` 对应本地0381树。PLAN的20个source文件在原source树可核，recovered/v3/experiments/hcsn_free_boundary_v1/datasets.py原树未包含，已在candidate/dependency publication中封存为blob `188bb065ad088c41169a2ed69827a3a7b7577e25`。此处没有把后来补依赖表述为原source已完整。

首次audit001因脚本假定PLAN全部source已在原source树而退出；失败源码audit_content96_failed001.py及cost_audit001日志保留。修复为区分原source树与补齐后的candidate/dependency树，fresh audit002通过。

独立重算相对原作者：row最大绝对误差1.11e-16，prefix/object 4.44e-16，三seed均值1.78e-15，逐seed contrast 1.11e-16，mean contrast 3.82e-17；在5e-12绝对容差内，无实质差异。概率最大误差2.22e-16；预测完全相同。

每split的async_av为12 recording objects×10 orders；av_binding为24 pair objects×10 orders，但仅12个底层recordings且每个recording被多个pair复用；每split只有2个历史actor。10 orders逐object核为audio首位、3 audio+3 video的全部10种次序。所有条件的labels/object_index/orders保持同一配对。不得把orders、重叠pairs、不同seed或A/D重复引用当作新的独立样本。

## 已暴露历史 TEST：三固定seed算术均值

accuracy列为百分比；NLL为越小越好。A/B/C/D分别为训练×执行full/full、full/margin、margin/full、margin/margin。

| task | condition | all accuracy % | final accuracy % | all NLL | final NLL |
|---|---|---:|---:|---:|---:|
| async_av | A: full/full | 25.277778 | 13.888889 | 3.909082336 | 4.347738197 |
| async_av | B: full/margin | 23.194444 | 13.055556 | 3.881993666 | 4.397319283 |
| async_av | C: margin/full | 24.907407 | 15.555556 | 3.975119585 | 4.325726372 |
| async_av | D: margin/margin | 24.907407 | 15.555556 | 3.976499856 | 4.328878406 |
| async_av | ordinary_gate | 23.657407 | 13.611111 | 3.950041442 | 4.229828880 |
| async_av | gru | 25.462963 | 18.055556 | 3.861700844 | 4.276009636 |
| async_av | ssm | 21.157407 | 9.444444 | 3.753822834 | 4.226689482 |
| async_av | history | 23.009259 | 12.500000 | 3.367283415 | 4.086084574 |
| av_binding | A: full/full | 51.851852 | 53.472222 | 0.725365643 | 0.728497724 |
| av_binding | B: full/margin | 51.944444 | 53.611111 | 0.725403581 | 0.728023247 |
| av_binding | C: margin/full | 50.277778 | 50.416667 | 0.722215203 | 0.723316539 |
| av_binding | D: margin/margin | 50.115741 | 50.416667 | 0.722200346 | 0.723276933 |
| av_binding | ordinary_gate | 51.574074 | 52.777778 | 0.723662819 | 0.725813700 |
| av_binding | gru | 50.509259 | 49.722222 | 0.707004871 | 0.700199003 |
| av_binding | ssm | 51.157407 | 52.638889 | 0.703685430 | 0.704784561 |
| av_binding | history | 49.513889 | 48.194444 | 0.707567374 | 0.712376175 |

## TEST：全部预登记contrast的三seed均值

差值方向均为左减右；accuracy差值为百分点，NLL差值为正表示左侧更差。hx_margin对照即D。

| task | contrast | Δall accuracy pp | Δfinal accuracy pp | Δall NLL | Δfinal NLL |
|---|---|---:|---:|---:|---:|
| async_av | A-B | +2.083333 | +0.833333 | +0.027088670 | -0.049581087 |
| async_av | C-D | +0.000000 | +0.000000 | -0.001380271 | -0.003152034 |
| async_av | A-C | +0.370370 | -1.666667 | -0.066037249 | +0.022011825 |
| async_av | B-D | -1.712963 | -2.500000 | -0.094506190 | +0.068440878 |
| async_av | (A-B)-(C-D) | +2.083333 | +0.833333 | +0.028468941 | -0.046429053 |
| async_av | A-versus-hx_margin | +0.370370 | -1.666667 | -0.067417520 | +0.018859791 |
| async_av | A-versus-ordinary_gate | +1.620370 | +0.277778 | -0.040959106 | +0.117909317 |
| async_av | A-versus-gru | -0.185185 | -4.166667 | +0.047381492 | +0.071728560 |
| async_av | A-versus-ssm | +4.120370 | +4.444444 | +0.155259502 | +0.121048714 |
| async_av | A-versus-history | +2.268519 | +1.388889 | +0.541798921 | +0.261653622 |
| av_binding | A-B | -0.092593 | -0.138889 | -0.000037938 | +0.000474477 |
| av_binding | C-D | +0.162037 | +0.000000 | +0.000014857 | +0.000039606 |
| av_binding | A-C | +1.574074 | +3.055556 | +0.003150440 | +0.005181185 |
| av_binding | B-D | +1.828704 | +3.194444 | +0.003203235 | +0.004746314 |
| av_binding | (A-B)-(C-D) | -0.254630 | -0.138889 | -0.000052795 | +0.000434871 |
| av_binding | A-versus-hx_margin | +1.736111 | +3.055556 | +0.003165297 | +0.005220791 |
| av_binding | A-versus-ordinary_gate | +0.277778 | +0.694444 | +0.001702824 | +0.002684023 |
| av_binding | A-versus-gru | +1.342593 | +3.750000 | +0.018360772 | +0.028298721 |
| av_binding | A-versus-ssm | +0.694444 | +0.833333 | +0.021680213 | +0.023713163 |
| av_binding | A-versus-history | +2.337963 | +5.277778 | +0.017798268 | +0.016121548 |

async_av上A−B的all accuracy为+2.083333pp、final为+0.833333pp，但all NLL变差+0.027088670，final NLL改善−0.049581087；C−D accuracy均为0，NLL变化很小。A−GRU的all/final accuracy分别为−0.185185/−4.166667pp，不能据该表声称A普遍优于普通模型。

av_binding上A−B的all/final accuracy为−0.092593/−0.138889pp，NLL变化约−0.000038/+0.000474；A对普通对照的accuracy有不同程度正差，但三seed均值NLL均更差。训练差异A−C与执行差异A−B须分别解释；这些小量描述性差异不能建立独立确认或机制/经济优越性。

## 可复核文件与成本

audit002/ROWS.json保留96条逐seed结果；OBJECT_METRICS.json保留全部object结果；CONTRASTS.json保留12组×10 contrasts×4 metrics；AGGREGATES.json和MEAN_CONTRASTS.json由独立算术重算。AUDIT.json记录逐项检查数量、原始文件与gate hashes、136个Git blob，SEAL.json补当前199个评估文件Git blob关联和审计源码/输出SHA256。

| envelope | task success | enclosing CPU seconds |
|---|---|---:|
| cost_inspect001 | true | 0.151233 |
| cost_audit001 | false | 0.751046 |
| cost_audit002 | true | 1.088548 |

所有实质审计通过现存v8 economics.worker_cost外层wait4包络且单线程。上表含失败成本；inner diagnostics不再相加。当前report/seal步骤另由cost_summary001包络，其RECEIPT.json保留该步骤成本。上述CPU是审计成本，不是模型推理时间或经济优势证据。
