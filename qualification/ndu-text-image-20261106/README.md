# NDU × Hepta：真实图文下一轮的资格验证

**当前研究决策：NO_GO_FOR_LARGE_SCALE_TRAINING。**

本轮已修复数值与审计缺陷，接上真实图像/文字 encoder 到冻结语言 decoder
的内容梯度，并完成有预算边界的实际运行。下一轮完整五类任务、控制器
2×2、强比较器、独立外部净收益与旧能力保持尚未执行；不能由本目录的
合同测试或单样本训练损失替代。

研究命题：

> 在相同内容模型、数据和真实预算下，以固定外部目标为约束的 NDU
> 动态控制，能否通过 Hepta 内部内容演化，选择有价值的后续计算和输出组合，
> 并在联合训练后产生超过强普通控制器的净收益？

## 实际完成的工作

| 层次 | 可复查的新增工作 | 证据边界 |
|---|---|---|
| 数值参考 | 修复零概率、极小风险和极端风险下解析梯度的不稳定；保留修复前失败及修复后结果 | 有限离散参考，不是通用连续时间 FBSDE |
| 状态表示 | 文字/图像分别命名；保留共享状态、可用性、准备状态、进度、版本和已提交前缀；Torch 拼接保留梯度 | pooled latent，不是完整 token/空间地址系统 |
| 材料准入 | 核验实际文字/图像 bytes、外部注册表、历史 split、case 级参考答案 pin、模型角色和文件身份 | bytes 验证不能认证科学有效性 |
| 实验审计 | 完整 A/B/C/D × frozen/joint，initial/fixed/VOI/MPC，比较器锁定、20 项配对 contrast、完整成本 | 没有 native receipt verifier，科学门槛一律 HOLD |
| 真实生成图 | 真实蜂/花照片 + 实际 SmolVLM2，V3 原始 Hepta core，两种 core 同初始化，真实 decoder 输入梯度 | 单个已公开开发样本；没有控制器或独立评价 |
| 复现与接入 | 原始源码快照、权重、运行记录、最终源码合同测试、现有 CI 的语义合同步骤 | 没有执行 #4944 的 native owner 路径 |

实现位于 `scripts/ndu_portfolio/` 与 `scripts/ndu_semantic_state/`。
格式与命令见 [FACTORIAL.md](FACTORIAL.md)、
[SEMANTIC_STATE.md](SEMANTIC_STATE.md) 和 [PROTOCOL.md](PROTOCOL.md)。

## 实际真实图文运行

只使用 ai395 上已经下载并有内容身份记录的文件；模型和输入在运行前后校验。
执行不涉及另一条 CUDA 170-run campaign。新运行没有模型下载、自动重试、
扩大训练或部署动作。

- 模型：HuggingFaceTB/SmolVLM2-256M-Video-Instruct，
  revision `067788b187b95ebe7b2e040b3e4299e342e5b8fd`。
- 冻结 safetensors：`dcc8f4c00d30d70bb3028a1bfc373e1b1972e25919f8788183cae4ae72431ce2`；
  13 个模型文件已核验。
- 已公开开发图像：`8b21ba78250f852ca5990063866b1ace6432521d0251bde7f8de783b22c99a6d`。
- 原始 V3 core blob：`040dfaf474bccd07ecb64a6360e486240325458c`，
  来自 `17376f025cbc62bd8e169bdd9f6d2b7341033cbc`，复制后保持原 bytes。
- 固定 seed 17，FP32 CPU，两个线程，latent width 16，3 次内部演化，
  每种 core 一次 SGD 更新；每种均为 61,472 个可训练参数。
- 初始权重身份相同；冻结回放不改变权重；训练改变权重；保存/重载后同进程
  logits 精确一致。此项没有恢复优化器或完整运行状态，也不是冷进程复现。

| First-target-token CE（越低越好） | 普通 core | Hepta dual core |
|---|---:|---:|
| 桥接零步 | 11.48171520 | 11.48171520 |
| 冻结桥接三步 | 11.43803310 | 11.43957806 |
| 一次联合更新后 | 11.43682384 | 11.43832874 |

真实 decoder 的梯度到达 core、shared、text 和 image；冻结 backbone
没有积累参数梯度。该单样本的 Hepta 损失没有低于普通 core。两列没有运行
light/NDU 控制器，因此**不是 A/B/C/D，也不能解释为 D−B 实验**。

固定 8-token 初始生成结果为：

`The insect shown on the flower is a`

它未完成回答。记录保留了这一限制，没有增加 token 或重复尝试以修饰结果。
训练目标仅为首个 target token 的交叉熵；训练损失降低不等于输出任务完成，
更不等于外部净收益。

模型子进程完整包络为 **9.804742 CPU 秒 / 7.726188 秒墙钟**，
峰值 RSS 1,468,584 KiB。独立 Torch 合同子进程另用
0.749446 CPU 秒 / 0.715760 秒墙钟。内部阶段计量不能与完整包络相加；
能源、工具调度、传输与先前模型获取成本没有完整观测，保持 null。

