# V10 执行经济性：隔离计量器落地，硬件验收继续 HOLD

本阶段没有重复 v9 的只读 cgroup 创建探针。`CAPABILITY_SURVEY.json` 绑定
原探针 SHA，并补查其他可执行路径：当前工具表没有云环境状态或外层
容器/runner 执行接口；本机无 Docker/Podman 及其 socket，也没有 perf、
bpftrace、accton/lastcomm。`CapEff`、`CapPrm` 和 `CapBnd` 都为零，
`NoNewPrivs=1`。存在 `systemd-run` 二进制，但实际 user scope 调用失败：
`Failed to connect to bus: No medium found`。没有复用过去环境的登录、
设备或凭证状态，也没有重挂载 cgroup 或尝试提升权限。

普通进程 accounting 的累计 CPU 或单进程 RSS highwater 不能重建所有后代
同一时刻的内存峰值；求和 maxRSS 也不能解决这一问题。现有工具和主机没有
提供另一个可验证的完整族连续内存路径。可归因设备能量仍然缺失。

为具备委派权限的真实 runner 实现了 `cgroup_meter.py`，可直接执行真实
工作负载，默认不会创建模拟的成功记录：

- 明确接收已委派的 cgroup2 父路径，只在其下新建唯一空组；检查 memory、
  CPU、events 和 kill 文件，不隐式启用控制器。
- 全新组已核对为空后，先实际写 `cgroup.kill=1` 验证清理权限，再允许
  工作负载入组；不能仅因 kill 文件存在就假定以后能够终止后代。
- 父计量器在组外。新 Python gate 子进程先阻塞，父写入 `cgroup.procs`
  并读回确认成员身份后才释放实际 payload exec。EOF 或错误释放字节均拒绝。
- 普通 fork/exec 后代继承组成员；外层 subreaper 等待 root 和收养后代，
  同时要求组的 `populated=0`。到时写 `cgroup.kill` 并等待排空。
- 读空组退出后的层次 `memory.peak` 与 `cpu.stat`，保留非零退出和超时。
  `measurement_valid` 与 `cleanup_verified` 分开；删除前核对组 inode 和
  `populated`，删除后核对路径确实不存在。清理未证实则 `task_success=false`，
  已读到的 counter 可以保留，但不能报告整个 campaign 成功。

其内存指标严格名为 **cgroup 层次内存收费峰值**。已有/共享页面的收费可能
归属其他组，gate 在入组前的启动也不在该组收费范围；它不是完整族 RSS
总和、物理唯一页总量或完整部署内存。计量器自身、数据准备、历史训练和
能量均在该 counter 范围之外。未来使用时可外包 v8 完整 worker CPU meter
以计入这些运行时开销，内外 CPU 不可重复相加。

实际可执行部分已在当前主机验证，`KILL_PREFLIGHT_TESTS.log` 和
`KILL_PREFLIGHT_VALIDATION.json`
记录 7/7 通过、零跳过：真实 gate 阻塞/释放、父退出 EOF、错误字节、exec
失败非零保留、普通文件系统冒充 cgroup 的拒绝、非法 counter 拒绝及真实
挂载路由。控制脚本没有模拟出成功的内核 cgroup 计量。该验证的解释器加
已等待后代 CPU 为 0.220356 秒，仅覆盖 suite 加载至执行完毕，排除最初
解释器启动、最终回执序列化及本阶段开发。前一源码版本的 0.232138 秒
验证回执及更早七项通过的日志也保留。

`runner_campaign.py` 已落地，供具有真实委派权限的 runner 执行四组冻结
qualification：正常四进程、收养四进程、payload exit 3、产生后代后超时。
源码和 v9 真实分配夹具先冻结，运行后要求计量有效、完整排空、清理已证实
及相应退出语义；若首组无能力则停止并保存 HOLD。当前主机未执行这条
成功路径，因此成功内核 cgroup campaign 数仍为 **0**。超时 kill、实际
组成员继承、计量和删除仍需要该 runner 的真实运行结果，七项门控检查
不能替代这些条件。

在已配置的 runner 仓库根目录执行（路径必须替换为该 runner 实际委派组）：

```bash
python -m experiments.hcsn_v10_followup_20261101.economics.runner_campaign \
  --delegated-parent /sys/fs/cgroup/ACTUAL_DELEGATED_PARENT \
  --out /tmp/hcsn-v10-fresh-cgroup-qualification
```

当前严格结论：完整族连续 RSS、可归因焦耳及完整历史准备成本均未闭合；
硬件经济性 **HOLD**，没有 GPU、能耗或生产采用优势声明。源码可分三步
独立审阅：gate/计量器、真实门控控制、具权限 runner campaign；源身份见
`SOURCE_IDENTITY.json`。本阶段没有修改 v9 或原 v8 字节，提交及最后仓库
格式化由主集成阶段负责。
