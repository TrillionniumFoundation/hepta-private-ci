# 原 Root producer、resident admission 与 PR #5509 的扩域审计

固定生产源码：`48844493c046fdd79734ddd2c1866314023a15cb`，tree `360375952ff4fa51e817f2c773e5a5bc2a842a27`。本报告补充 [普通入口 custody 图](ordinary-bootstrap-custody-map.md)。全部文件 pins、完整搜索规则与命中在 [机器审计](upstream-caller-and-pr5509-audit.json)。本提交只增加证据，不改变生产 Rust、权限、lease、key、执行门或 PR 分支。

## 结论及准确范围

**在本报告列明的固定源码与旧实验中，尚未找到把真实 T/E/Model/S/Version/Observer custody 交付到普通启动入口的原 producer，也未找到可直接授权独立 B 在采用前执行候选的既有 E-only task capability。** 这是对已审源域和原实验输入的结论，不是对整台主机或仓库外部署的存在性判断。本次普通 A、独立 B、采用、新会话 C、daemon/Root 冷重启验收仍全部为 0。

现有 Root checkpoint sender 和原 issuer 均有真实实现。缺口是当前启动收到的能力类型与 resident/stage owners 所需输入不同。原 issuer 的 policy、lease 和 signer 必须来自真实原持有者；checkpoint 数据、Root pidfd、一般操作授权和旧实验材料不能补齐这些能力。

## 实际读取范围

| 范围 | 读取及校验 | 可支持的结论 |
| --- | --- | --- |
| Agentd src | 全部 926 Rust，9,402,011 字节；完整 body 与 tree/API/独立 Git blob SHA1 一致 | 普通入口和全部 Agentd 内部 caller 的精确符号搜索 |
| Workspace 依赖 | root Cargo.toml 与全部 187 个 member Cargo.toml，逐文件 Git blob 验证 | 外部直接依赖 Agentd 的只有 infer-worker-host 与 matrixd；不等于扫描全部 workspace Rust |
| 相关实现、脚本及文档 | 856 文件、10,926,175 字节；13 个未截断 tree 内的显式 catalog | 相关 crate、Agentd 非 src、scripts/tools 与选定部署文档的调用检索 |
| 配置与历史记录 | 同 13 个 tree 内额外 96 个匹配部署/配置名称的文件，共 663,934 字节 | 检索专用入口；具体 host locator 均来自历史 acceptance/fixture |
| PR #5509 | 固定 head 的 18 份文档/JSON/runner，加实际 f070 的两份 Rust 文件 | 旧模型与 Root handoff 实验的执行及权限范围 |

Rust 搜索先屏蔽注释和字面量并保留位置，再区分定义、调用、导出和 fixture；非 Rust 文本使用原文搜索。一个 fetch_file 首次失败由同 SHA 的完整 Git blob 读取补齐并记录。最终清单全部验证完整。未运行 Python verifier、全量 typed caller scanner、Rust 编译或 native；这些搜索不称为上述检查通过。

两个外部直接依赖的生产引用为 AgentdClient、HealthSnapshot、AgentRunPhase、SessionTransport 与进程身份常量，未引用学习 owner/enrollment。[infer-worker-host](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-infer-worker-host/src/native_app_server.rs) · [matrixd](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-matrixd/src/runner.rs)

## 上游调用链的实际边界

### checkpoint producer 已存在

原 hepta-authority-host CLI 的 register-learning 调用 checkpoint 注册；serve-session/serve-fresh-session 打开同一注册、seal learning bootstrap，并在 ready 回调真实调用 send_root_learning_handoff。这是生产 caller。它只交付 sealed bootstrap File 与同 Root pidfd；receive 校验、连接并 restore checkpoint 后存入 AgentdRootLearningInputsV1，没有 T/E/S/Model/Version owner 或 resident admission stream。require_root_learning_assembled 的拒绝必须保留。[原 CLI](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-agentd/src/bin/hepta-authority-host.rs) · [handoff](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-agentd/src/root_production_learning_handoff.rs) · [普通 receive](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-agentd/src/production_launcher.rs)

### 原 issuer 存在，resident 仍需独立的已批准授权

