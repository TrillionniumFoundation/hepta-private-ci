# 同一个模型、同一次后续使用与完整成本

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
