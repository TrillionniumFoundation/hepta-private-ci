# 双模态原型：2026-11-09 最终证据

**结论：有界训练、推理、成本与回滚机制通过检查；动态策略仍 `no-update`，科学准入 `HOLD_NO_GO`。** 没有相对所有注册强对照的稳健净收益，原生动态请求继续回退 static-quota；语义质量、真实未来分布和项目专属云环境认证未闭合。

本页数字来自实际 JSON。完整精度、关键 SHA 和限制见 [summary.json](summary.json)，历史见 [attempts.json](attempts.json)，状态/收益/费用与命令见 [原型契约](../../scripts/ndu_bimodal/README.md)。

## 1. 来源与运行历史

最终源码 `2b70482f55d1b2007f04ad8636add032229d5fa1`；源码清单 SHA256 `9e5ca305cb0ad6a109d638d6270816268bf31667c80c4ba3359df5da49ba618d`，运行前后身份一致。实际执行标签为 `session-cloud-unattested`，Linux、Python 3.12.14、Torch 2.8.0 CPU、Rust 1.96。`project_cloud_environment_verified=false`：当前云会话的测试通过不是用户指定项目专属 Codex 云环境的身份认证。

| 记录 | 源码 | 实际结果与地位 |
| --- | --- | --- |
| 首轮 attempt-001 | `a945af5202f61b9c0a7eeb241ca4c72afb5a275a` | 25 Rust、37 Python，0 failure/error/skip；原始证据保留，已被取代 |
| 最终 cloud-final | `2b70482f55d1b2007f04ad8636add032229d5fa1` | 25 Rust、39 Python，0 failure/error/skip；passed_auxiliary_checks；仍 no-update |
| CLI 入口验收 | 首轮 HEAD，实际依赖另存摘要 | train/infer 成功；动态请求静态回退；错误权重 SHA 拒绝 |

首轮后修复 READ 包身份：READ counter 使用 `(seed,pending-signal,ready_at)`，延迟读取不改变同一包隐藏值；其他动作按 `(seed,time,action)` 耦合。冷加载增加校准残差/CDF/分位数/来源清单及精确特征维数验证，新增两项回归测试。最终轮沿用相同 seed 重新执行，不是独立新研究或新盲测。

根代理曾传短 SHA `a945af520`，parser exit 2，训练前拒绝、未创建目录；该事件依据当次工具回执，没有独立运行 JSON。CLI 首次额外全仓 clean 预检遇到并行修改无关控制文件而停止，尚未调用 train/infer；保留失败记录后改为冻结实际 CLI 依赖并记录仓库状态。错误权重 SHA 是预期负例，不算训练尝试或失败训练，过程成本保留。

证据：[最终 qualification](receipts/cloud-final/qualification.json)、[Python 测试](receipts/cloud-final/unittest.json)、[Rust 日志](receipts/cloud-final/rust-tests.stdout.log)、[首轮 qualification](receipts/attempt-001/qualification.json)、[CLI 报告](receipts/cli/report.json)。

## 2. 有限研究与对照结果

模型 risk=0.25、deadline/max_steps=6、utility_per_credit=0.01。12 个预算/等级初态共 **1,305 个可达状态、1,498 个不确定续行对**；每次 fit 支持覆盖率 1.0，终止训练目标 0。数值等级和终止收益是明确夹具，没有自然文本/图片语义质量验证。

seed 11、29、47 各训练 fixed-hidden/trainable-hidden，共六次 fit、每次 240 epochs；24 个校准来源，**48 个 future 来源**。动态每行 144 条记录是 **3 fit × 同一批 48 个来源，不是 144 个独立 future 来源**。训练已见有限 DP 全支持，程序化来源分离不代表真实未来分布泛化。

注册 `2026-11-09T08:44:19.207746+00:00`；权重/校准/固定策略冻结 `2026-11-09T08:44:25.425880+00:00`，随后生成本轮 future 结果。最终复验仍复用首轮注册种子。全部轨迹、配对数据、冻结记录保留在 [finite-study 压缩包](receipts/cloud-final/finite-study.tar.gz)。

| 方法 | 执行记录数 | 平均净效用 | 平均 credits | 控制器 ms/episode |
| --- | ---: | ---: | ---: | ---: |
| `encoder-only` | 48 | 0.200208 | 0.937500 | 0.108366 |
| `static-quota` | 48 | 0.373333 | 17.666667 | 0.411279 |
| `fixed-steps` | 48 | 0.386458 | 14.020833 | 0.235213 |
| `light` | 48 | 0.471250 | 20.416667 | 2.635457 |
| `exact-DP` | 48 | 0.458125 | 20.354167 | 1.101779 |
| `privileged-oracle` | 48 | 0.663958 | 19.729167 | 9.819539 |
| `tuned-fixed` | 48 | 0.374583 | 16.333333 | 0.319668 |
| `dynamic/fixed/trained` | 144 | 0.373333 | 12.486111 | 0.726933 |
| `dynamic/fixed/reset` | 144 | 0.373333 | 12.486111 | 0.707110 |
| `dynamic/trainable/trained` | 144 | 0.398750 | 14.430556 | 0.785595 |
| `dynamic/trainable/reset` | 144 | 0.237778 | 3.166667 | 0.388660 |

