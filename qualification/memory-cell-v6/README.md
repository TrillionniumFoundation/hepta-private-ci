# Hepta Memory Cell V6

V6 提供可运行的类型化记忆实验和本地 CLI：写入自己的事件、语义属性与程序，训练独立参数 cell，经过已保存的语言路由器读取，并保留来源、模型、版本和成本记录。正式结果、失败案例与验收判断见 [RESULTS.md](RESULTS.md)；复现协议见 [PROTOCOL.json](PROTOCOL.json)。

完整原始证据的解包、离线复算、源码身份和补充核验见 [DELIVERY.md](DELIVERY.md)。它们可以在不重新训练模型的情况下审查本轮结论。

**生产 organ／TaskFlow 尚未接通这些 cell。** 当前实现包含 Python qualification、Rust 类型与检索验证边界，以及调用现有 context compiler 的 qualification bridge。接入真实 cognitive owner、产品权限、运行生命周期和 provider delivery 仍需生产适配。具体已完成与待接线项见 [native/INTEGRATION.md](native/INTEGRATION.md)，native 复现入口见 [native/README.md](native/README.md)。

## 1. 环境与已固定版本的 encoder

以下命令从仓库根目录执行，使用 Python 3.12。模型缓存、个人数据和实验输出位置均可自行选择；示例使用相对路径，不依赖作者机器上的绝对路径。

```sh
python3.12 -m venv .venv-memory-v6
. .venv-memory-v6/bin/activate
python -m pip install -r qualification/memory-cell-v6/requirements.txt

V6_ROOT=qualification/memory-cell-v6
V6_WORK=work/memory-v6-local
export PYTHONPATH="$PWD/$V6_ROOT${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$V6_WORK"

python "$V6_ROOT/download_encoder.py" \
  --model multilingual \
  --output "$V6_WORK/models/multilingual"

python "$V6_ROOT/download_encoder.py" \
  --model english \
  --output "$V6_WORK/models/english"
```

下载入口只接受仓库已经声明的 `english` 或 `multilingual` encoder，逐文件校验固定 revision 对应的字节数和 SHA-256。已有正确缓存可以复用。缓存路径及其父目录不能使用符号链接。`memory_cli.py` 不负责下载模型，缺少所选 router 绑定的本地 encoder 时会明确失败。

个人使用可只准备 multilingual 缓存。下面的个人示例以 multilingual 作为唯一候选 encoder；正式比较会同时使用两种缓存。依赖版本见 [requirements.txt](requirements.txt)。

## 2. 用自己的数据完成一次写入、训练和读取

### 2.1 准备一个 selected router

如已有身份校验通过的 selected router，可直接设置其目录及匹配的 encoder 路径。首次使用可运行：

```sh
python "$V6_ROOT/train_router.py" \
  --model-cache "$V6_WORK/models/multilingual" \
  --output "$V6_WORK/routers-demo" \
  --seeds 1103

V6_SELECTED="$V6_WORK/routers-demo/seed-1103/selected"
V6_ENCODER="$V6_WORK/models/multilingual"
V6_SOURCE="$V6_WORK/personal/source.sqlite"
V6_ARTIFACTS="$V6_WORK/personal/artifacts"
V6_SCOPE=personal:memory-demo
```

这里训练并选择小分类头，encoder 保持冻结。训练输出目录必须尚不存在。若复用同时比较多个 encoder 的训练结果，应根据该 seed 的 `SELECTED.json` 与 `selected/manifest.json` 选择匹配的缓存；不能把任意 encoder 与已训练的分类头组合。纯 lexical 候选无需 encoder，CLI 会忽略其 `--encoder-path`。

### 2.2 写入 typed records

将下面内容保存为 `$V6_WORK/records.json`。CLI 接受一个记录对象，或最多 256 条记录组成的数组。`scope` 由命令行明确指定；每条记录提供 `entity`、`kind`、`effective_at`、`value`、`origin_id`，修订已有记录时还可提供 `predecessor`。

