# Run02 controller 对账：静态复核

## 范围与判断

本次仅完整读取 Mac 上的新旧 postrun preparer、reschedule 包的 DEPLOYMENT_MAP/MANIFEST、archive03 与 owned02 源码。没有读取活动 Run02 输出或 controller observation 原件，没有执行任何 preparer、wrapper、归档程序、模型、tests、verifier 或新 C；只新建本报告。以下为静态兼容性判断，不是 Run02 已结束、writer 已停止或 postrun 已成功的证明。

**新 preparer 与已冻结 archive03 的“目标 owned wait/停止身份为准、controller 原样保留”规则兼容，未发现此次修改把未知 controller 状态伪写为 exit 0、重复启动研究模型或弱化既有停止检查。**它接受 controller loss，但仍要求目标 owned wait_returncode=0、原 child/wrapper PID 不存在、已有 worker EXIT 的 PID 不存在、study freeze SHA 相符，并新增 Desktop Linux boot 等于原 research launch freeze 的约束。〔N·remote；A·owned_receipts/writer_evidence〕

**必须保留限定：preparer 自身不是完整的所有 worker 终态证明。**它沿用旧代码，只枚举已有 */EXIT.json；最终 archive03 才按每个 LAUNCH.json 要求恰好一个 EXIT/INTERRUPTED、验证回执/输出身份并观察停止。不能以 preparer 的 POSTRUN_FROZEN 代替这个完整闭合步骤。〔O/N·remote；A·writer_evidence〕

## 新旧差异核对

通过解码源码中的 remote 字符串做精确文本比较：外层 Mac 程序完全相同；remote 除以下三处外完全一致。未执行这些代码。

| 改动 | 静态效果 |
| --- | --- |
| 原单一 controller clean gate 改为 clean 或 lost/incomplete | clean 仍要求 status.state=exited、exit_code=0、status.output_complete=true；loss 要求 status.state=lost 且原 observation 顶层 output_complete=false |
| 增加原 Linux boot 绑定 | 读取 /proc/sys/kernel/random/boot_id，与原 RESEARCH_LAUNCH_FREEZE_02.json 的 boot 相等；controller 的 target_reboot 标签不会替代此目标主机检查 |
| 增加四个 freeze 元数据字段 | controller_status_as_observed、controller_capture_complete_as_observed、controller_status_rewritten=false、completion_basis；原 study/diagnostic 参数、来源 SHA、预算引用及资格不变 |

loss 分支接受的是 lost/incomplete 这个状态类别，未进一步要求 reason 必须等于 target_reboot，也没有将其转换成 exited。完整原 observation 字节经 base64 和 SHA 校验，以 xb/fsync 保留，并进入 immutable_inputs；reason 等其他原字段因此仍在原件中。新 freeze 只投影 status 和 capture 字段，不伪造完整捕获。〔N·remote〕

## 元数据变量与 wrapper 兼容

1. 解码后的 N remote 中，control_observation 仅赋值一次。worker 循环仍将各 EXIT 内容赋给 v，文件身份循环使用 name/p；它们均不改 control_observation。新增 freeze 字段引用的明确是原 controller observation，不是最后一个 worker EXIT。
2. 外层 Mac 的 v=json.loads(p.stdout) 属于另一个解释器作用域，只用于取回新 freeze；它不会反向影响 remote 已序列化的 controller 元数据。
3. owned02.main 校验必要顶层字段及角色/路径/qualification，没有要求顶层键集合完全相等，故新增顶层元数据不会被拒绝。
4. 附加字段不会自动逐项复制到 INTENT；INTENT 保存整个 launch freeze 的 SHA，archive03 又保存并核对 freeze 原件，因此这些字段仍被完整字节身份绑定。不能声称 INTENT 本身直接含有全部新字段。
5. 新 preparer 的 argv 固定为 postrun diagnostic；entry SHA 和 diagnostic rules SHA 与 DEPLOYMENT_MAP 一致。owned02 的 postrun 角色固定指向该 diagnostic，不能因这些元数据变成 research 角色。〔N·remote；W·ROLES/main/run_owned；A·writer_evidence〕

## writer 关闭与原始 controller 的证据链

新 preparer 保留了旧 preparer 的 target 检查，先读原 owned STARTED/EXIT，要求 wait_returncode=0，并要求原 child_identity、wrapper_identity 的 PID 路径不存在；对已有 worker EXIT 要求整数 exit_code 且 PID 不存在。若原 coordinator 仍存活或没有 EXIT，该 preparer不能完成。新增同 boot 检查也防止把目标真实重启后 PID 消失直接当作同一次正常完成。〔N·remote〕

archive03 的最终权威检查更完整，保持原冻结逻辑：