净效用为 realized 终止收益减全部模拟费用；控制器时间为 controller_seconds/episodes×1000，包含推理/支持检查，**暖缓存、额外列于模拟 tariff 之外**，不证明完整物理预算匹配。DP 最优仅指声明的嵌套风险模型；表中 realized 样本均值是另一统计量，light 点估计较高不否定模型内 DP。oracle 有未释放未来信息和额外搜索，非同信息可部署对照。

`tuned-fixed` 从预注册长度 0..3 的 40 个序列中，用校准来源执行 960 次，选择 both→image→text，future 不重选；调参 0.576019 秒、11,901 模拟 credits。DP 支持构建 0.849666 秒，六次 fit 3.094042 秒，整段有限评估 11.188126 秒；嵌套时钟不可相加。

### 动态主候选减对照

主候选 dynamic/trainable/trained；来源×初始化配对 bootstrap 1,200 次，五个主比较各 alpha=0.05/5=0.01，实用余量 0.002。区间是程序化实验的描述性区间，只有三个初始化，不提供部署覆盖保证。

| 对照 | 平均配对差 | 描述性区间 |
| --- | ---: | --- |
| `encoder-only` | +0.198542 | [+0.128264, +0.275486] |
| `static-quota` | +0.025417 | [-0.072361, +0.119722] |
| `fixed-steps` | +0.012292 | [-0.038750, +0.071042] |
| `light` | -0.072500 | [-0.141667, -0.007083] |
| `tuned-fixed` | +0.024167 | [-0.048958, +0.102917] |

相对 static-quota、fixed-steps、tuned-fixed 跨零，相对 light 为负，因此未通过全部强对照门槛；即使有限门槛通过，也不能自动取得真实部署资格。

**所有普通策略，包括动态、轻量和精确 DP，本次均 READ=0、WAIT=0。** 只有特权 oracle READ=2、WAIT=12。因此没有观测到同信息策略的未来信息价值净收益。原生 READ 是预定机制演示，也不是该项策略收益证据。

## 3. 训练×执行与校准

2×2 的 A/C 复用同一 static-quota（均值 0.373333）；B 为 fixed-hidden 动态执行（0.373333），D 为 trainable-hidden 动态执行（0.398750）。固定执行不依赖 fit，复用不算新物理执行或独立来源。

| 2×2 对比 | 平均差 | 描述性区间（此处 alpha=0.05，未作主家族调整） |
| --- | ---: | --- |
| `dynamic_minus_fixed/fixed_hidden` | -0.000000 | [-0.070694, +0.072569] |
| `dynamic_minus_fixed/trainable_hidden` | +0.025417 | [-0.048264, +0.097361] |
| `training_difference/fixed_execution` | +0.000000 | [+0.000000, +0.000000] |
| `training_difference/dynamic_execution` | +0.025417 | [-0.003542, +0.066042] |
| `interaction` | +0.025417 | [-0.003542, +0.066042] |

交互项跨零，未证明表示训练稳健放大动态收益。另列 trained/reset-hidden 表示消融：trainable/trained 减 reset 为 +0.160972，区间 [0.078542,0.246042]；重置已训练表示会损伤候选，不等于完整 Hepta/NDU 联合训练证明。fixed-hidden trained/reset 差为零。

残差校准使用 24×16=384 pair 的组最大绝对 DP advantage 残差，alpha=0.1，第 23 次序统计量。主候选三个 seed 的 future 检查分别覆盖 767/768、765/768、767/768（99.8698%、99.6094%、99.8698%）；这些是已知支持上的 48×16 次检查，不是 768 个独立真实任务。

**有限 DP 误差覆盖不是正确概率校准。** Brier/ECE 均 null，没有条件、语义 OOD 或真实分布保证。future 0 拒绝来自已知支持，不是未知输入识别准确率；未知支持、协议畸形输入和篡改 checkpoint 有负例测试，开放世界语义拒绝未建立。

## 4. 真实 v4、READ、成本和退化输出

实际内容训练 seed 41、12 步色卡，wall 0.308062 秒；candidate SHA `b613a7d5be3bda45a4d75bdef03f6f513b66e997aca4cbbb75a35d11444c9c61`。终止 critic/旧 actor 未训练。共享数值图中部分 audio/video 参数组也变化，但没有 AV 数据、同步训练或验证；参数变化不能解释为 AV 能力完成。