```json
[
  {"entity":"meter-orion","kind":"event","effective_at":10,"value":7,"origin_id":"manual:orion:event:10"},
  {"entity":"meter-orion","kind":"event","effective_at":20,"value":11,"origin_id":"manual:orion:event:20"},
  {"entity":"meter-orion","kind":"semantic","effective_at":20,"value":{"factor":3,"label":"orion-calibration"},"origin_id":"manual:orion:semantic:20"},
  {"entity":"meter-orion","kind":"procedure","effective_at":20,"value":{"opcode":"affine","bias":2,"limit":1000},"origin_id":"manual:orion:procedure:20"},
  {"entity":"meter-vega","kind":"event","effective_at":20,"value":19,"origin_id":"manual:vega:event:20"},
  {"entity":"meter-vega","kind":"semantic","effective_at":20,"value":{"factor":5,"label":"vega-calibration"},"origin_id":"manual:vega:semantic:20"},
  {"entity":"meter-vega","kind":"procedure","effective_at":20,"value":{"opcode":"clamp","bias":-1,"limit":80},"origin_id":"manual:vega:procedure:20"},
  {"entity":"meter-lyra","kind":"event","effective_at":20,"value":4,"origin_id":"manual:lyra:event:20"},
  {"entity":"meter-lyra","kind":"semantic","effective_at":20,"value":{"factor":2,"label":"lyra-calibration"},"origin_id":"manual:lyra:semantic:20"},
  {"entity":"meter-lyra","kind":"procedure","effective_at":20,"value":{"opcode":"identity","bias":0,"limit":1000},"origin_id":"manual:lyra:procedure:20"}
]
```

```sh
python "$V6_ROOT/memory_cli.py" write \
  --source "$V6_SOURCE" \
  --scope "$V6_SCOPE" \
  --input "$V6_WORK/records.json" \
  > "$V6_WORK/write-result.json"
```

返回值包含各条记录的 `source_id` 与新的 `source_cut`。每条 append 是独立的不可变记录事务；批量写入不是一个原子事务，重复运行同一导入也不是幂等操作。修改现有记录需要追加修订，不能直接改 SQLite payload。

当前参数快照要求同一 scope 至少存在两条有效 semantic 和两条有效 procedure 记录。示例使用三个实体，使后续撤销一个 semantic 来源后仍能重新训练剩余记忆。事件时间为调用者定义的非负整数，最大为 `2**53 - 1`；示例中的 10、20 只是便于演示的时间坐标。

### 2.3 训练一个干净的参数快照

```sh
python "$V6_ROOT/memory_cli.py" train \
  --source "$V6_SOURCE" \
  --scope "$V6_SCOPE" \
  --artifacts "$V6_ARTIFACTS" \
  --selected "$V6_SELECTED" \
  --encoder-path "$V6_ENCODER" \
  --seed 1103
```

此命令从当前有效来源重新训练 semantic／procedure cell，保存不可变参数对象，再通过 generation 的 compare-and-swap 发布完整 bundle。事件仍由 source owner 精确保存。快照绑定 source cut、来源 frontier、两个参数 cell 和所选 router 的 manifest digest。

`--steps`、`--hidden` 控制训练规模；`--expected-generation` 可用于显式约束发布前代。CLI 的 `train` 总是干净重建，不继承可能含已撤销来源的旧权重。新写入或撤销会使旧快照失效，读服务不会把新来源与旧参数混成一个成功结果。

### 2.4 提交 MemoryRequest

将下面内容保存为 `$V6_WORK/request.json`：

```json
{
  "query_id": "query-apply-orion",
  "scope": "personal:memory-demo",
  "entity": "meter-orion",
  "text": "Apply the stored procedure to the latest value of meter-orion.",
  "at": 20,
  "since": 10,
  "max_hops": 4,
  "max_cells": 3
}
```

```sh
python "$V6_ROOT/memory_cli.py" read \
  --source "$V6_SOURCE" \
  --scope "$V6_SCOPE" \
  --artifacts "$V6_ARTIFACTS" \
  --selected "$V6_SELECTED" \
  --encoder-path "$V6_ENCODER" \
  --request "$V6_WORK/request.json"
```

`entity`、`scope` 和时间字段由调用者提供。CLI 规范化文本中的这些已声明槽位，加载已保存的 router，选择操作，再调用真实 `MemoryRuntime`。router 不负责从任意文本中推断实体身份，地址哈希也不承担语义检索功能。

输出为 JSON `MemoryReadout`，附 `router_decision`、`router_digest`。关注 `status`、`value`、`source_ids`、`cell_digests`、`generation`、`snapshot_digest`、`prediction_kind` 和 `reason`。若本例路由为 `apply` 且参数读回正确，计算应为 `11 * 3 + 2 = 35`；这只是输入数据的可核对示例，不是正式评估指标。router 可以拒绝请求，参数 cell 也可以拒绝不在支持域内的地址；应检查实际 decision 与状态。

当前语言接口覆盖六种操作：

