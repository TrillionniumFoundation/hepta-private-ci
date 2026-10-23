# Final memory-cell boundary review — read-only, 2026-10-23

结论：四阶段的有界研究机制已实现并获得真实执行证据；长期通用 memory、自治生长网络及生产资格尚未成立。
本审阅只读 README、关键实现和已完成的结果；未修改仓库、未运行测试或模型。以下“已通过”均保留对应实验范围。

## Evidence map and source identity

- R = `/workspace/scratch/12ef9c5bdc23/hepta-memory-work`; inspected HEAD `d61a36e21d1ad6d90614c145455b88c647c430e8`，工作树干净。
- S = `/workspace/scratch/12ef9c5bdc23/system-development-trial-002`; `source-identity.json` 与 `source-identity-after.json` 相同，git_head=d61a36e；manifest_sha256=`9012d9747a689afa1138c931e04d1a33bd87f09cd9c20e612830a3c228febd2d`。
- D = `/workspace/scratch/12ef9c5bdc23/domain-development-trial-001`; `protocol.json.source_identity.git_head=a26aeb74cf63c7489deb5ece7e2b9a86e5697748`，是独立冻结的较早源码实验，不能改称 d61 执行。
- H = `/tmp/hepta-memory-runtime-hosted-checks`; `verification-summary.json`：d61 push/PR 各43/43（26 service+9 domain+8 network），同一套检查的两次运行。
- S/result.json SHA256=`42d2cda3478555fa08e7d5ef740f77098055495db3189de6c7ed41ba50e7faca`; D/result.json SHA256=`9890eaf1fd5e9bc00b977a2056ec70dadb9557d7794fdfe7faab98b40c48eb74`。
- 代码短文件名按章节定位：§1/Correction → R/scripts/memory_cell_service；§2–3 → R/scripts/memory_cell_domain；§4 → R/scripts/memory_cell_network；system_network.py 在 R/scripts/memory_cell_system。完整相对路径省略 R。
- 结果字段以 S 或 D 的 result.json 为默认定位。四阶段按本次交付的 source/parameter、domain、fission/router、network/integration 划分。

## 1. Typed source → trainable parameter service

- DONE — `(scope,cell_id,role)` 持久绑定；semantic/procedural 两角色、revision CAS、带值的 source digest、即时 overlay、durable outbox：`scripts/memory_cell_service/{service_types,source_store}.py`。
- DONE — source 写入不等训练；lease/attempt/staged candidate、旧 epoch supersede、owner activation 后 source binding 崩溃恢复：`training_queue.py`、`parameter_publication.py`。
- DONE — 真正 LoRA、immutable checkpoint/catalog、前后 source/version barrier；`memory_service.py.invoke_parameter` 保留 raw response，`origin=parameters` 且 `correctness_verified=False`。
- DONE — S/result.json：19/19 `engineering_gates`、6/6 `parameter_control_gates`；800 updates，49,400 input tokens，401.417 training seconds，555.595 wall seconds。
- DONE — S.metrics：initial adapter=9/9；base=0/9；shuffled=0/9；corrected=8/9；after_withdrawal=8/8。指定纠正项 case_00 的新值 white 正确。
- OPEN — 参数并非可靠事实库：S/corrected-network-read.json `journal.rows[5]` 将 case_05 的 white 读成 purple；0.75 准确率门槛允许该错误，不能改写成纠正后全对。
- OPEN — 长期准确性尚无证据：S/protocol.json 是单 seed=2718、最多9条合成事实、一次 correction/withdrawal、三次 clean publication；没有长时间事件流、跨种子或真实任务保留率。
- OPEN — 可信输入仍由调用方负责：`memory_service.py` 不验证外部 CI ledger；`source_id=ci/...` 只是标识；`invoke_parameter` 不验证 question 与传入 entity/relation 的语义一致。
- OPEN — 两种 role 共享 completion decoder；S 只创建 semantic。`scripts/memory_cell_service/README.md` 明示角色名不证明能力，procedural 尚不能等同于可执行的调试程序。

## 2. Natural CI-domain memory