演示先编码和修复文本；提前 READ 被拒且不调用 loader；等待声明到达后实际重编码/重放，再修复图片并本地 SUBMIT。**7 次账本调用=6 次 Rust 子进程+1 次图片 loader**，不是 7 次服务商账单请求。原生组成 observation 2、generate 2、recompute 1、submit 1；最大状态误差 `4.4408920985006262e-16`，终止字节一致。

| 真实账本类别 | 事件数 | wall 秒 | 父 CPU 秒 | 调用数 |
| --- | ---: | ---: | ---: | ---: |
| `observation` | 5 | 0.151950 | 0.013123 | 3 |
| `control` | 13 | 0.093006 | 0.093031 | 0 |
| `generate` | 2 | 0.171792 | 0.015064 | 2 |
| `coordination` | 2 | 1.000362 | 0.000372 | 0 |
| `recompute` | 1 | 0.070941 | 0.005062 | 1 |
| `submit` | 2 | 0.081587 | 0.007141 | 1 |

驻留 8082512.383380 byte-seconds，结束登记 5,073,101 bytes。全演示 wall 1.596217 秒、父 CPU 0.160331、子 CPU 0.456192 秒；账本 wall 1.569638 秒。时钟重叠不可相加；reuse 本次 0，重放按 recompute。命名载荷不覆盖完整 heap/RSS，金钱/能耗仍 null。[完整事件与调用](receipts/cloud-final/native-demo/report.json)。

**semantic_quality=null。** [实际文本](receipts/cloud-final/native-demo/delivery/generated.txt)为 128 字节：一个 u 后 127 个 e，例如 `ueeeeeeeeeeeeeee…`。它是合法 UTF-8/framing，却没有形成有用颜色描述；[合法 PPM](receipts/cloud-final/native-demo/delivery/generated.ppm)也不证明图片语义正确。REPAIR 只证明数值变化，quality_improvement_certified=false。

CLI 用冻结后新输入 colour_card(9100011)：train/infer exit 0，dynamic 请求实际 static-quota、dynamic_admitted=false、no-update；PPM 实际解码 16×16 RGB，文本严格 UTF-8。4 次 Rust 调用，状态误差 `6.106226635438361e-16`。错误完整权重 SHA exit 1，未创建输出目录。[完整 argv/耗时](receipts/cli/commands.json)保留；可解码性不是语义通过。

## 5. 回滚、准入和证据交付

fixture candidate 未激活，active pointer 不变，冷加载 baseline 字节一致。公开 API 回滚测试用人为测试证据验证完整性、仅前一版本和 compare-and-swap；仅证明机制。实际候选仍 HOLD_NOT_ADMITTED，没有新生产候选上线后回滚的事实。

继续 no-update：有限收益不超过全部强对照；实际内容出现退化且未获语义验证；真实未来分布、保留能力、语义 OOD、完整资源成本、有限策略到原生状态映射未闭合；项目专属云身份未认证。AV Packet 时间/媒体时钟/同步分组字段只是接口，未完成同步 AV 或全模态策略验证。

PR 保留 [receipt-index.json](receipt-index.json) 的原始关键收据、输出及两轮压缩 finite-study（全部原始轨迹/配对、六个 controller checkpoint 和调参试次）。完整两轮运行、CLI、内容权重、二进制、checkpoint store、源码另附验收包，详见 [evidence-bundle.json](evidence-bundle.json)：

- `hepta-ndu-bimodal-evidence-20261109.tar.gz`，9,703,347 bytes；132 manifest entries，根代理已逐项校验。
- SHA256：`247e150a94ca2e7dc7e10c21c5f5e27a0323bc1938b9de8809269edd927ac3ed`。
- 最终 qualification SHA：`28881525a1e6f46da4ce5c58ecbd080de999fa001477644be7016cfddf9a92a8`。
- 最终原始 finite-study/report.json SHA：`994b9762e068f28d7a57be7f4c8495aa3d1b4a8b88d0e708d05159bbeb5cbf08`。
- 最终 finite-study.tar.gz SHA：`8b076262e719231ea6c2de38cc06a21230f8f244e31f8fec9509b9168ee09767`。

可只读执行 `tar -tzf receipts/cloud-final/finite-study.tar.gz`，或 `python -m json.tool summary.json`。重跑使用完整提交和 checkout 外新目录，参照原型命令；保留首轮、最终轮、失败预检及预期负例，不得看 future 重选策略却沿用原区间。当前证据支持可复现研究原型及其边界，不支持生产收益或全局最优声明。
