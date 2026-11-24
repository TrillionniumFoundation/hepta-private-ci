# 同一个模型、同一次后续使用与完整成本

当前安全状态：生产授权验证暂停。下述流程中的原 SQLite-only 原生授权入口已关闭，
`--print-statement` 仍可生成声明；完整原线程运行时验证器尚未接通。历史与工程回读
不因此获得真人授权资格。具体迁移限制见本文末尾。

2026-11-24。本增量继续原 #7047 的受保护来源和普通因果语言模型 / 固定槽位 Circuit
路径。Q24 原生生命周期仍由其原验收门决定；两种模型的结果不能互相替代。

新增入口为 `PYTHONPATH=scripts python3 -m cell_experiments.paired_loop`。前三个位置
参数仍为原私有 `HOME_DIR ADMISSION MATERIALS`，第四个为命令。

1. `identity` 只读原登记，输出一次 loop identity 及其摘要。它绑定原 study、admission、
   freeze、父/候选模型、数据暴露、路由、模型运行参数、未来/保持面板、原生授权二进制，
   以及实际 Python 二进制、依赖版本和整份 Python 实现。第三方依赖目前只固定安装版本，
   其 `.py/.so` 完整闭包尚未固定，所以明确输出 `runtime_closure_complete=false`。
   同版本第三方包被修改的情况仍需镜像或文件清单门，不能称完整运行时资格。
2. 独立保留该摘要，随后使用 `select --expected-loop DIGEST` 运行原父/候选冷评。
   只有旧入口真实选出改善且保持旧能力的候选，才有完成记录。
   已有历史 selection 的登记被拒绝；不能给过去执行追加当前代码身份。
3. B 仍通过原接口生成和亲自提交声明；使用同一摘要执行 `run --task TASK --delivery DELIVERY`
   和 `report --task TASK --effect EFFECT --outcome accepted|rejected --delivery NEW_DELIVERY`。
   两者以及后续核对均需原 `--root-pid`、`--sqlite-home`、`--route` 和继承的 fd 3/4。
4. 执行 `verify-request --task TASK`，再执行 `verify --task TASK`。每条命令均传相同
   `--expected-loop`。后者重新核验原 B，输出不可覆盖的 loop readback。

这些新旁证有独立的 v1 命名空间，原签名消息和原件不改写。每个命令先落盘 STARTED，
失败也保留 CPU 和墙钟记录；已开始的命令不能由这个入口再次分发。中断后应检查原件，
该入口不自动重试或补授权。全部五个阶段完成但最终旁证写入中断时，可用
`readback --task TASK --expected-loop DIGEST` 只读重建，不重新执行，也不将过去的核验
冒充本次实时核验。更新代码、解释器、依赖版本、模型或路由将产生不同摘要。

每个 B 对同一父/候选能力的采用只计一个 improvement_id。工程身份计零；原登记与实时
B 授权提供的是站点见证的独立性，不能证明全球不存在同控或女巫。参与者接受与独立业务
效果仍是不同证据。此程序不发起交易，不授予结算或共识信用。

当前计量覆盖冷评、后续执行和授权核验，训练、失败搜索、分发、阶段间等待和外部服务
仍须接入原成本来源。阶段墙钟之和不冒充端到端 makespan。只要这些成本缺失，
`adopted_improvements_per_total_cost` 保持 null，不把缺失成本按零计入。

针对控制：`PYTHONPATH=scripts python3 -m unittest cell_experiments.test_paired_loop cell_experiments.test_paired_loop_process cell_experiments.test_paired_consumer_fresh cell_experiments.test_paired_consumer -v`。
测试重读原工程 ZIP，实跑失败子进程及保存的 GPT-2 权重，覆盖冷评、后续生成、报告、
独立读回、跨研究/请求/模型/冻结替换、实现变更、中断、重复分发、原件篡改与工程身份
误计。新动作的首次执行条件在原 consumer 锁内检查，竞争写入不能复用旧执行结果。
这些工程身份测试不是新增真人 A→B 实验。