- DONE — `scripts/memory_cell_domain/domain_data.py` 校验 failure→direct-parent fix→same-workflow success、唯一 run、原始 symptom 与文件 SHA；按整个 root-cause group/time 划分并保留原始证据。
- DONE — D 用真实预训 decoder 完成416 decoder updates、3次梯度 forward/backward、2×400 router updates；`executed-reads.json` 保留 raw text/token/checkpoint/timing。
- DONE — D/result.json `independent_source_groups=3`；single/expanded/split/random_split 的 known_recall 都3/3；parent=1/3；exact_source、BM25、TF-IDF、dense 两基线也都3/3。
- DONE — D/selection.json 在 final_outputs_seen=false 时选择 exact_source；选取规则允许检索获胜，避免强行挑 neural arm。
- OPEN — D 的 validation/future 均空，`missing_validation=true`、`missing_future=true`、`prospective_generalization_established=false`；多模板/额外 reads 不增加独立事件数。
- OPEN — 任务只是为原始已见 failure symptom 生成短 repair_id；D.future_policy_execution_evaluated=false，没有应用补丁、执行排错或后续任务成功率。
- OPEN — producer 只验证离线 export 的一致性，不能独立认证 GitHub export、previously_seen 声明或修复因果性：`scripts/memory_cell_domain/README.md` 与 `domain_data.py`。
- OPEN — synthetic_unknown 是人工“未记录 checksum”关系；exact_source 与两种 split 都3/3，不能据此声称自然 OOD 拒答能力；其他模型臂/模糊检索为0/3。

## 3. Data-driven fission, learned routing and fair budget

- DONE — `domain_training.py` 执行实际 source-gradient sketches、whole-group balanced split、seeded random split、rank4 continuation 与 function-preserving rank8 expansion；不是只生成计划。
- DONE — 两个 router 各1539参数、400次更新；`scripts/memory_cell_router/learned_router.py` 用 source-measured utility 学习 question→expert/reject；final routes 在 decoder 执行前冻结。
- DONE — D.costs.training：expanded/split/random_split 每臂96 updates、7,640 input tokens、1,843,200 adapter parameter bytes；single 同96/7,640但921,600 bytes。
- OPEN — 等训练曝光不是等总预算：D.costs.equal_total_system_cost=false；梯度、800 router updates、不同 inference/diagnostic/base 成本另计，runtime/OS、冷启动、能耗未覆盖。
- OPEN — 没有已证实 split 增益：已知召回四臂都3/3，gradient/random 两种 split 的未知结果同为3/3；D.capacity_advantage_established=false，3组不构成 capacity pressure。
- OPEN — D.split_and_random_partition_identical=false 仅说明分组不同，不能转化为 data-driven 分裂优于随机分裂的效果证据。
- OPEN — 部署字节上 exact_source=349,694，single=273,455,308，split=274,427,183，expanded=276,262,338；D.chosen=exact_source；D.costs.net_compression_established=false。
- OPEN — 完整3条 record 的 zlib=1,490 bytes，single checkpoint=969,192 bytes，另有271,170,520-byte shared base；这些不同口径只说明必须完整记账，不能宣称参数净压缩。
- OPEN — learned edges 尚未实现：当前 router 是固定专家列表上的线性 softmax；`network_client.py` 接收静态 nodes map；没有训练 cell→cell graph、跨类型边效用或路径信用分配。
- OPEN — 自治分裂生命周期尚未实现：`domain_training.py` 预设 single/expanded/split/random 四臂、一次两子分片；没有与 live service 队列闭环的增殖触发、递归分裂/合并和容量调度。

## 4. Logical identity, migration and network lifecycle

