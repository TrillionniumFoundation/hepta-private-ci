# 真实模型 NoUpdate：不同输入、选定父版本与冷读回

本次 **一个实际模型尝试通过研究组件的运行机制检查**：source 产生真实输出，执行一次局部 LoRA 训练和真实评价，协议作出 `NoUpdate`，内容不同的 next 任务真实使用保留的父版本；重新打开 owner 并启动新的 worker 后仍读回同一结果。它使用 **Cell scoped V2 的组件边界**，不是无 scope 的 legacy 运行。

这次 source 的答案错误，next 的答案正确。测试 PASS 不代表两题都成功，也不代表训练有收益。完整普通 daemon P0、独立科学评价、两 tensor 训练授权、Parameter V3 owner 准入和生产 activation 均未取得资格。此次原始结果保留 `qualification=HOLD_NO_GO`，科学状态继续 **HOLD**。[CURRENT](CURRENT.json)、[精简索引](SUMMARY.json)、[原 native 结果](native-result.json)

## 1. 唯一实际运行与固定材料

| 对象 | 本次绑定 |
| --- | --- |
| source commit | `f070113bb61cda492d2668b3afbbcda13e11fa52` |
| source tree | `068b6a7749e94d7335c826d6c43c19198e02cc24` |
| operation | `learning-common-e1c98-model-no-update-002` |
| 实际执行 job | `1a1c0435e71-5e21-994`，succeeded / exit 0，durable output complete |
| native 结果 | 1 selected PASS；1555 项被 filter 跳过；Nextest 45.388 秒；无重试、无超时 |
| 模型 | `HuggingFaceTB/SmolLM2-135M-Instruct` |
| revision | `12fd25f77366fa6b3b4b768ec3050bf629380bac` |
| 基座文件 | 269,060,552 bytes；SHA-256 `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c` |
| 输入 profile | `distinct-source-next-v2` |
| 数据暴露 | 4 个训练行；每版本 4 个评价行；既有任务、材料及结果均已曝光；独立确认任务为 0 |
| 状态协议 | 原 checkpoint codec `HEPLCP02`、profile 2、Cell V2 frozen binding；研究 owner/custody |

模型执行前置的同源 helper、八库、Matrix SDK、agentd binaries 四门均已通过，其原始 receipts 被准备器逐一验证。执行仍经过原 `just test --archive-file` 入口，保留 `--no-tests fail`、0 retries 和原 60 秒 Nextest watchdog。准备时记录八个测试 binary 的原件与 archive 解包后的 SHA，并逐一相等。[准备结果](preparation-result.json)、[工具绑定](tools.json)、[启动与终局记录](PROCESS_RECEIPTS.json)

本次运行的外层 command record 在执行前后都记录 f070 的 HEAD/tree 和空 `git status`。随后发生的 lint/fmt 维护不属于本次已测试 tree；证据晚于维护提交不改变这一绑定。67 个外置模型、历史材料、运行源码及 recorder pins 在准备前、执行前和执行后都一致。它们与共同候选 Rust 源码的 HEAD/tree 检查是两个层次，不能用维护后的工作树替换执行时的源码证据。[材料绑定](INPUT_BINDINGS.json)、[67 项后验原件](MATERIALS_AFTER.json)

## 2. 真实任务输出、学习和选择

| 阶段 | 实际内容 | 原始输出 / 结果 | 解释 |
| --- | --- | --- | --- |
| source | `Answer with only yes or no. Is 135 greater than 134?` | **`no`，错误**；一次真实 forward | source 来自已曝光训练行；不具备独立评价资格 |
| training | 从已固定父 adapter 开始，candidate LoRA recipe | 一条 `train` journal action，10 optimizer steps | 产生 generation 2 的新权重，但没有采用 |
| evaluation | 同一组 4 个已曝光研究问题，分别评价 parent/candidate | parent **3/4**；candidate **1/4**；8 次实际评价 forward | 评价结果不支持学习收益 |
| selection | 原协议处理实际评价 | **NoUpdate**，保留 generation 1 | candidate 已生成和被评价，NoUpdate 不是零步骤占位 |
| next | `Answer with only yes or no. Is 8517 greater than 8516?` | **`yes`，正确**；一次真实 forward | 真实加载并消费选定的父 artifact |
| cold readback | 相同 next request 的保存结果 | **`yes`**，同一 output tensor；新增 forward 为 0 | 这是读回，不是又一次新题推理 |