- 核对 owned INTENT→STARTED→EXIT 的 SHA 链、schema、role、operation_key、argv、child_identity；要求整数 wait_returncode 和 exit_source=subprocess.Popen.wait，并核对真实 stdout/stderr 字节。
- 对 child 与 wrapper 用 boot/PID/start_time_ticks 做 fresh process_observation，要求不再是原活 writer。
- 遍历每个 LAUNCH.json，要求恰好一份 EXIT 或 INTERRUPTED；EXIT 要有有效 seal 与流 SHA，且实际 worker PID 不再活着。缺少 terminal 的已启动 worker 会阻止归档。
- 原 controller response 仅要求具有 status dict/session_id string，其字节 SHA 被绑定；state/exit/capture 原样写进 verified_writer_outcomes，controller_status_rewritten=false。没有要求或补写 controller exit0。
- 核对 immutable_inputs、research freeze、diagnostic result；导出后再次逐源比较字节/元数据，不把这些操作声称为原子文件系统快照。〔A·owned_receipts/process_observation/writer_evidence/main〕

## 仍须准确陈述的既有边界

**preparer 不是 archive 的替代。**它不检查“每个 LAUNCH 必有 terminal”，也不自行验证 owned 的全部 SHA 链或 exit_source。completion_basis 是方法描述，真实 Popen.wait 与原 writer 身份链仍须由实际原件和 archive03 校验支持。进入 postrun 前，根代理仍应完成其所拥有的全部 writer 对账；最终不能跳过 archive03。此范围是新旧 preparer 共有，非本次增加。〔O/N·remote；A·owned_receipts/writer_evidence〕

**当前 PID 检查是保守的。**preparer 要求 /proc/PID 完全不存在；PID 被复用或处于 zombie 时可能拒绝，即便原 writer 已停止。archive03 的 owned 身份比较更精确。此差异会造成拒绝，不会把仍存活原 PID 当作通过。〔N·remote；A·process_observation〕

**freeze 的 environment 不是 wrapper 已应用的保证。**owned02.main 从 os.environ.copy() 建立实际环境，只覆盖固定缓存路径，没有把 freeze["environment"] 整体应用。因此新 freeze 中 CUDA_VISIBLE_DEVICES="" 的记录不能单独证明 postrun 进程已屏蔽 GPU。该行为未被此次修改；零模型调用依赖冻结 diagnostic 的实际程序和启动/终态证据，不应归因于这个未应用的环境字段。此处未复读或执行 diagnostic。〔N·remote；W·main〕

**create-only 失败不能盲目重试。**新旧 preparer 使用同一个 Mac preparation 目录、Desktop observation 与 postrun freeze 目标，且 observation 在后续验证前落盘。若先前已留下文件，第二次执行会拒绝；不能把这个拒绝解释成研究失败或通过更换 key 自动重跑。原件应先对账。〔O/N·外层及 remote〕

## 源码身份

根目录：/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a。所需源码的部署映射不含 source/ 层；根据实际目录及 DEPLOYMENT_MAP，archive03/owned02 位于 research-reschedule-source-02/operations/。两份实际源码的大小/SHA 与 DEPLOYMENT_MAP、MANIFEST 一致；本次没有验证正在运行主机的部署状态。

| 标记 | 相对路径 | 字节数 | SHA-256 |
| --- | --- | ---: | --- |
| N | operations/prepare_research_postrun_reconciled_02.py | 5849 | b51fe2f1e6646e1737ab98ff37d06414a6d3ba716892bb5edd1de9ba776b7efa |
| O | operations/prepare_research_postrun_02.py | 4914 | a8e9da6cce44377e55b18d73c52abc5f68d7829dffe5d475fe5fa17e37e52297 |
| A | research-reschedule-source-02/operations/archive_qwen_research_v1_03.py | 20170 | 251e08cae5fb55df3872ab45619e1b22d0177a0c8d1a0b8b200ddcfd237ab462 |
| W | research-reschedule-source-02/operations/launch_qwen_research_owned_v1_02.py | 9063 | 205a72dbe8adab915c8f7c9225a3d4effb0f399f80ba167cd5786213aa7eda00 |
| D | research-reschedule-source-02/DEPLOYMENT_MAP_02.json | 1742 | 3bd804a4c30ddef12c1f51f8e197254f7b934ab874f98d6aa4e5ada302e28719 |
| M | research-reschedule-source-02/MANIFEST_02.json | 4533 | f7c84c00b8dc137d19acaafdb2234433500044f197a565febb1bd2a6dfc15d78 |

静态结论：新 controller 对账字段与冻结后续链路兼容，原 lost/incomplete 必须持续可见；实际研究终态、所有 writer 关闭、postrun 和最终归档成功仍待真实证据分别成立。
