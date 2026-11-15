# V：run-v2 校准与特征范围审计

## 结论

当前拒绝按冻结实现正确发生。alpha=0.1 的来源数门已经满足；阻断是全量校准记录未完全落入训练样本的特征范围，不能将其改写成“样本量不足”。
frozen 的 54 条已知校准记录中，45 条域内、9 条越界；adapted 为47条域内、7条越界。两模式分别涉及7个校准来源；每个来源仍有域内记录，因此两cell各9来源/rank=1，与complete=false并不矛盾。

执行source固定3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd；原件来自不可变归档928a2603a7911cb5e8db439b7b814b9e033b6007。仅进行了读取和算术审计，没有重新export、fit、actor或修改任何原件。

## 原件与输入验证

- frozen checkpoint：c4ee4a0219117edeec6381b0bb01b896f9a182862298eba22d3c69a828c17096（11489 B）。
- adapted checkpoint：11e9e251d06ab46f12b0b16a8622a7a2c8d059943bdce763e1aa901df9471858（11474 B）。
- frozen EXPORT：1fd00505b3d59e5a6755603d93d0ebd7634b311a71588ee7b1809ae1fc608910（2358610 B）。
- adapted EXPORT：290d93428109f08906b6db69567c02c50f8c2760738124f8c71e77fe3e4f1ec6（2350217 B）。
- 两EXPORT原canonical pin以及四个checkpoint.input_sha256均匹配；详见observations JSON。
- 核对canonical digest时仅删除JSON字符串之外的空白、保持原数字/字符串lexeme与键序，再按原planned列表选择rows。没有用JavaScript重新序列化数值替代Python原digest。
- 每模式72条真实v2训练行重新计算47维minimum/maximum，94个边界值全部与其checkpoint一致。
- 96个conditional controller公共state的原SHA逐项匹配；仅对原状态作范围比较，没有重新执行policy或重新准入native artifacts。
- fit/calibration/evaluation为24/18/16来源，58个来源ID互不重叠。不是旧run-v1的72-state回归fixture。

## 94次校准拒绝与2次范围拒绝

原choose顺序先检查时间/形状及训练范围，再检查calibration.complete、cell存在性和有限残差。
两checkpoint的complete均为false，所以所有已经通过范围门的conditional调用返回insufficient_calibration：frozen 46次、adapted 48次。
另外2条frozen调用先被outside_observed_feature_envelope拒绝；完整source/case/state SHA与坐标列在observations JSON：

| case | 原坐标 | 实际值 | 训练边界 |
| --- | --- | ---: | ---: |
| case-cec614ca042812e30008c41a | features[16] | 0.8003638386726379 | maximum 0.7981781959533691 |
| 同上 | features[22] | -0.8109265565872192 | minimum -0.8041679859161377 |
| case-8620f006a753f96c76cb17d3 | features[14] | 0.6995145678520203 | maximum 0.6987173557281494 |

## 被排除的校准记录

| 模式 | 原pair编号 | 越界来源数 | 域内/计划 |
| --- | --- | ---: | ---: |
| frozen | p0073,p0094,p0098,p0100,p0101,p0107,p0110,p0112,p0113 | 7 | 45/54 |
| adapted | p0079,p0094,p0098,p0107,p0110,p0113,p0118 | 7 | 47/54 |

observations JSON保留每一行的完整decision/source ID、cell、全部越界坐标、实际值、原min/max与超出量。日期cell两模式均24/27域内；总额cell分别21/27、23/27域内。所有54条gain均已知；缺失标签不是这次complete=false的原因。

## 最小来源数与真实预算

_lower先对同一来源的残差取最小值，再取rank=floor((n+1)*alpha)对应的顺序统计量。alpha=0.1时n=8得到rank0、n=9得到rank1。因此每个目标cell至少9个独立来源；当前日期/总额cell是互不重叠的9+9=18来源，已经达到此门。无条件校准18来源也已有rank1。

54条记录不是54个独立来源；增加同源seed不增加n。两内容模式共享同一18来源，也不能算36个独立来源。rank非零仅保证存在有限下界，不证明条件覆盖、功效或效益；原policy仍明确conditional_coverage_guarantee=false。

真实冻结参数：alpha0.1、ridge0.001、READ bound30秒、finalizer reserve5秒、action budget40秒、episode wall60秒。96条conditional初始状态均40秒，30+5≤40，时间预算不是拒绝原因。

保留当前3条/来源、24 fit+18 calibration、双内容模式布局：每模式126完整STOP/READ pair，即双模式504 collection macro执行；校准部分为216执行。16 eval×3×12臂为576执行，合计1080。它只是下一完整development布局的预算基线，不保证原训练来源足以覆盖新域，也不是功效计算；新增训练覆盖来源数量与完整物理成本仍须另行确定。实际optimizer步骤和历史失败分母单列。

## 下一研究的前置条件与验收

1. 新研究独立冻结允许的训练域、来源分区、模型/context/source/receipt身份和上述门；旧eval不转成calibration/新确认，已暴露来源保留用途记录。
2. 训练域覆盖须来自真实、允许的训练观察。完整保留原计划校准行；不能放宽min/max、裁剪输入、降低alpha、删除越界记录或复制seed冒充新来源。固定训练域时只追加校准行，无法让已有越界行消失。
3. 两内容模式均通过原完整export/fit/cold-load路径，所有计划校准行域内、complete=true且每目标cell≥9来源。新adaptation receipt必须真实绑定新freeze与fit来源；旧原件不改名复用。
4. 校准机械门通过后，score+原lower_residual仍须严格>0才READ；合法nonpositive_value/STOP不算失败，也不能强制READ。V效益继续按原预注册效应、功效、独立确认和完整成本条件判断。

当前仅闭合根因定位。V效益、完整成本、独立确认和owner准入仍未建立。原NoUpdate研究标签不成为owner决定；本审计状态HOLD，owner_decision=null。