DeploymentFinalUseIssuer::issue 按原 pinned lease、subject/destination/scope policy、原 epoch、durable sequence 和窗口签发；本次没有调用签发或初始化。Resident profile 使用 runtime.learning.resident-admission.v3 与 runtime.learning.resident-readback.v3 两个明确 purpose，构造器要求已签原 intent 和已注册 exact-purpose lease。admission_binding 只计算规范绑定；hold_original_resident_intent_v3 只在原 issuer fence 内核验已有签名、序号、revocation 和时间，不创建授权。[原 issuer](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-agentd/src/deployment_issuer.rs) · [原 lease fence](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-agentd/src/deployment_issuer_root.rs) · [resident profile](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-agentd/src/authority_host_learning_resident_profile.rs) · [intent verifier](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-agentd/src/deployment_learning_resident.rs)

register_host_resident_learning_v3 只从原 config 重开同一 Root issuer、Registry 与目录。Agentd 内该符号共五处：定义、两处导出、两个 Root fixture 调用；扩域没有额外命中。服务的 register_resident_learning_v3 只有定义，原 CLI 没有 resident 注册命令。[open-only registration](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-agentd/src/authority_host_resident_registration.rs)

### Supervisor 不产生学习角色能力

PrecreatedProcessDriver 给已 pin 的原子进程交付确切 SpawnSpec，并可移交一个预先持有的 startup descriptor。其唯一 Agentd with_startup_descriptor caller 是 finite native G2 supervisor；完整 Agentd catalog 中所有 native_g2_entry Rust 文件均没有 learning/resident token。一般 UnixProcessDriver 启动原配置 command 与身份，没有构造学习 owners。这个机制不能把一般进程启动描述符解释为 T/E/S/Version custody。[precreated driver](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-supervisor/src/precreated.rs) · [原 Agentd 调用](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-agentd/src/native_g2_entry/supervisor.rs) · [Unix driver](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-supervisor/src/unix.rs)

### 最终消费点尚无原生产交付

以下每个符号在全部 926 Agentd Rust 中为 1 个定义、0 个调用、0 个其他引用；856 个扩域文件和 96 个配置文件也没有这些符号：

| 边界 | 定义 |
| --- | --- |
| checkpoint stage assembly | config_root_learning.rs::with_root_learning_stage_owners |
| resident opt-in | config_resident_learning.rs::with_root_resident_learning_enrollment |
| 原 Root enrollment | resident_learning_delivery.rs::enroll_original_root |
| resident admission stream | authority_host_learning_resident_transport.rs::from_original_root_stream |
| resident readback stream | 同文件 recover_original_root_stream |
| Candidate stages → resident runtime | authority_host_learning_resident.rs::into_candidate_runtime |
| E host 实际 T 首读晚绑定 | neuron_cell_evaluation_host_training_readback.rs::into_host_from_original_training_readback |

run_original_resident_delivery 有条件地由 runtime 调用，但不存在的 config delivery 不会因工厂类型存在而安装。T/S/Version 的原 custody 工厂和 Ready-only 晚绑定同样只证明机制，不能证明普通部署。先前 owner → purpose stream → consumer 图继续有效；本报告扩大的是搜索域。

## PR #5509 的固定证据

### 原输入没有声称提供生产 custody

读取时 PR #5509 是 open draft，未 merge，固定 head 为 `71738345326b98d88b738250d2b84ecbcb466eb8`。其 INPUTS 的 production_materials 四项均为 null：model_and_selected_current、authorized_source_frontier、original_root_writer_and_capability、generator_evaluator_selector_observer_owners。原说明明确不能用测试 keys 或 research receipts 替代生产材料。[INPUTS](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/71738345326b98d88b738250d2b84ecbcb466eb8/qualification/cell-common-20261109-e1c98/INPUTS.json)

### 真训练与 NoUpdate 属于 research component

准备 runner 的 execute 选择 actual_smollm_training_no_update_native_next_use_and_cold_readback。实际运行 f070 的该 Rust 测试调用 run(ResearchFlow::RetainedOnly)，使用 research host fixture，external_owner=None。它没有把独立 owner 装配进普通 daemon。[原 runner](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/71738345326b98d88b738250d2b84ecbcb466eb8/qualification/cell-common-20261109-e1c98/actual-model-no-update/execution/prepare_and_run-v2.py) · [实际运行 Rust](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f070113bb61cda492d2668b3afbbcda13e11fa52/codex-rs/hepta-agentd/src/neuron_generation_real_learning_tests.rs)