### 原始证据与最终源码的区分

[evidence/real-content/EXECUTION.json](evidence/real-content/EXECUTION.json)、
[RUNTIME_STATUS.json](evidence/real-content/RUNTIME_STATUS.json) 与
[probe/terminal.json](evidence/real-content/probe/terminal.json) 是实际运行记录。
[ordinary.pt](evidence/real-content/probe/ordinary.pt) 和
[dual.pt](evidence/real-content/probe/dual.pt) 是两次实际更新的权重。

[executed-source.zip](evidence/real-content/executed-source.zip) 保留当时的完整源码
bundle 和 supervisor；原始 bundle SHA-256：
`12241add5ffcb665c054db6ec5bc7012bad278fab171ed7175a7d14a8ab32462`。
本轮后续加强了 state/materials 的拒绝边界，最终源码另跑合同测试；
没有把旧的模型运行冒充最终所有源码的模型运行，也没有重复训练补结果。

## 六个推进门槛现在是什么状态

| 门槛 | 本轮证据 | 仍需满足的推进条件 |
|---|---|---|
| 数值参考 | #4875 有限参考、饱和梯度修复与回归 | 真实 runner 与统一风险/费用/STOP/动态偏好目标逐项一致，native 对照仍需实测 |
| 内容机制 | 真实 decoder 梯度与一次权重更新已测 | 五类真实任务上增加步骤带来独立可测内容改善；补完整图像输出与可寻址内容 |
| 状态表示 | 模态身份、前缀、材料边界、Torch 梯度合同 | 实测策略识别哪个输出值得继续；命名 slots 本身不能证明有效选择 |
| 冻结控制 | 完整 16-profile 审计接口与强比较器锁定 | 真实 A/B/C/D、同数据 fixed/VOI/MPC、独立外部净收益 |
| 联合训练 | 单样本内容桥接更新 | 独立确认集、完整 frozen/joint 对比、旧能力与训练重复性 |
| Hepta 增量 | 普通/Hepta 内容桥接同参数同初始化 | 相同控制器下 D−B 的外部净收益，以及交互项 |

主要门槛是相对验证集锁定的最强可部署比较器，外部净收益的多重校正下界
超过预注册最小收益，并满足成本、完整证据和旧能力保持条件。赢过初态、
STOP 或 abstain 不能单独推进。

## 与现有工作的接点

- [#4875](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4875)
  head `0ea61fb707fbcc399ea2318238652efe411c6535` 是本改动的真实父提交。
  有限参考的既有负面 retention 结果继续保留。
- V3 `17376f025cbc62bd8e169bdd9f6d2b7341033cbc` 提供实际 core，
  旧几何图像/正弦音频合成任务不升级为真实语义任务。旧 slot mean 对模态交换
  不可辨识，新的接口保留模态身份，旧 actor 的输入布局不兼容。
- [#4944](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4944)
  head `25fa6d6dd7e1c5c1827a4099f601aee49b2f1b58` 的 owner 设计是后续
  集成边界：Cell journal 保持权威，Joint planner 保持纯计划，Decision/Outcome
  必须由既有认证计量链产生。本 Python 探针没有另造 owner，也没有声称原生
  集成验证；原 #4944 被测源码与 head 的区别保留在接入说明。

## 执行与验证

```bash
PYTHONPATH=scripts python -m ndu_portfolio.qualify_text_image \
  --output /tmp/ndu-text-image-contracts
PYTHONPATH=scripts python -m ndu_portfolio.example_factorial \
  /tmp/ndu-text-image-factorial
```

实际模型 qualification 需要其已核验的本地模型/图像路径与 Torch 环境：

```bash
PYTHONPATH=scripts:. python -m ndu_portfolio.real_content \
  --model-dir /path/to/pinned/vlm \
  --image /path/to/pinned/input.jpg \
  --output /tmp/ndu-real-content-new-run
```

输出目录必须全新。此命令会实际计算，不能被当成单纯文件检查。本次原始
执行已封存；没有必要为确认原运行成功而重跑训练。

本地 focused suite 的 Torch 跳过与远端最终 Torch suite 分开记录；
确认结果见 `evidence/contracts/` 和 `evidence/final-torch-contracts/`。
本地发现 139 项，136 项通过、3 项因缺 Torch 跳过；这 3 项随后在 ai395
最终源码上全部通过。两地 source manifest 一致，共 139 个不同合同测试
获得通过记录；这不等于 139 个真实任务实验。摘要见 [VERIFICATION.json](VERIFICATION.json)。
现有 blocking CI 保留全部原门槛，增加语义/材料合同步骤。未声称本地完成
Rust 全仓构建或完整远端 CI；此工作区只物化了所需文件，
`codex-rs` 不存在，因此 `just fmt` 未在本地执行。