这些 yes/no 是 `conditional_binary` 模式下从模型的 yes/no logits 取得的预测；本次没有把它升级为自由生成质量评价。[source 原件](source-observation.json)、[next 原件](next-observation.json)、[cold 原件](cold-observation.json)、[训练原 receipt](training-actual-receipt.json)

source 与 next 的冻结输入 SHA-256 分别为：

- source：`0e6247037b2885c4f09298b41ce7b4b5af7159b6cbd670155a978031664f7d9e`
- next：`bae2909d9687659d1c5f55865ab93c9f9bc4699c24fa90798c45d258fd38486d`

原输入文件、冻结映射、请求及后验比对均已保存，前后提示文本确实不同。旧的 `shared-next-prompt-v1` 历史运行不被追认为满足新合同。[source 输入](source-task-input.json)、[next 输入](next-task-input.json)、[冻结计划](frozen.json)、[后验绑定](OBSERVED_BINDINGS.json)

| 版本 | adapter digest | artifact 文件 SHA-256 |
| --- | --- | --- |
| 保留并实际消费的父版本，generation 1 | `e1a9ce940c9d4b04bb827490708604178d4e2391e7afd81a3ca63008389d1e53` | `a946c2cd7073092e607fb5ee3fd9b2dc78053ba5dc3d357a0a27c273ebbf95e2` |
| 已训练但未采用的 candidate，generation 2 | `6d3ad4295d628df7e5d0927f9044f46dd4375511b2788eeb1606a2cb6d48aa34` | `9ed906784ad969209386762f514ba2d209899c7180076d52306c268b7587e64d` |

## 3. 恢复到底证明了什么

next worker PID 为 `3041700`，cold worker PID 为 `3041823`。在新 worker 中重新打开 durable store 后，forward 计数 **1→1，增量 0**；idempotency-conflict 与 forward-budget 负向控制之后仍是 1。返回的 output tensor 和保留 artifact 与热执行一致。[hot 计数](hot-counters.json)、[cold 计数](cold-counters.json)、[恢复控制](recovery-controls.json)

native 组件重新打开 Learning/Generation owner、重建 fleet 生命周期，并核对完成 checkpoint 不变。完成 checkpoint SHA-256 为 `2947cce5746080ab276959001e4170399b6f5351d61729196edfd5c4293a7733`。原 native 结果明确记录 `native_daemon_os_restart=false`：本次不是整个 agentd daemon 的 OS 级重启。

完整 driver journal 的六个 action 顺序为 `prepare, probe, train, evaluate, probe, probe_recover`。只出现一条 train 请求，实际训练 receipt 记录 10 步及 10 个 loss；恢复没有新增 train action。**没有独立的 `training_invocations` 前后计数器**，因此不把 journal 和 receipt 改写成该计数器的观测值。原请求和进程终局均在完整 raw archive 的 `evidence/process-*` 中。

收集时仅按当前 UID、此次 operation 路径和已知 worker 标记扫描，未发现匹配的存活模型 worker。原 h job 的 systemd unit 此时已被移除；该次 readback 证明终局后的观察，不能重建运行中的 cgroup 属性。[进程后验原件](PROCESS_READBACK.json)

## 4. 实际训练对象、基座冻结与两种范围