该次真实训练执行 10 个 optimizer steps，父版本 3/4、候选 1/4，正确选择 NoUpdate；后继不同输入实际使用父版本 forward。原 SUMMARY 同时记录 independent=false、independent_confirmation_tasks=0、candidate_adopted=false、daemon_os_restart=false。新 worker 进程和 owner reopen 不等价于 daemon/Root 冷重启，也没有提供本次独立 B 执行授权。[原 SUMMARY](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/71738345326b98d88b738250d2b84ecbcb466eb8/qualification/cell-common-20261109-e1c98/actual-model-no-update/SUMMARY.json) · [scope review](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/71738345326b98d88b738250d2b84ecbcb466eb8/qualification/cell-common-20261109-e1c98/actual-model-no-update/SCOPE_REVIEW.json)

### Root handoff 为同进程真实存储与传输

f070 的原 Root 测试声明 synthetic scope，通过 learning_test_support 取得 fixture；Root 和 consumer lifetime 使用同一进程身份，send 与 receive 位于同一函数。真实 CAS、sealed fd、SCM_RIGHTS、pidfd 和 reopen 的结果保留，但没有独立部署的 consumer/stage actors。原 SUMMARY 明确 independent_actor_custody=false、deployed_non_root_consumer=false、daemon_os_restart=false、ordinary_P0_chain=false。[实际 Root 源码](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f070113bb61cda492d2668b3afbbcda13e11fa52/codex-rs/hepta-agentd/src/authority_host_learning_registration_tests.rs) · [Root SUMMARY](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/71738345326b98d88b738250d2b84ecbcb466eb8/qualification/cell-common-20261109-e1c98/actual-root-handoff/SUMMARY.json)

/var/lib/hepta-common-e1c98-root-test-f070113b 是原 Root fixture 私有测试目录；审计导出不成为新 capability。旧 host 是 ai395，源和研究目录在 /home/qq。原 model unit hepta-runtime-job-1a1c0435e71-5e21-994 的当次终态读回是 LoadState=not-found / ActiveState=inactive，范围内无匹配 worker。这个历史记录不能替代今天 desktop 的状态。[原 PLAN](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/71738345326b98d88b738250d2b84ecbcb466eb8/qualification/cell-common-20261109-e1c98/actual-root-handoff/PLAN.json) · [原 process readback](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/71738345326b98d88b738250d2b84ecbcb466eb8/qualification/cell-common-20261109-e1c98/actual-model-no-update/PROCESS_READBACK.json)

本次没有证明 ai395 与当前 desktop 的部署映射，也没有找到可据以读取的现存 T/E/S/Version unit/config 身份；未探测未知主机目录，未读取环境、令牌、私钥或无关 argv。Root runner 的 gzip 与大型权重/archive 未解压；结论来自逐字验证的原 runner、Rust 源码和机器 evidence，不声称读取那些二进制原件。

## 真正可实施的原交付

1. 原 task/version host 交付已授权 PublishedCircuitFeatureTaskV1 与实际 Circuit/Cell/Source/inference 所有权，在 ordinary config 安装 Q24 task profile。
2. 原 T/E/Model/S/Version/NextUse/Observer hosts 保留各自私有文件、witness 和 key，交付已经连接、同 peer、held pidfd、原绝对期限的专用 stream。
3. 实际 A 完成后，原 Root issuer/Registry 使用已经批准的 resident intent 与 exact-purpose lease，消费上述实际 stage owners 注册并启动 resident runtime。
4. 原 trusted launcher 交付真实 Root resident stream、peer、pidfd、profile/verifier；ordinary config 的 enrollment 消费 opaque client，既有 delivery 才能加入真实 A outbox。
5. 原独立 B executor 持有候选评估执行能力并完成真实任务与保留面板；E provider 读原完成证据，S/Version/C 继续使用各自原授权。

当前 receive 输出没有完成这些步骤的实参。新增一个无人调用工厂、集中角色 keys、从 checkpoint DTO 派生 custody 或用 OS root 补权限都不能构成普通验收。本次不增加生产接线代码，保留所有拒绝门。找到真实原 launcher/owner 交付后，必须把其实际源码、instance 身份和 capability 绑定纳入同一固定候选，再执行普通闭环。
