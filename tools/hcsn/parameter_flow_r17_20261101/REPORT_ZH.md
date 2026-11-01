# R17：有限传播全坐标梯度与连续停止边界参照

本交付新增两项明确受限的数学／工程能力：R15 兼容四十状态法的全坐标一阶导数，以及一个独立的连续 GBM 永续美式 put 自由边界参照。**二者均为确定性开发验证，不是新的核心收益确认，也未闭合完整 He–Xiong／神经任务的连续自由边界或生产采用门。**

## 源码来源与冻结边界

本模块的 `SOURCE_FREEZE_V3.json` 绑定本轮执行源码；其中七项数值源码／协议冻结并没有单独列出导入的旧金融 kernel、R12 Cell、`BASE_THETA` 所读协议及 R15 Law。继承来源另由根层 `../four_stage_r17_20261101/BASELINE_READBACK.json` 绑定：根层在本轮检查前已核对 **53 项全部匹配**，来源为提交 `0fd894118c47f38c2acf2532b8242fd16df76c47`。没有依靠分支名或事后任意源码选择补齐身份。

`DEPENDENCIES.json` 在运行后补充摘录本模块实际依赖的路径、SHA256、该固定提交与根层收据 SHA256；它明确属于**运行后来源索引**，不冒称新的运行前冻结。数值记录中的源码冻结身份、已有检查及结果没有改变，也不以这次索引补充冒称重跑。NumPy／SciPy 版本由结果的运行环境记录提供。

## 有限法的全坐标导数

`flow.py` 独立命名了 48 坐标扩展：九个金融原参数，reset asset／recovery mean 的 log 坐标，有效内容保持概率的 logit，32 个 READ／REFRESH logits，以及四个初始内容 logits。原 R15 固定其中多数坐标；本轮没有重训练它们，也没有把新增参数数量隐去。

- 默认及另外两组 sigma／liquidity 下，Q 与旧 R15 最大差 `1.78e-15`；旧 prior 和观测法亦匹配。
- 实现 full／killed 转移、首事件概率、重复事件数、条件存活、Bayes evidence／posterior，以及显式 RESET 后完整后继的一阶 Jacobian。事件积分采用正通量；没有以 `1-survival` 丢失极尾精度，或将事件数裁成概率。
- 通过矩阵指数 Frechet 导数执行传播导数。初始分布、reset 插值、恢复率和 emission 同时参与链式法则；`sequence.py` 实际串起多次传播、缺测、READ／REFRESH 和 RESET。
- reset 插值 knot 不可微处拒绝；没有为硬 argmax／动作或自由边界拓扑伪造导数。零似然观察及存活下溢拒绝，不补 epsilon 或任选 posterior。

`RESULTS_V3.json` 是最终数值主记录。远端以确定性 gzip `RESULTS_V3.json.gz` 交付，其原始 512,968 字节 JSON 未作为单个文件发布；`RAW_COMPRESSION.json` 绑定压缩前后大小与 SHA256，并验证逐字解压还原。本地原始记录没有改变。三参数组 × 五时长 × 三观测中，三项 t=0 恢复 erasure 没有正似然，明确拒绝；其余 **42 情形 × 48 坐标 = 2,016** 方向全部执行，两种中心差分步长均保留。数值门固定于执行前。

| 核验 | 最大缩放绝对差 |
| --- | ---: |
| 参数导数相对中心差分 | 2.905e-7 |
| 两个差分步长之间 | 8.714e-7 |
| 状态相对独立 DOP853 | 1.297e-12 |
| 导数相对独立 tangent ODE | 2.078e-10 |
| 时间导数相对差分 | 7.106e-9 |
| 质量切向误差 | 3.625e-14 |

这里缩放量为 `max(abs(a-b)/(1+abs(b)))`，不是纯相对误差。ODE 不调用矩阵指数或 Frechet，但接收本实现 Q／dQ；参数到 Q 和 inherited FullHX 的链条靠中心差分另验，不能把这称作对金融公式的全新独立推导。所有结果只是列出的有限输入验证，非全参数域误差证明。

六条多步 prefix 共 **288** 坐标检查全部通过，最大缩放差 `2.995e-9`，见 `SEQUENCE_RESULTS.json`。十项错误边界契约通过，含 t=0 不可能 erasure、极长时域存活下溢、非法时间及 reset 插值 knot，见 `API_RESULTS.json`。

Linux `wait4` 外层记录最终数值 worker **18.96809 CPU 秒**，含解释器、导入、计算和输出；多步 worker另 **1.560494 CPU 秒**。这不是在线部署费用。V1 的零似然处理失败、V2 不必要的全时域极严 ODE 验证及未准确计时的开发尝试全部保留在 `FAILED_ATTEMPTS.json`；不能把未知 CPU 当零，也不将最终两次收据称完整研究成本。

## 真正连续的一维自由边界参照

`boundary.py` 求解一个单独的 GBM 永续最优停止问题。`BOUNDARY_SCOPE.md` 给出候选值、value matching／smooth pasting、变分不等式及验证论证；独立单调有限差分 obstacle solver 不读取闭式边界或闭式 continuation value。

三组参数、四层网格共十二次预定求解全部执行，最终最细网格最大边界绝对差 **0.13150**（strike 100），重点资产区间 value 差 **0.0002310**，离散 smooth-pasting slope 差 **0.012609**，LCP 残差 **6.47e-11**。各组首末网格 value 误差下降；原始非单调边界估计亦保留。数值网格邻点没有被称作严格连续边界夹逼，有限网格观察不等于收敛率定理。

## 剩余范围

完整金融有限期限／rollover 自由边界、reset／regeneration 边界条件、内容／控制的共同任务最优性、动态学习边界、所有分支的一致高阶梯度、生产 Rust／FP32／GPU、核心 D−B、全模态和能耗采用门仍未闭合。新 API 没有替换生产模型。

复现从仓库根执行（必须使用新的输出名，所有结果 create-only）：

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m tools.hcsn.parameter_flow_r17_20261101.verify --output /tmp/new-gradient-result.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m tools.hcsn.parameter_flow_r17_20261101.sequence --output /tmp/new-sequence-result.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m tools.hcsn.parameter_flow_r17_20261101.api_check --output /tmp/new-api-result.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m tools.hcsn.parameter_flow_r17_20261101.boundary --output /tmp/new-boundary-result.json
```

最终数值源码与执行 V3 相同；`SOURCE_FREEZE_V3.json` 保存当时完整冻结。之后仅更正失败收据中的一次终止方式描述，原误述及勘误均保留，不冒称重跑。当前 `SOURCE_FREEZE.json` 为相同数值源码的复现门。

远端原始 JSON 的逐字还原与读取：

```sh
gzip -dc tools/hcsn/parameter_flow_r17_20261101/RESULTS_V3.json.gz > /tmp/hcsn-r17-gradient-raw.json
python -c 'import json; print(json.load(open("/tmp/hcsn-r17-gradient-raw.json"))["gates"])'
```

压缩只改变交付容器，没有重新计算、删改数值行或改写原始 JSON；解压后的 SHA256 应与 `RAW_COMPRESSION.json` 的 `raw.sha256` 完全相同。