本次 14 项全程通过，177.538 秒；原始输出见 `BOUND_LOOP_TESTS_20261124.txt`。

## 原线程授权边界的安全收口

审查 `9917930245b184cba7ded078221fe90a2335eab7` 确认，旧原生入口从调用者指定的
SQLite 读取 Acked 行，随后核验 Root 保留的人类签名；它没有调用原 Notes/Desktop
连接的 `verify_human_turn`。AuthBus 的 Acked 可以对应尚未进入原 turn 的排队记录，
所以它不能替代当前 Core 队列的 `ReconcileOnly`、同 turn 的 Persisted 确认，或附着
宿主前后的 replay checkpoint 同步。当前 Root 的签名、会话、权限修订及过期校验仍然
有效，但它们不能补出这些缺失的队列事实。

本安全阶段删除生产代码中的 SQLite 读取与直接 Root consent shortcut。旧
`ROOT_PID SQLITE_HOME ROUTE_JSON` 验证调用统一返回 `ORIGINAL_TURN_VERIFIER_REQUIRED`，
在读取 stdin、调用者路径或继承描述符前退出，stdout 不产生授权 receipt。
`PairedLearningDataUse::consent_text` 和合法 `--print-statement` 的协议字节保留。
原 `CALLERS.toml` 的两个 reader 集合与 Root verifier 集合没有扩大。
本地原 `python3 -B scripts/verify_hepta_callers.py verify` 完整门实际通过：
扫描 6,180 个 Rust 文件，核验 182 个边界和 166 个保护文件；`authorityGranted=false`。

新的进程回归传入实际 Unix socket 与 pidfd；另用未提供数据的 stdin 和 FIFO 路径
检查拒绝不会等待这些输入。开发 helper 仍真实签名、入库、确认并重开其工程 SQLite
原件，再以五种旧用途请求启动新版 CLI；它现在检查安全拒绝和 issuer 通道零请求字节。
这些结果只能证明拒绝行为，不能称原生授权成功、真人 A/B 实验或学习收益。
CI 安装原固定版本 just/nextest，选择非空的实际进程测试，并保留原隔离 helper 的运行。
执行成功与否仍以本次实际构建、日志和对应 source HEAD 的 CI 为准。

本轮 Python 迁移与工程回归共 29 项，191.444 秒，全部通过、零跳过；
[原始日志](CONSENT_BOUNDARY_TESTS_20261124.txt)保留各测试名称和实际退出结果。
它们覆盖生产旧授权拒绝及显式工程 fixture，不代表新版原生 CLI 已构建执行。
本地尚未执行新版原生构建、实际 socket/pidfd 拒绝测试及隔离 helper；这些门保持待验。
远端 `just fmt` 的回执未恢复，整体退出状态为 unknown。仅核对并应用了读回的
example 排版 postimage，其余七个当时所属文件字节未变，未把文件存在冒充 fmt 通过。

历史研究包 pin 的原生二进制仍具有旧身份及旧行为；原 archive、原请求及原失败不改写，
也不能借新版源代码修复而升级历史授权。配套 Python 迁移门对新注册与既有生产
`owner_intake` 上下文拒绝旧 native receipt，工程 fixture 则必须显式标明工程 scope。
上面的 14 项 fake-native Python 流程属于工程验证，真实授权人数和授权改善计数仍为零。
增加一个自称 `v2` 或 `authority` 的 JSON 字段不能证明原宿主或原 turn。

完整后续实现必须由已经安装的 Notes/Desktop 运行时持有原连接、seed、Session 和
不可克隆 adapter，执行有界只读请求、真实同 turn/队列/checkpoint 核验，并在返回前
重新核验同一人类授权及存活性。独立 CLI 不能仅凭 SQLite、Root fd 和自报 route
构造该证明。当前阶段没有启用这样的新生产 verifier，也没有产生训练、真人或付款。