| 操作 | 运行行为 |
|---|---|
| `current` | 最新事件值 |
| `history` | 不晚于 `at` 的事件值 |
| `semantic` | 当前 semantic 参数 cell 的属性预测 |
| `procedure` | 当前 procedure 参数 cell 的程序选择预测 |
| `change` | 最新事件值减去不晚于 `since` 的事件值 |
| `apply` | 最新事件、当前语义属性和当前程序的三类组合执行 |

`read` 没有 operation override、gold 或 expected-answer 输入。传入 contract 之外的字段会被拒绝。预测、任意聚合、解释等新增意图不能因为“听起来接近”而自动获得新的操作定义。

### 2.5 撤销来源并重建

从第一次写入回执中取出 `meter-orion` 的 semantic 来源：

```sh
V6_REVOKE_SOURCE=$(python -c \
  'import json,sys; rows=json.load(open(sys.argv[1]))["written"]; print(next(r["source_id"] for r in rows if r["entity"]=="meter-orion" and r["kind"]=="semantic"))' \
  "$V6_WORK/write-result.json")

python "$V6_ROOT/memory_cli.py" revoke \
  --source "$V6_SOURCE" \
  --scope "$V6_SCOPE" \
  --source-id "$V6_REVOKE_SOURCE" \
  --reason "user requested revocation"

python "$V6_ROOT/memory_cli.py" train \
  --source "$V6_SOURCE" \
  --scope "$V6_SCOPE" \
  --artifacts "$V6_ARTIFACTS" \
  --selected "$V6_SELECTED" \
  --encoder-path "$V6_ENCODER" \
  --seed 1103
```

撤销后、重建前，旧快照读取会因来源版本变化而失效。重建排除已撤销来源；此时再请求 `meter-orion` 的 `apply` 应因缺少可用 semantic 支持而拒绝。其余有效实体仍可使用。当前来源日志和旧参数版本为审计而保留，因此撤销与干净重建不等于磁盘物理删除，也不构成统计意义上的机器遗忘证明。

### 2.6 查看摘要和成本

```sh
python "$V6_ROOT/memory_cli.py" inspect \
  --source "$V6_SOURCE" \
  --scope "$V6_SCOPE" \
  --artifacts "$V6_ARTIFACTS"
```

`inspect` 输出 generation、source／snapshot／router 摘要、source cut，以及数据库、日志、artifact 目录、当前 cell 和训练 CPU 的成本字段。它不输出实体 payload。encoder 的共享基座成本与路由候选搜索成本另由训练／正式实验账本记录，不能只拿当前 cell 字节当作系统总内存。

## 3. 三类 cell 实际存储了什么

| 类型 | 当前表示与读取 | 当前 payload |
|---|---|---|
| event | SQLite source owner 中的不可变事件；按 scope、entity、时间和 cut 精确解析 | 一个整数 |
| semantic | 用实际优化得到的小型 tanh MLP 学习地址到属性类别的关联 | `{"factor":整数,"label":字符串}` |
| procedure | 用独立 MLP 学习地址到有限程序 catalog 的关联；选择后交给唯一解释器 | `{"opcode":字符串,"bias":整数,"limit":整数}` |

semantic 和 procedure **仍显式保存完整 value／program catalog**，模型预测类别索引。读取过程中不会从训练映射或原始 semantic／procedure payload 查答案；来源校验读取元数据并检查依赖。catalog、参数、支持集、旧版本、回放数据、基座和所有候选都必须纳入成本。当前实现是关联学习，不是已经证明的自由文本压缩，也没有微调 MiniLM 基座。

`event`、`factor`、`bias` 必须是 `[-1_000_000, 1_000_000]` 内的整数；`limit` 为 `[0, 1_000_000]` 内的整数；`label` 为非空、最多 256 个 UTF-8 字节的字符串。布尔值不作为整数接受。字段集合按 [v6/values.py](v6/values.py) 严格校验，目前不能直接写任意属性字典。

设事件值为 `e`、语义因子为 `f`、程序偏置为 `b`、上限为 `L`，固定程序只有以下五种：

| `opcode` | 执行语义 |
|---|---|
| `identity` | `e` |
| `add_bias` | `e + b` |
| `multiply` | `e * f` |
| `affine` | `e * f + b` |
| `clamp` | `min(max(e * f + b, -L), L)` |

即使某算子不用 `bias` 或 `limit`，其字段也要完整提供。程序是有限的、已注册的 typed arithmetic DSL；训练只学习选择，没有发明新程序原语。参数预测保留 `model_prediction` 或 `mixed` 身份，来源依赖校验不把预测提升成独立证明的事实或可信指令。

## 4. 正式实验的可复现顺序