- DONE — `network_serve.py` 绑定同一个 MemoryService.authority_view；worker 经 HTTP 读取 frontier，source-root 不传给 worker，correct/revoke 不需手工 frontier RPC。
- DONE — `network_checkpoints.py` 搬运实际 lineage/config/safetensors 字节并核验 pin/layout/digest，目标独立目录；`network_authority.py` placement CAS 与幂等 retry。
- DONE — `network_worker.py` / `network_fences.py` 执行 placement、withdrawal 的前后 barrier 与持久单调观察；旧节点拒绝、authority outage fail-closed、restart 保持 fence。
- DONE — S.engineering_gates：independent_worker_pids、transferred_checkpoint_bytes_identical、fresh_and_network_generation_equal、live_source_withdrawal_reaches_both_nodes、restart/recovery 全 true。
- DONE — H 两次43项检查包含真实 child nonzero/timeout、worker被杀时 child停止执行、重启后同checkpoint/raw output；`model_child.py` Linux parent-death 绑定创建线程。
- OPEN — 这次迁移的是 executor/checkpoint：服务端 `(scope,cell_id,role)` 继续存在；wire placement 只有scope/cell/node/generation/pin/roots，不搬迁 source authority、训练队列或学习 graph。
- OPEN — 真多主机未实现：`network_wire.py.endpoint/server` 只接受/监听127.0.0.1；S/protocol.physical_hosts=1、S.multi_host_qualification=false；多个PID不等于多个物理节点。
- OPEN — “frontier 不传 source values”已成立；物理数据本地性未验收。`system_network.py` 在同一主机启动所有进程、共用base路径；没有源文件访问隔离或只在源主机训练的跨机协议。
- OPEN — Authority 是单可信 SQLite writer，无复制/共识/quorum恢复；`network_fences.py` 只能拒绝该节点已观察过状态的回退，不能恢复丢失的 authority DB。
- OPEN — CAS 后目标首次加载仍可有可用性间隙；base兼容性在 decoder load 时才核验：`scripts/memory_cell_network/README.md`；未测跨机分区重连、持续可用性或硬盘丢失。
- OPEN — 本地 HMAC key 持有者同时是可信 publisher/reader，无独立用户角色；HTTP无加密，代码刻意限定 loopback：`network_wire.py` 与该目录 README。

## Correction / withdrawal semantics that must remain explicit

- DONE — correction 撤回旧 revision root；revoke 禁止该 source_id 静默复活；多个同值来源可支持同一key，冲突key从训练快照剔除：`source_store.py`。
- DONE — Unknown/conflict/revoked 的零 callback 来自 source admission，不是模型学会拒答；in-flight source/version 改变会抑制响应：`memory_service.py.invoke_parameter`。
- OPEN — source history 与旧 checkpoint 留存；withdrawal 是使用阻断，不是磁盘擦除、数学 unlearning 或证明模型永不再输出同一字符串。
- OPEN — 当前重训固定 `fresh_base_all_current_unconflicted_sources`：`training_backend.py`；任何 source epoch 变化都会使整个旧 binding unavailable，需完整 clean replay 后恢复。
- OPEN — 由代码可推知，持续写入若快于完成重训会反复 supersede；没有在长期输入负载下证明稳定出版率、延迟或增量保留能力；S只验证一次中途新事件。

## Remaining acceptance ledger

- REQUIRED — 冻结协议的独立未来 root-cause/task cohort、实际执行任务收益、容量压力、多个独立组/种子的误差范围；以检索为可胜出的对照，而非只测已见字符串回忆。
- REQUIRED — 相同总资源约束下逐级证明 parameter→split→learned-connection 的增量收益；现有 costs 明确否认总预算相等，也未闭合净存储压缩。
- REQUIRED — 可信源接入与 typed-key/question 绑定、稳定长期写入/纠正/撤回准确性、跨角色实际任务能力；当前 research caller 约定不能自动升级为生产契约。
- REQUIRED — 真跨物理节点和数据本地性实现/验收，以及显式 authority 故障模型；不把本地TCP、进程重启或HMAC当作上述结果。
- SCALE LIMITS — source128 active/4096 revisions；owner/authority最多64 cells/scopes；wire96MiB、weights64MiB；serial HTTPServer、每次读取新建模型child、全量 replay：均为有界研究约束，未测吞吐规模。
- PLATFORM LIMITS — `durability.py.power_loss_recovery_verified=false`；Windows directory fsync、非Linux parent-death显式unsupported；观察child退出不等于本进程负责reaping。
- RELEASE CLAIM — 可发布为“typed trainable memory 的有界可执行研究栈”；S.research_target_status=not_established_by_this_mechanism_trial，S/D.production_accepted=false 应原样保留。
- Stop condition — 此审阅不要求改动已冻结源码；上述 OPEN/REQUIRED 是下一研究阶段的 blocker ledger，不能以本轮19+6门槛或hosted43项通过替代。
