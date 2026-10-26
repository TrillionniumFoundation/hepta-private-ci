# 独立静态复核：公共语义 commitment 与双资格媒体入口

复核者：`control_next`。本记录只审阅源码、冻结身份、旧开发记录和既有实际 PCM/ASR 缓存；没有加载模型、运行 ASR、读取本次新资格的结果值，或开放正式 128-pair 来源。完整字节身份和机械检查保存在 [复核记录](CONTROL_BRIDGE_STATIC_REVIEW.json)。

**结论：在所列版本中未发现目标标签进入 commitment 或生成决策的路径。原双资格和正式来源入口保留。发现的本地依赖漏 pin 已形成明确的历史连续性补证，并通过独立前置 guard 约束正式执行。此结论只涉及实现和身份，不授予统计资格。** 正式 BASE/FINAL protocol 产生后，媒体执行方仍将按约定在首次正式访问前记录逐字段一致性比较；本次没有提前声称该记录已经产生。

## 公共输入、单 seed 和实际输出

`ingress.generate_state` 的 hard commitment 只取当前公共 encoder 概率的 `argmax`，audio/video 联合路径只平均两个公共估计；没有 `Target` 参数。原始 soft posterior 和分量 posterior 另外保留在 `encoder_belief`，没有以目标标签修正。之后的 canonical rendering 也只使用当前公共 state 的 posterior。构造任务时选取匹配的实际输入，和生成后独立观察器评分所用的目标，在代码路径上与生成决策分开。

这项操作会丢弃输入笔迹风格，并将输出限制为有限数字语义的固定语音和运动图像；保留 soft posterior 不能被当作已获概率校准，也不证明后续纠错能力。本轮没有通用自然音频、开放域视频或基础模型能力结论。

训练 receipt 指向 `seed-23179`。仅用 ZIP/pickle opcode 元数据静态检查，确认打包 checkpoint 的 `member_count=1`、`selected_members=[1]`，文件 SHA 为 `5c10b1ca0830879464f5d29219236fe88cb9422f7f630cb8dc7cc7b5844b3bbb`；没有执行 pickle 或加载权重。类名 `EnsembleIngress` 不表示实际使用三个 seed。旧失败开发结果和 bridge 旧开发结果分别保留；本次调整不能把旧开发成功改称新资格成功。

## 缓存的实际 PCM 身份和计费边界

独立重查 `MEASURED_EVENT_CACHE.json`（SHA `1883c9bc8476ae4f016a2cebdea78140c29d522f1767c1e833de37c7ffa862d1`）：14 项原始证据 pin 均匹配，11 个实际事件 WAV（十类及 silence）均为 8 kHz、单声道、16-bit、16,000 samples；文件 SHA 与真实 PCM SHA 全部一致。所有缓存的 target-free observation 都逐字段等于被绑定的原始 ASR 观察记录，未用预期标签替换转写。未知 PCM 会拒绝，两个组件观察器的 V3.1 组合只依赖实际转写。

新任务仍实际生成并写入、读回 codec 输出；对字节完全相同的事件复用观察记录不构成新 ASR 推理。原冷进程记录保留，包含旧媒体生成及 codec 等工作，因此不能把该 whole-process 时间写成纯 ASR 时间，也不能将缓存命中记作独立新观察。

## 双资格与样本单位

原冻结入口同时要求独立 ingress 与 `PRIMARY=consensus_or_single_v3` 观察器通过原 `.85` 门槛；实际 checkpoint、selection、ASR manifest 和资产字节须与获得资格的版本一致。正式执行还复核旧开发的完整公共 candidate pins，随后才调用新来源 loader。正式数值门槛、128 pairs、32 个 writer/speaker 匹配 cluster 和每 pair 五种输入模式均保留；640 个输出不是 640 个独立来源。

两个新资格终点使用同一批 **300 个登记录音、298 种唯一 WAV 字节、147 个 speaker**。两组重复文件均在同一个 speaker 内，没有跨 speaker 重复；不据结果删除重复或改变已冻结的 300 分母。这是同一 cohort 上相关的两个终点，不能写成两次独立实验或 600 个独立样本。本复核没有读取这些终点的结果值。

## 发现的依赖缺口与补证范围

原 `QUALIFICATION_PROTOCOL.json` SHA 为 `cd7be102f8c624caa7bac560866ae00e0f852627927121ba93c328392fad7114`，原 411 pins 保持不变。四个实际入口的递归本地 Python 导入闭包有 46 个文件，其中仅 21 个原本被该协议列入，另 25 个 helpers 确实遗漏。不能把后补记录描述为原协议已经预注册这些依赖。

`dependency_continuity/ADDENDUM.json`（SHA `4b24864a87e9d09e22d3b4b0990164a672ddef8ea0214d14cfb5a91dd9c63e46`）给出 21 项原 pin、12 项更早 Git 字节、11 项更早协议 pin、2 项原归档成员的完整映射。独立重核了全部当前身份、12 个 Git blobs、11 项旧协议，以及原归档的整体压缩 SHA、manifest 和两个成员的解压字节。46 项全部匹配。历史 Git `7f10e250…` 在本地记录中早于资格登记与实际 child 启动。

这证明所记录的源码身份连续性；它不是进程内存取证，也不把本地 Git 时间变成独立可信时间戳。复核覆盖静态本地 Python 导入，未把第三方包、动态库和操作系统宣称为完整固定环境。

## 正式 guard 的边界

新增 guard/build 位于独立子目录，未进入旧候选的三层根目录 `*.py` glob；原 49 个候选 Python 文件及其资格 pins 没有因补证被改写。guard 在导入原候选模块前复核 addendum、自身、全部闭包和原 411 pins。冻结时必须使用绑定 child 的实际 summary 路径，并确认进程成功结束，再调用保留的双资格 freezer。生成 FINAL protocol 时只扩展身份映射并加入连续性元数据，保留 BASE protocol。

执行入口复核完整 FINAL pins，再强制原评价器使用 `confirmation` 和指定 protocol。原评价器仍在实际候选、两资格与资产身份全部验证后才开放正式来源；退出后再查依赖。BASE→FINAL 除新增 pins/continuity 以外字段完全一致的独立启动检查，是对这条生产路径的额外记录；原 guard 的 evaluate 分支本身不执行该逐字段比较，不能混淆两者。

| 关键复核源码 | SHA256 |
| --- | --- |
| `bridge_v2/ingress.py` | `fe191d8e71980ef5112eea4f64a08bfa95452d920193293f31267d3baf704c0a` |
| `bridge_v2/evaluate.py` | `4d447f3504d3d1fbce4caa7af4e49092de1b74adbcaff557221a0650c8094571` |
| `dependency_continuity/build.py` | `c67d599124bcb87b534b9ba8d5edeb24226239bfac2fe629cc51e243c1f23799` |
| `dependency_continuity/guard.py` | `cd39d9c4b1a9f4e82cee57418d7ef1756415aadb1a34aab9bd6883c838fb887f` |

本轮复核没有修改候选、来源、模型、观察器、门槛或任何结果，也没有将静态复核通过等同于独立资格或正式四模态成功率通过。