正式执行顺序是：**`train_router` → `prepare` → `seal` → `run_language` → `audit_results`；`run_extensions` 单独执行预声明的扩展实验。** 使用全新的输出目录，保留失败、所有候选和原始记录。个人数据示例与正式实验使用不同输出目录。

开始前，执行脚本、`v6` 模块、测试及协议应已经在一个 Git 提交中。`seal` 会验证这些源文件确实匹配当前 `HEAD`，后续评估还会验证 commit、文件摘要、模型、encoder、依赖版本及输入封存身份。封存期间不修改它们或切换 `HEAD`。实验输出不要求为封存而提交。

### 4.1 训练并选择全部声明 seed 的 router

```sh
V6_FORMAL="$V6_WORK/formal-v6"
mkdir -p "$V6_FORMAL"

python "$V6_ROOT/train_router.py" \
  --model-cache "$V6_WORK/models/english" \
  --additional-model-cache "$V6_WORK/models/multilingual" \
  --output "$V6_FORMAL/routers" \
  --seeds 1103 1109 1117 1123 1129
```

该步骤只使用 training／selection 语料。输出保留各 seed 的全部候选、校准网格、选择结果、参数、特征缓存和训练成本。多个 seed 共用同一套语料，且当前分类头的求解具有确定性；这些复现不能解释为独立语言人群样本。

### 4.2 准备记忆快照并封存

```sh
python "$V6_ROOT/prepare_run.py" prepare \
  --routers "$V6_FORMAL/routers" \
  --encoder-cache "$V6_WORK/models/english" \
  --encoder-cache "$V6_WORK/models/multilingual" \
  --plan "$V6_ROOT/PROTOCOL.json" \
  --output "$V6_FORMAL/run"

python "$V6_ROOT/prepare_run.py" seal \
  --run "$V6_FORMAL/run" \
  --output "$V6_FORMAL/FREEZE.json" \
  > "$V6_FORMAL/freeze-identity.json"

V6_FREEZE_SHA256=$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' \
  "$V6_FORMAL/freeze-identity.json")
```

`prepare` 创建声明 seed／domain 的来源、真实训练的记忆参数与成本回执；`seal` 绑定已准备资产和已提交的执行代码。二者不读取 held 措辞。封存不可静默覆盖；若需要改变实现、数据、候选或阈值，应建立可追溯的新一轮实验，不能复用旧封存宣称仍是原来的评估。

### 4.3 打开 held，执行并审计语言实验

```sh
python "$V6_ROOT/run_language.py" \
  --run "$V6_FORMAL/run" \
  --freeze "$V6_FORMAL/FREEZE.json" \
  --freeze-sha256 "$V6_FREEZE_SHA256" \
  --held "$V6_ROOT/held"

python "$V6_ROOT/audit_results.py" \
  "$V6_FORMAL/run/evaluation/records.jsonl" \
  --held "$V6_ROOT/held" \
  --plan "$V6_FORMAL/run/execution_plan.json" \
  --output "$V6_FORMAL/language-audit.json"
```

held 只在封存验证成功后由正式 runner 打开。评估中的期望值与来源用于独立评分，不进入 router 或 cell 的服务输入。该 runner 使用新输出目录且不支持静默 resume；中断或失败的目录应保留，不能删除失败后只报告成功重跑。

原始逐条记录位于 `run/evaluation/records.jsonl`；执行成本、逐 case 成本和完成标记分别位于 `COSTS.json`、`CASE_COSTS.json`、`COMPLETE.json`。审计检查标签、数值摘要、来源、版本和记录完整性。`audit_passed` 与性能验收 `primary_joint_gate` 含义不同，不能用一个成功退出码代替全部质量门槛。

### 4.4 执行学习、结构、迁移和多节点生命周期实验

```sh
python "$V6_ROOT/run_extensions.py" \
  --plan "$V6_ROOT/PROTOCOL.json" \
  --output "$V6_FORMAL/extensions"
```

该入口同样要求执行源文件匹配已提交版本，依次运行协议声明的每个 seed；失败会写入对应 `FAILURE.txt` 并保留进度。总账为 `extensions/EXECUTION.json`，各 seed 下分别包含 `learning`、`transfer`、`lifecycle` 目录。

learning 记录实际训练、新写入、修订、撤销、回放与干净重建；no-replay 对照固定输出 catalog，原始参数干扰与支持域拒绝分开计算。结构训练候选包括 refit（K=1）、fixed-2/4、split、merge；另支持来源 frontier 不变时零训练 keep，以及可重新加载的休眠状态。旧地址 retention、selection 与最终 test 分离。自然成本和同参数字节上限都要检查，完整搜索成本及预声明调用量的回本判断不能由单个候选的读取成绩替代。强固定基线有意豁免其模型选择搜索费用，属于乐观对照，详见 RESULTS。