本次训练对象是一个私有 Cell LoRA adapter。实际保存的 933,544-byte safetensors 含 **120 个 F32 A/B 因子、60 个 q/v 模块、rank 4、alpha 8，共 230,400 个可训练参数**，覆盖 30 层的 `q_proj` / `v_proj`。训练计划的 candidate recipe 为 `kind=lora`、学习率 `0.002`，实际 inherited child 只执行该 candidate 分支；计划中列出的其它 recipe 不是本轮已执行比较臂。[实际训练计划](training-execution-plan.json)、[范围审阅](SCOPE_REVIEW.json)

基座保持不变的证据包含三层，而非仅比较磁盘文件：

1. 固定 `llm_runtime_pilot.insert_lora` 要求可训练参数总量恰好 230,400，并要求所有 `requires_grad` 参数名称包含 `lora_`；`train` 的 AdamW 仅接收 `requires_grad` 参数。
2. 固定 `llm_inherited_runtime.child` 在训练后重算全部内存 backbone tensor 的 descriptor index root，要求等于原 contract 的 `index_root`。本次成功 receipt 保留该 root：`c320c094769446c21d7e4a33795d7f9310b5e4c8ca5a6fecca40207b1f735b7c`。
3. 外置基座文件及全部 67 个 material pins 在实际运行前后不变。

上述代码原字节连同 SHA-256 保存于 [scope-sources](scope-sources/MANIFEST.json) 的 gzip 中，便于独立审阅。基座大文件沿用 revision、现有 locator 和完整 hash，不重复复制。原 recipe 的其它分支不改变此次已执行 LoRA 分支的边界。

`frozen.model_config.allowed_patch_targets` 仅有 `model.layers.29.self_attn.v_proj.A/B` 两项。这一 allowlist 属于 **另一条 direct weight-edit worker 接口**：固定 `SmolLM2Provider` 用它约束 temporary patch、measure patch 与 export；export 要求 `DirectWeightEdit`、`gradient_steps=0`、`optimizer_calls=0`。其底层 provider 明确 `training=false`。本次 LoRA training 走独立 inherited trainer，不是该 worker 的 direct patch 操作。因而该两个名称不是此次 trainer 的两 tensor mask，也没有在此次运行中证明两 tensor 训练资格。

原 f070 `FrozenLearningScopeV2` 冻结 initial request/owners、Cell 标签和 update rule，对 Training observation 比较 `CellBundleComponentsV1`。Cell 可改变 cell_adapter、heads、calibration、composition，其余组件须保留；lineage 的 update rule 必须一致。**该结构没有 tensor 名称列表或 mask 字段。** 本次研究组装使用 adapter/contract 摘要进入这些组件；`RetainedOnly` 的 `external_owner=None`，没有调用原 external artifact owner 的 tensor/mask 准入。

因此本次可报告 **Cell V2 组件级 scope 通过**、实际私有 adapter 训练和基座冻结检查成功；不能报告两 tensor 训练授权、Parameter V3 资格或生产 owner 准入。这里也没有执行组织图分裂、合并、重连、迁移或搜索。

## 5. 两次准备与唯一模型尝试的成本

| 窗口 | 终局 | 外层 wall 秒 | 回收子进程 CPU 秒 | 子进程 max RSS KiB |
| --- | --- | ---: | ---: | ---: |
| preparation 001 | exit 1，模型未启动 | 10.683565 | 5.426981 | 273184 |
| preparation 002 | exit 0 | 11.121716 | 6.321698 | 273676 |
| 唯一实际 model | exit 0 | 46.179697 | 53.625113 | 3018300 |

准备 001 已完成 source/nextest archive，但 Nextest 0.9.103 的 binaries-only list 因 extract 目标目录尚未创建而 exit 96。外部准备器补齐两个目录创建语句后，使用全新的 operation/output 002 重新准备；没有重试模型，没有更改 f070 runtime 或原测试门。[成本明细](COSTS.json)、[h 原始请求及终局](PROCESS_RECEIPTS.json)

