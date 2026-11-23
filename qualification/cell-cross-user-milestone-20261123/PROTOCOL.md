# Hepta 首次跨用户学习实验

本方案登记在第一份真实用户输入到达前。当前没有已准入的训练用户或前瞻评测任务。任何实际运行都应把本方案版本、实际使用的软件、数据和模型分别固定下来。

## 已执行的工程对照

附带的 `fixture/` 保存了一个完全自建的一层、8 维 GPT-2 夹具，含两份各 6,080 字节的 safetensors、分词器、训练记录、实际输入、输出、分数与冷进程回执。输出头在 `train` 上执行一次 SGD，从错误的 `0` 学到目标 `1`。夹具构造时人为让 `train` 与 `later` 共享同一特征。两个模型均在首次冷调用收到 `later`，然后执行 `keep`。两道评测题的材料均显式排除训练用途。

| 冷启动时的实际调用顺序 | 期望 | 冻结父模型 | 候选 |
| --- | ---: | ---: | ---: |
| 1. 模拟后续题 `later` | 1 | 0 | 1 |
| 2. 模拟旧能力题 `keep` | 0 | 0 | 0 |

两臂使用磁盘上的独立清单和同一分词器，模型外部教师调用数为 0。两者在同一题上实际收到的 token ID 摘要一致。每题的模型输出和验证器结果都保存在 `fixture/evaluation/{parent,candidate}/`。这次运行的真实用户数为 0，加载 Circuit 数为 0，结算数为 0。`A_INTAKE_WITHOUT_NEW_RECORDS.json` 记录原项目入口以固定清单、历史原始观察和空的新训练输入运行后返回的 `INPUT_REQUIRED`。

要在项目的 CPU 测试环境中重新执行已经发布的两个模型，在仓库根目录运行下列命令，最后一个参数指向新目录。要从头构造并训练同一诊断模型，运行 `PYTHONPATH=scripts python -m cell_experiments.test_paired_cold --fixture NEW_DIRECTORY`。

```sh
fixture=qualification/cell-cross-user-milestone-20261123/fixture
PYTHONPATH=scripts HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python -m cell_experiments.paired_cold "$fixture/request.json" \
  e0cd3479b1fa58d00896432c908433434cce9a5a1e3dad0df9e79adf8e35f93f \
  "$fixture" NEW_EVALUATION_DIRECTORY
```

真实任务的两阶段接口先运行 `python -m cell_experiments.paired_freeze freeze SPEC MATERIALS SNAPSHOT`。`SPEC` 只接收父模型、候选、旧任务和每臂时限。先在独立授权入口保管输出的摘要。随后收到评测专用的 B 记录，运行 `python -m cell_experiments.paired_freeze assemble SNAPSHOT FREEZE_SHA FUTURE REQUEST`，将输出的请求摘要传给配对运行器。两步都以仓库 `scripts` 为 `PYTHONPATH`，只创建新工件。

Linux 上可用 `PYTHONPATH=scripts python qualification/cell-cross-user-milestone-20261123/replay_offline.py NEW_DIRECTORY` 复现整条工程路径。脚本在独立内核网络命名空间中运行两阶段接口和双冷评测，核对启动时仅有回环接口、两臂结束后收发计数不变，并记录原始分数和冻结摘要。该命令使用已经公开的夹具，能复核工程操作顺序；真实 B 的到达时间须有独立原始记录。

## 单个配对案例的判定