多节点实验使用本机 HTTP 进程、独立文件、真实进程退出／重启、显式来源回放与完整 bundle 重新分发。当前自动分布式撤销、跨主机部署与一致性协议仍需生产实现；尚未接到新版本的独立副本可能继续提供旧的自洽视图，实验会把这一阶段单独记录。

## 5. Typed DAG 和分工迁移覆盖的范围

[v6/transfer.py](v6/transfer.py) 从机器生成的结构化表达式自动推导 typed DAG，校验输入输出类型并去重依赖。图层注册 `apply`、`difference`、`sum`；程序层继续使用前述五种固定 opcode。因此可以组合“历史事件应用新版本程序”“两个时间或实体的事件差再应用程序”等任务，无需为每个实体重新手写整张图。

general／current／archive／revision 专家的能力范围预先声明；其 semantic 和 procedure cell 由真实参数训练获得。路由器从独立 selection 上各专家的实际正确性与工作成本学习分配，输入只包含图结构和时间上下文特征。新增域写入后重训专家，路由器保持冻结，再测新的任务组合。对照包括通用专家、selection 选择的固定分配，以及仅据公开能力与成本进行分配的强固定 scheduler。

这说明的是**结构化任务语法内的分工迁移**。新的领域关联需要先写入，新的图组合限于注册类型和算子；专家能力范围也没有被自动发明。CLI 的六种自然语言操作不因这个实验而自动扩展，当前没有从自由文本发现任意新意图、发明新记忆类型或形成通用自组织记忆系统的承诺。

## 6. 能力与现有 owner 的接入位置

| 能力 | 当前可运行实现 | 现有 Hepta owner／生产接线位置 |
|---|---|---|
| 类型化请求与读回 | `v6/contracts.py`、语言 router、`MemoryRuntime` | `hepta-cognitive-types` 和 `hepta-memory-retrieval` 已有 native 边界；产品请求生命周期还需调用它们 |
| 事件与来源权限 | qualification `EventStore`；校验 scope、entity、kind、cut 和撤销 | 真实 `CognitiveStore`／`hepta-memory::cognitive_retrieval_adapter` 需绑定当前 owner、身份与最终使用时验证 |
| 参数记忆与推理组合 | `v6/cells.py`、`v6/values.py`、`v6/runtime.py` | 对应 neuron runtime、inference control、cognitive read/store 的生产调用与能力边界尚待接线 |
| 训练、回放和发布 | `LearningSession`、不可变 artifact、SQLite CAS bundle | learning operator／ledger／artifacts 需接管训练授权、完整资产和 release／rollback 生命周期 |
| 分裂、合并、休眠和竞争 | `EvolutionController` 的离线 successor proposal | learning plasticity／eval 需消费评估与预算证据；服务中不会直接突变 topology |
| 多节点读取与迁移 | `v6/network.py`、`v6/lifecycle.py` 的 qualification 进程与节点目录 | organ／TaskFlow 的调度边、租约、网络认证及生产一致性尚未接通 |
| 进入上下文 | native bridge 调用现有 context compiler，并保留 `UntrustedEvidence` | 仍需真实 owner adapter、V2 admission、实际 tokenization 与 provider delivery |

native 库契约、qualification 调用者与完整产品调用链应分别验收。参数预测及其依赖摘要不能替代真实 owner 的权限与新鲜度证明。生产接线的准确边界以 [native/INTEGRATION.md](native/INTEGRATION.md) 为准。

## 7. 如何阅读结果与成本

正式结论统一记录在 [RESULTS.md](RESULTS.md)。阅读时应同时查看覆盖率、错误接受、拒绝、来源正确性、版本一致性和失败恢复，并核对所有候选、catalog、共享 encoder、回放来源、旧版本、路由、通信与迁移成本。

报告中的 arithmetic work proxy 是公开计算规则下的工作量代理，不等于实测硬件 FLOPs、能耗或货币成本。回本数字是使用冻结价格系数的情景投影。结构化合成任务、同作者语言样本及多 seed 复现也不构成人群泛化证明。若完整成本不优于强固定结构，或学得分配不优于固定 capability scheduler，应保留该负结果。

已有开发过程的完整性在证据包解压后的 `development/` 各项 `ACCOUNTING.json` 或对应记录中说明；部分早期临时产物没有保留，无法恢复的历史逐 fit 成本明确记为未知。正式 runner 的持久账本和开发历史账本应分开报告，不能把后来的复现实验当成之前缺失历史的恢复。
