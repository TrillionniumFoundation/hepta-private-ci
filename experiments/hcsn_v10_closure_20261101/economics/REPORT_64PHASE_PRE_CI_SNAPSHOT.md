本轮当前完整本地账户为 **2103.114801 CPU 秒、64 条阶段收据**，包含固定384世界确认、失败尝试、全部拟合候选、补核和最终账本审核尾部。全部声明的本地研究生命周期均已覆盖。完整执行经济性仍为 **HOLD**：外部CI待核验，历史准备、精确内存与可归因能量尚未完备。

每个阶段只将唯一外层 wait4 CPU 加入账户；内部任务、观察器和模型分项计时已经包含，不再相加。外层覆盖子计量器解释器启动/导入/能力检查、研究命令、普通可等待后代、采样和内部收据写出。源码编辑、工具传输、最外层CONFIG/源码快照及最终摘要序列化在边界外，不作整个开发历史成本完备的声明。

| 本地研究生命周期 | 必需互斥阶段 | 已覆盖 |
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

阶段覆盖按各study的active输出目录核对；development001旧版准备/测试费用保留，但不借它们填development002缺项。常数0.5参考另立av_constant账户，是train/validation诊断激发的事后补充，未替换原B/PLAN/FROZEN，也不冒称新的预注册独立确认。publication只验证11个输入与PLAN的字节复制，不训练模型、不作科学通过。

| 范围（含失败和前置复核） | 已测互斥 CPU 秒 | 非成功退出阶段 CPU 秒 |
|---|---:|---:|
| av_analytic | 247.109272 | 4.693529 |
| av_constant | 6.263588 | 0.000000 |
| av_interface_supplement | 5.422386 | 0.000000 |
| av_target_diagnostic | 0.268563 | 0.000000 |
| ci_capability | 0.175411 | 0.000000 |
| economics | 0.580310 | 0.000000 |
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

LEDGER005.json审核了63条已完成阶段收据，567项阶段身份/算术检查、16项控制上界检查及并发合同全部通过。审核自身退出后才能取得的0.137725 CPU秒另由SUMMARY.json加回一次；因此最终为64条收据，而不是遗漏这条尾部的63条。失败只指进程阶段非成功退出；科学负结果的全量运行费用也全部计入。AV首次因果测试失败4.693529秒已包括。最初计量器路径初始化在Popen前失败，CPU未知，保留原源码与INITIALIZATION_FAILURE.json。

固定确认模型不变，192 worlds/condition共384，8片全部完成后一次汇总；matched双primary使用97.5% crossed-bootstrap，mismatch为次要95%。八片CPU合计1300.307611秒，实际首片启动至末片收集窗口631.716058秒，峰值并发恰为6。各片重叠wall合计3007.502080秒仅作诊断，未当elapsed。实际窗口约10.53分钟，诚实保留超过原估计的事实；未据中途效果改变规模。CONFIRMATION_BATCH_COST.json和账本均从同机monotonic阶段边界重算该窗口。

本地硬件核验实际创建私有子cgroup返回EROFS，cgroup2挂载只读。powercap/hwmon/drm、GPU设备、perf电源事件接口和MSR设备均未暴露。根代理额外插件搜索未取得可直接提供本任务精确能量或独立cgroup的现成执行器；搜索范围有限，不是整个插件目录不存在其他服务的证明。没有改动宿主限制或绕过网络。

两个闭合控制进程树包含父、子、孙、短命任务、收养及32MiB共享页面；短命任务另外触碰48MiB，其驻留采样缺失仍有最终wait4高水位。完整逐进程清单支持保守上界sup_t ΣRSS_i(t)≤Σsup_t RSS_i(t)≤ΣH_i，两个数值为317,775,872与270,446,592 bytes。共享页和后代高水位重复只使上界更松，不使它成为同时峰值。这只给闭合夹具资格，不给任意研究命令或生产任务完整内存上界。MEMORY_BOUND_SCOPE.md保留公式、范围与主来源。

确认审核期间新增CI dispatcher，使原报告结束磁盘driver hash与启动snapshot不同。原JSON、前后driver和数值checker快照全部保留；CONFIRMATION_IDENTITY_NOTICE.json独立核对仅CI分支变动、confirmation/renewal数值checker未改。新driver已取启动快照hash；本轮sidecar费用已计入，未重复整个384数学重构。

外部GitHub Actions run 41371500148、workflow404015454、preliminary source4ccada8d893a5471a39fec998fb3d14fc9728116截至此快照为queued/pending。未纳入本地CPU总和，runner CPU、checkout/pip准备与设备能量均为unknown/null，不得当0。只在真实run成功且raw kernel receipt、source identity和独立重构都可核对后，才升级对应内存profile；一个memory.peak也不能替代整个CI费用。

此前Library下载、ZIP提取、manifest/远端树比较、843个历史v3文件恢复及首次初始化失败未被这套正式阶段计量，分别保留null；正式audio prepare不覆盖它们。v5/v6历史训练和准备成本亦未恢复。精确本地独立族峰值、可归因设备能量和这些历史责任仍缺；阶段收据完整不代表经济采用门通过。

此前47阶段750.269645秒保留为SUMMARY_47PHASE_SNAPSHOT.json及REPORT_47PHASE_SNAPSHOT.md；当前主入口为SUMMARY.json、LEDGER005.json、CONFIRMATION_BATCH_COST.json与LIFECYCLE_SCOPE.json。后续如外部CI工件到达，本地独立审核会新增阶段并更新当前总数。