| 时点 | 原件与操作 | 判定 |
| --- | --- | --- |
| 用户 A 的真实失败 | 在私有入口核对来源、用途许可、当时模型可见的步骤、失败的执行回执、纠正动作及成功的原始验证。把失败动作保留为上下文，明确排除该动作的监督损失。 | 只有经过验证且在许可范围内的纠正进入训练。原始失败和训练派生物分别登记。 |
| 冻结 | 记录父模型及训练得到的候选的完整模型清单，包括基座、适配器、分词器、运行参数。若运行使用 Circuit，记录图、各 Cell 版本、路由权重、状态初值和路由计算预算。预先固定旧能力套件、主指标、推理预算、错误和弃权计分。由独立可复核的记录确定冻结先于未来任务的可用时间。 | 从冻结开始，未来输入仅对评测侧可见。任务到达后改权重、路由、评分器或阈值须重新开始前瞻评测。 |
| 用户 B 后续任务 | 在原始入口核对 A、B 为不同用户、B 的任务可用于评测、到达时间和原始任务承诺。核对来源、派生关系和近重复；预先闸定的规则同时适用于两臂。首次合格到达即纳入，保留所有分配结果。 | 独立记录证明身份和时间顺序。项目名、任务 ID、目录名、事后自填的时间均无法提供这项证明。 |
| 教师关闭，两臂冷启动 | 两个新进程从磁盘分别加载各自冻结工件，各运行一次相同的后续任务与旧能力面板。采用相同推理设置、可用工具和计分器。只允许实验约定的本地资源，保留实际加载摘要、输出、业务验收、调用和成本记录。 | 二元任务只有父模型失败且候选通过才记为这一次配对胜出。评测或交付不完整，单列待核验。 |
| 旧能力保持 | 冻结前为每项声称保留的能力选择有真实验收的旧任务。逐个记录父模型和候选在同一任务上的结果。 | 首例采用保守标准，每个能力至少有一项父模型通过，父模型通过的旧任务全部由候选通过。不可用或无基线覆盖的能力不计为已保留。 |
| 可核对结算 | 在派工前通过 Chain `prepare-request` 锁定服务请求，关联原始付款方授权合同及用途；终局读取同一请求、运行/模型身份、独立消费回执及账本变化。 | 按所用账本标明网络及单位，核对接收方、金额、终态、余额变更和所依据的交付；区分请求准备、预留和已结算。该合同的支付条件独立于科学结论。 |

本案可支持一次有限的跨用户迁移。群体效应需要更多独立用户。不同领域与未见组合任务的长期留出评测还应持续复核旧能力；只有在同一版本可重载的自有权重和 Circuit 上复现的提升，才计入系统的能力证据。

模型清单还应注明各部分的来源与权利范围。使用外部开放基座时，分别标出基座与 Hepta 训练并保存的参数。模型身份摘要覆盖推理所需的完整组合；旧权重、归一化统计或缓存若从未入档，应记为冷恢复缺口。

## 复用的入口

- A 的训练材料沿用项目固定的 train-only JSONL 入口。原始登记说明、私有来源证明及材料用途应可相互核对。B 提供仅供评测的后续任务入口；登记阶段可以只交付入口引用，具体任务在候选冻结后到达。[来源接入说明](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a5366ae2e16f1ed77273bc610671b580ecc0eaf0/qualification/cell-experiments-v3-20261116/operations/research-round03-20261117/data/SOURCE_INTAKE_03.md)
- 现有 E6 的 `D` 冷进程负责所选模型的一次调用。本案的两臂均需要实际加载并执行；工程夹具、历史回放和任务接入的结构校验各自单独标示。[E6 入口与证据范围](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/04518604db126d5a9d212f64f2647c986ee7ec06/scripts/cell_experiments/README_ADOPTION.md)
- Chain 的请求准备与终局读取共用同一摘要计算。后续读取需要沿请求找到相应的原生服务操作、合同和独立消费回执。[Chain 合同摘要及终局读取](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/105175d7b0f266be611020b540150c63cf910f5c/docs/development/CELL_LEARNING_BUSINESS_READBACK_V1.md)
- 带 Circuit 的后续实验可以复用 `FrozenRouter`。它从 `ROUTER.json` 校验并恢复按提示选图的系数。还要在同一冷进程按注册表加载各 Cell 对应的真实张量，记录实际选择及最终输出。既有 E4 归档保存了路由结果和 306 次调用的旧记录，归档清单明确未含模型权重。[冻结路由代码](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a5366ae2e16f1ed77273bc610671b580ecc0eaf0/scripts/cell_experiments/online_v4/circuit_router.py#L75-L132) · [E4 原始归档](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/a6c32fa20295a0fe38aa69f72d9c5f94712caaf1/qualification/cell-experiments-v3-20261116/operations/e4-complete-evidence-20261118)

## 两条规模曲线

数据多样性实验在同样硬件和总训练算力下，改变真正贡献更新的人数，同时固定并发度。对同组独立留出用户评价各候选相对父模型的配对增益，按用户加权。系统实验在相同入选名单、相同任务负载和每用户预算下改变并发 Cell 数，测完成并核验的唯一任务数/秒、耗时分位数和重试成本；同时报告实际重叠执行和相同的质量、保持性指标。每种规模比较的计算及验证预算和允许偏差须在看到结果前固定。

旧 E5 的每个更新单元最多引入一名用户。32 单元的固定总量可覆盖 1、4、16 人，不能覆盖 64 人。扩大共同预算或改为多用户批次需要单独登记，并重新建立可比的基线。面板点、可并发槽位和独立用户是不同的计量单位。