模型窗口中的 Nextest 45.388 秒、train action 23,476 毫秒、training child 19.406631 秒和 training stage 17.005017 秒是嵌套观测，**不能相加**。训练 child peak RSS 为 3,090,739,200 bytes；profiler 支持算子的 FLOPs 为 291,371,950,920，不是总工作量。外层 child max RSS 也不是同时存活的整棵进程树内存之和。

h 请求资源为 400% CPU、8 GiB、240 秒，原 native 单测试 watchdog 仍为 60 秒。嵌套历史 trainer 配置仍显示 16 GiB / 1800 秒 supervisor 预算，native training admission 为 90 秒；不把这些嵌套配置当成实际执行允许突破外层门。执行后的 systemd unit 已 `not-found`，其默认 `infinity` 字段不是运行时限额的证明。本 dossier 记录请求 envelope、真实 command window 和终局；没有声称取得运行中 cgroup 峰值快照。

父版本/基座历史训练、下载、此前 native 构建尝试、缓存准备和影响、operator/tool/传输时间、能耗、金额以及同时整棵进程树峰值仍未知或在其它证据中另记。完整端到端成本未取得资格，不作成本优势或净效用收益结论。

## 6. 全部原件与无执行的复核方式

[MANIFEST.json](MANIFEST.json) 绑定本目录除 manifest 本身之外的每个交付文件；Git commit 绑定 manifest。原始完整包为 **2,722,775 bytes**，SHA-256：

`1bb1860b53c32bdcbfe601a4be3240164c1faf7f0aacfb89d5b7455c5da942a1`

完整包包含 **212 个原始 payload 和 1 个内嵌 manifest**，包括新 candidate 权重、推理 tensor、checkpoint、原始 requests/responses、训练与评价原 receipt、两次准备日志和唯一模型执行日志。它以 `full/` 下七个有序、每个不超过 400 KiB 的分片纳入 Git；未改 blob allowlist，未删除远端或 scratch 原包。[分片顺序/长度/SHA](RAW_ARCHIVE.json)、[212 项原清单](RAW_FILES.json)、[传输与逐成员核验](BYTE_VERIFICATION.json)

`raw-metadata.tar.gz` 是方便审阅的小型子集，**不替代完整包**。`RESULT.json` 是只读收集器结果，不是模型第二次运行。`execution/` 两份 Python 是实际使用的外部准备/收集器原件，不是新增产品 API。四份外部范围源码以原字节 gzip 保存；source/nextest 大型构建 archive 及基座模型另有固定 hash 与远端 locator。所有结论仍绑定 f070，后续维护不继承本次执行资格。

以下在本目录运行，只读取和验证归档，不启动模型、不解包到既有目录：

```sh
python3 - <<'PY'
import hashlib, io, json, pathlib, tarfile
root = pathlib.Path('.')
index = json.loads((root / 'RAW_ARCHIVE.json').read_text())
parts, offset = [], 0
for part in index['ordered_parts']:
    data = (root / part['path']).read_bytes()
    assert part['offset'] == offset and len(data) == part['bytes']
    assert hashlib.sha256(data).hexdigest() == part['sha256']
    parts.append(data)
    offset += len(data)
raw = b''.join(parts)
assert len(raw) == index['archive_bytes']
assert hashlib.sha256(raw).hexdigest() == index['archive_sha256']
files = json.loads((root / 'RAW_FILES.json').read_text())['files']
with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
    for item in files:
        data = archive.extractfile(item['archive_path']).read()
        assert len(data) == item['bytes']
        assert hashlib.sha256(data).hexdigest() == item['sha256']
print('Verified complete archive and', len(files), 'raw payloads')
PY
```

后续若实施新的模型运行，须使用新的唯一 operation/output、重新验证 source/model/data/tool pins 及全部先决门。此档案本身不授权重放，也不授予普通 daemon、独立科学评价或生产 owner 资格。
