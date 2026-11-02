本轮当前完整本地账户为 **2124.153532 CPU 秒、67 条阶段收据**。两次真实远端CI均成功，其原始kernel收据和各30,720项预测已由本地独立重构核对；冻结回放的cgroup charged-memory peak分别为 **51,634,176 / 51,703,808 bytes**。完整执行经济性仍为 **HOLD**，尚不具备能量、远端全准备成本或部署全范围资格。

只将每阶段唯一外层wait4 CPU加入本地账户；内部任务、观察器和模型分项计时已包含，不再相加。外层包括子计量器启动/导入/能力检查、研究命令、普通可等待后代、采样及内部收据写出。源码编辑、工具传输、最外层CONFIG/源码快照和最终摘要序列化在边界外，不作整个开发历史成本完备的声明。

| 已完成本地生命周期 | 必需互斥阶段 | 已覆盖 |
|---|---|---|
| risk | prepare/validation/execute/audit | 是 |
| persistent_renewal | prepare/validation/train/execute/audit | 是 |
| persistent_renewal_extension | prepare/train/execute/audit | 是 |
| high_power_confirmation | prepare/execute×8/aggregate/audit | 是 |
| joint_retrain | validation/prepare/data/train/execute/audit | 是 |
| av_analytic | validation/prepare/train/execute/audit | 是 |
| av_constant | prepare/execute/audit | 是 |
| historical_audio | prepare/train/execute/audit | 是 |
| publication | validation | 是 |
| external_ci_review_41371500148 | audit | 是 |
| external_ci_review_41372584433 | audit | 是 |

阶段覆盖按active输出目录核对。旧版准备/测试费用保留，不借其通过填新版缺项。常数0.5参考是train/validation诊断激发的事后补充，未替换原B/PLAN/FROZEN，不冒称新预注册确认。publication仅验证11个输入与PLAN的字节复制。两组external_ci_review阶段仅表示本地工件审核，绝不表示远端准备/执行CPU已计量。

| 范围（含失败和前置复核） | 已测互斥 CPU 秒 | 非成功退出阶段 CPU 秒 |
|---|---:|---:|
| av_analytic | 247.109272 | 4.693529 |
| av_constant | 6.263588 | 0.000000 |
| av_interface_supplement | 5.422386 | 0.000000 |
| av_target_diagnostic | 0.268563 | 0.000000 |
| ci_capability | 0.175411 | 0.000000 |
| economics | 0.722578 | 0.000000 |
| external_ci_review_41371500148 | 9.591851 | 0.000000 |
| external_ci_review_41372584433 | 11.304612 | 0.000000 |
| frontend_review | 0.203673 | 0.000000 |
| hardware | 0.105367 | 0.000000 |
| high_power_confirmation | 1346.792961 | 0.000000 |
| historical_audio | 5.434654 | 0.000000 |
| joint_retrain | 37.017289 | 0.000000 |
| memory_bound | 0.584409 | 0.000000 |
| meter | 0.086077 | 0.000000 |
| package_inventory | 0.371828 | 0.000000 |
| persistent_renewal | 256.236275 | 0.000000 |
| persistent_renewal_extension | 179.779624 | 0.000000 |
| publication | 0.118547 | 0.000000 |
| review_driver_identity | 0.095534 | 0.000000 |
| risk | 16.469033 | 0.000000 |

LEDGER006.json覆盖66条已完成收据，594项阶段身份/算术检查、16项控制上界检查及六并发合同全部通过。审核自身退出后取得的0.142268 CPU秒由SUMMARY.json另加一次，因此最终为67条收据。失败仅指进程阶段非成功退出；科学负结果的运行费用全部计入。AV首次因果测试失败4.693529秒保留；最初计量器路径初始化在Popen前失败，CPU未知，原源码和INITIALIZATION_FAILURE.json保留。

固定确认保持模型不变，192 worlds/condition共384，8片全部完成后一次汇总；matched双primary用97.5% crossed-bootstrap，mismatch次要95%。八片CPU1300.307611秒、首片启动至末片收集窗口631.716058秒、峰值并发6。重叠wall合计3007.502080秒仅作诊断，未当elapsed。实际约10.53分钟，保留超过预估的事实；未据中途效果改规模。

远端实际收据与重构：

| Run / source commit | 回放charged peak B | 夹具charged peak B | 独立预测数 | 最大概率误差 |
|---|---:|---:|---:|---:|
| 41371500148 / 4ccada8d893a | 51634176 | 62148608 | 30720 | 1.11e-16 |
| 41372584433 / c555fcbcf0eb | 51703808 | 62148608 | 30720 | 7.22e-16 |

两件均由API独立取得的CI_PROVENANCE绑定success/completed和SOURCE_COMMIT；下载摘要/CRC、kernel receipt hash均保留。每件142个汇总数值字段也重算，first最大误差0，strict约2.22e−16。worker在exec前进入专属cgroup，初始peak=0，退出后家族为空且自有group清理成功，无OOM事件。空组后memory.current仍约4MiB的kernel/cache charge如实保留，不当0或异常。

这里的精确量是该冻结有限模型回放及后代的cgroup v2 memory.peak，包含kernel和被charge的page cache；它不是RSS/PSS、唯一物理内存，也不覆盖训练、真实AV、部署全范围或设备能量。strict run只闭合此明确profile的kernel峰值及数值回放资格。当前本地环境仍cgroup只读，私有组创建实际EROFS；无能量计数器/GPU/perf/MSR暴露。本地CAPABILITIES原始事实不因远端成功而改写。

远端runner CPU、checkout/pip/setup、下载及根CRC准备成本继续unknown/null，不计入上述本地总和，不能当0或由wall/memory.peak推算。两次本地独立CI审核CPU9.591851与11.304612秒已经加入；能源仍null。

两个闭合本地控制树覆盖父、子、孙、短命任务、收养与32MiB共享页；短命任务另触碰48MiB，驻留采样缺失仍有最终wait4。逐进程完整清单支持sup_t ΣRSS_i(t)≤Σsup_t RSS_i(t)≤ΣH_i，保守上界317,775,872 / 270,446,592 bytes。共享页和继承高水位重复使其更松；只给这些闭合夹具资格，不给任意生产命令完整内存上界。MEMORY_BOUND_SCOPE.md保存公式和主来源。

确认审核期间CI dispatcher新增使旧报告结束磁盘driver hash与启动snapshot不同。原JSON及前后源码均保留；CONFIRMATION_IDENTITY_NOTICE.json核对仅dispatcher差异、数值checker未改。新审核driver取启动snapshot digest；sidecar费用已计，未重复384重构。

此前Library下载、ZIP提取、manifest/远端树比较、843个v3文件恢复及首次初始化失败费用分别null；正式audio prepare不覆盖它们，v5/v6历史成本亦未恢复。阶段账户完整与一个外部profile成功不能升级完整经济采用门。

当前入口：SUMMARY.json、LEDGER006.json、LIFECYCLE_SCOPE.json、CONFIRMATION_BATCH_COST.json及ci_runs两件原始工件/下载验证。47阶段750秒和64阶段2103秒已作为历史快照保留，主报告已更新为本次67阶段账户。
