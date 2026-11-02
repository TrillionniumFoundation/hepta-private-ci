# V13：新内容头的未来正确性拟合与固定校准

36个新联合内容checkpoint现在各有一个真实未来正确性读出器，均完成固定
128次AdamW更新及预声明五bin校准，未选最佳检查点或依据TEST结果调参。
`results/run001/CANDIDATES.json`封印全部36份reader权重、校准元数据和原始
未来目标。**控制pipeline尚未打开历史TEST；当前交付是训练与校准，不是
动态控制收益或新独立群体确认。**

第一轮prepare在任何TRAIN/VAL读取前正确拒绝：原内容训练PLAN依赖的
`recovered/v3/experiments/hcsn_free_boundary_v1/datasets.py`漏在发布Git树外。
原失败与3.820153 CPU秒保留。root随后只补发该文件的原字节，没有修改
训练、模型、控制算法或已有权重。新发布身份为远端
`f810ee199755d139f5b8c08187efc41cbd7839c9`、等价本地
`0381c6643b209c2374b309485212e68e7e1180c5`。第二轮prepare完整通过后，才
载入24/48个TRAIN及12/24个VAL对象。

每个checkpoint在TRAIN/VAL的完整合法A1起始prefix树上实际执行新模型的
持久状态更新和分类。每对象34个非空节点只计算一次；一至两次有序READ
的64个descendant引用提供正确性目标，不冒充64个独立对象或前向。
36个fit共实际执行66,096次离线joint状态更新，保存124,416条未来目标记录。
对象/标签只在离线教师和外层评分中出现，执行器只取得已接受历史和公开计划。

reader输入是同一354维格式：六槽已接受历史与mask、当前新内容头概率及
精确两READ顺序。未来读出target与当前STOP均绑定新的模型权重/标准化
身份，未借用旧V3头、旧V10风险分数或旧校准器。未来和STOP的五bin经验
校准只用历史VAL；重复prefix和后继属于相关开发记录，不是独立校准样本。

所有36fit在同task/seed下使用相同reader初始权重与minibatch索引流，二者
SHA已保存并在freeze时核同。所有reader权重、128项loss、归一化和校准
域通过检查；全部原始目标逐项重算标签/正确性/有序后继及保存哈希。
`CANDIDATE_AUDIT.json`中751,465项通过。另对每个checkpoint预指定的
TRAIN对象0重建34节点树，共1,224次真实新模型step，重放2,304条目标及
当前可见特征SHA，概率最大差为0。这是同实现真实前向重放，不能称为
第二套独立神经实现或科学质量证明。

完整batch以最多两个fit并发执行。batch外层CPU为188.711332秒、墙钟为
93.776259397秒，已包含全部36个子fit包络及父driver；子fit成本只作
嵌套拆分，不再次加总。失败prepare、成功prepare、batch、freeze及记录
审查五个不重叠正式包络合计206.359390 CPU秒；加全部预检/复跑16.009592秒，
已登记control范围下界为222.368982秒。完整项目成本、进程族峰内存和
设备焦耳仍未知，详见`COST_LEDGER.json`。

下一步必须先公开上述reader、校准、目标与源码的确切Git树，root独立读回
后由`campaign evaluate --publication ...`通过新的发布门，才执行历史TEST
的fixed/light/value策略。后续仍不能把这一已曝光历史群体称为新确认，不能
用源/算术检查数量代替实际控制净收益或解析核心增益。
