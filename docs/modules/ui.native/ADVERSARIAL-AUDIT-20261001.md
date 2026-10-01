# ui.native 对抗审计与修订记录 — 2026-10-01

审计基线为规范开发分支 `work/ui-native-qualified-integration-20260928`
的 `9be52d267d02a76f73e8a94fd086191c351d1c70`，不是较旧的 main。
本轮修订分支为 `work/ui-native-adversarial-audit-20261001`。
实现冻结身份以 CURRENT_SOURCE/CANDIDATE 中的 SHA/tree 为准。

本次后续修订冻结于 `32310eefbef2a80164b669fe3bfcaef69b47b9da`，tree 为
`90e28eb295688c11e93d4aec0ad983ba53e0e612`。该源仍是未完整验收的实现候选：
非 Linux Open/Reveal 缺少等价资源能力适配，完整同源 CI、实体桌面、签名及
独立发布审批均未完成。最终同源的 release 应用回归 243/243 通过（1.469 s），
包含真实 headless egui text snapshot；all-targets/all-features 严格应用 Clippy
通过（4.78 s）。三项 ignored 是两个独立规模主体及其 worker；原生资格 Python
227/227 和严格 native-map adapter 86/86 通过，两个完整 release 规模主体也通过。
三个 release 二进制构建、自检和真实子进程 qualification-e2e 通过。ca66 的先期
243 项回归、ed5 的 212/226 项回归及 21cbe83 的 210 项 owner 回归保留为历史，
不能继承为最终源 owner 或平台验收。最后一次独立静态复审未发现
新的同范围可复现问题；这不是对所有未来缺陷或生产完成度的保证。

## 完成度结论

模块有详细技术开发文档：TECHNICAL.md 覆盖所有权、持久化、最终使用授权、
平台能力、更新协议、性能预算和验收；DEVELOPMENT.md 提供工具链、构建、
回归、打包、排障及证据采集步骤。旧模块 dossier 和辅助投影工具存在明显
漂移，本轮已同步；旧 dossier 完整保留在 qualification 历史目录。

| 层次 | 审计结论 | 完成证据要求 |
| --- | --- | --- |
| 产品实现 | 主调用链、MAC v2 网关、内核最终使用、WAL、历史分页及更新协调已经落地；基线仍有构建/协议缺陷 | 本轮修复与回归，不等同生产完成 |
| 功能覆盖 | Linux Open/Reveal 使用验证 FD；macOS/Windows 等价能力适配器仍缺失并拒绝执行 | 各目标平台的真实资源能力适配与测试 |
| 仓库验收 | 基线七主体工作流失败，manifest 未附成功 run/性能/覆盖率证据 | 同一 head/base/workflow/run/attempt 的完整成功证据 |
| 实体桌面 | 无完整 Windows/macOS/X11/Wayland、IME、DPI、无障碍及安装验收 | 对应实体主机执行记录 |
| 发布资格 | 未完成独立签名、供应链接受、审批与保护规则 | 独立负责人提供并审核，授权标志保持 false |

不能用一个百分比同时表达这些层次，也不能把测试代码存在或候选代码冻结
换算成验收通过。非 Linux Open/Reveal 属于代码能力缺口；签名、实体验收和
独立接受属于外部证据门槛，必须分别追踪。

## 对抗发现与修复

| 严重度 | 基线问题及触发 | 修订 |
| --- | --- | --- |
| P1 | WAL/锁先跟随路径打开，再做软链接检查；悬空 WAL 链接可能创建根外目标 | 同句柄验证、NOFOLLOW/NONBLOCK、根目录能力与替换回归 |
| P1 | 私有目录只检查权限和属主；替换成同样 0700 的目录仍通过 | 持有原目录句柄并绑定目录身份；拒绝稳定替换 |
| P1 | 更新前驱检查后再复制备份；复制内容未在原子替换前绑定签名摘要 | 对实际复制句柄流计算摘要，候选/备份/回滚均在发布前验证 |
| P1 | 持久化 Confirmed 先于助手 C 确认；助手死亡可留下错误终态 | readiness 保持 ActivatedUnconfirmed，收到确认后由候选提交终态 |
| P1 | 超时清理与确认并发，可能杀死刚确认的进程而跳过回滚 | 同一更新所有者锁裁决取消/确认；取消先持久化回滚状态，再清理进程 |
| P1 | 激活失败回滚未校验安装目标，可能覆盖外部安装的新二进制 | 仅对签名候选/前驱身份回滚；其他目标保留并持久化 RecoveryRequired |
| P2 | Windows 合同依赖声明被删除但代码仍使用它；直接恢复会产生两处项目层级违规 | 将纯 OS/ACL 实现提取至公共 utility；contracts 直接依赖 utility，旧 crate 保留兼容导出；保留严格分层规则 |
| P2 | 分页 API 更换后故障验收和旧测试仍调用已删除接口 | 迁移至有界分页，保留重复执行/恢复断言 |
| P2 | WAL 延迟检查点后，测试仍假定每次 mutation 都写快照 | 重复操作比较真实 WAL；快照场景通过真实 128-entry 检查点构造 |
| P2 | 工作流在 checkout 内产生 native-evidence 后检查全部未跟踪文件 | 输出移至 RUNNER_TEMP；继续拒绝真实源码污染 |
| P2 | 冻结检查漏掉 build/portal/package/keyring/owner manifests，未检查未提交实现漂移 | 扩展冻结范围并验证 staged/worktree/untracked 源码 |
| P2 | 冻结范围与工作流触发遗漏网关的传递依赖 | 纳入本地 Cargo 依赖闭包并对依赖修改重新验收 |
| P2 | 性能预算以编译常量引用，但 metadata continuation 可放宽阈值 | 对冻结 Git blob 比较完整预算语义，仅允许更新顶层 SHA/tree 锚点 |
| P2 | 证据摘要可被一并重算后替换实现/包/供应链语义 | 对照候选 Git 状态、包、锁、主体、workflow、run/attempt 重验语义 |
| P2 | SBOM 删除依赖 components 后重新计算摘要仍被 aggregate 接受 | 从精确执行 Git 源的两份 Cargo.lock 独立重建并逐项比对组件 |
| P2 | storage transitions 可任意膨胀、fsync 可减少，稀释写放大数值 | 绑定 4096 × 3 次实际状态转换及其持久化次数，拒绝数量漂移 |
| P2 | 冷启动/rebuild 仅单次测量却当作 p95；aggregate 未重验 storage 原始证据 | 每项 20 个独立新进程，保留样本数组并重算 p95；aggregate 重验原始 JSON、syscall 和全部预算 |
| P2 | 独立 active/retired 测试漏掉共存负载；4096 + 百万时启动反复解码索引桶 | 启动按前缀批量校验一次，查询数上限 4096；增加共存负载 20 次新进程及历史页测量，预算不变 |
| P2 | 产品性能验收默认测量 debug 构建，未绑定实际编译配置 | 专用规模主体使用 release，与产品二进制配置一致；原始样本及 validator 明确绑定配置，保留旧 debug 失败记录 |
| P2 | 百万重建夹具按 prefix 聚簇，并复用既有派生文件，漏掉混合历史首次迁移成本 | 以每批 1024 个 identity 的时序混合批次构造 977 个权威段；20 独立根从零派生资产重建；有界认证 spool 每 prefix 只构造一次最终 bucket，完整验证归档，强绑定 shape/head 摘要 |
| P3 | 每次 SHA 摘要验证分配一个 64-byte 全零 String | 改为静态零摘要比较，保留全部输入校验语义 |
| P2 | Windows 闭合打包清单仍断言 5 文件，新增 registrar 实际为 6 | 每个平台断言精确文件集合 |
| P2 | Escape 仅在部分屏幕有效；陈旧 close 可清除当前认证 | 全局准入前取消；绑定精确 SessionIncarnation |
| P2 | 文件名 trim/有损显示转换可能改变所选路径 | 保留空白，拒绝非法 UTF-8/NUL/超长路径，保留原目标 ticket |
| P2 | 未限制输入缓存；切换操作可能复用焦点；GUI 线程展开 JSON 无输出上限 | 有界输入、独立控件 ID、worker 预渲染与 4 MiB 诊断输出上限 |
| P2 | portal 超时从同步 RPC 结束后计算，父进程可能先终止导致取消失效 | 从请求前计算总期限，保留关闭 RPC/回收余量 |
| P2 | 更新备份持续累积，清理 staged 文件没有绑定实际摘要 | 每目标最多保留 4 个、共 2 GiB 前驱；新增更新在写入前拒绝超额，恢复不受限；只清理摘要相符的所属文件 |
| P2 | 旧 dossier/投影 receipt 引用退役分支、schema 和已删除工作流 | 同步当前架构和唯一验收链；保留历史和独立授权边界 |
| P2 | 远端工作流在 job.env 使用 runner.temp，GitHub 在创建 job 前拒绝语义验证 | 将临时路径放到 runner 执行的初始化 step，并写入 GITHUB_ENV；保留 step 级合法 runner 上下文 |
| P2 | 外部 compile-negative 夹具缺少锁文件，离线浮动解析先失败，未执行隐私验证 | 从精确应用锁 seed 归一化，逐项拒绝版本/摘要/依赖边漂移，再执行 locked 负向编译；保留失败诊断 |
| P2 | 全局实现映射检查器只接受 v3，拒绝当前 ui.native v6 映射 | 仅对该模块提供只读严格适配，复用完整冻结检查；其他模块规则和所有权保持严格 |
| P2 | 生成 binding 在 GUI 线程执行资源确认；输入或 authenticated view 改变后可能展示旧结果 | 移至受监督 runtime lane，准入时复验精确 view，完成时比对全部输入、页面及连接；编辑使结果失效；独立 owner 仍负责签署 grant |
| P1 | 启动记录的父目录在初始化后可替换；更新 JSON、锁和 staged 路径未完整保留目录身份 | StartupRecorder 固定已有私有父目录；更新读写、锁、ACK/取消和清理保留根能力；staged 使用已验证子目录能力，替换与 trust drift 拒绝 |
| P1 | Windows 私有父目录不保证已有子文件 ACL；可写 WAL/锁的硬链接别名可影响根外文件 | 在实际打开句柄检查 child owner/DACL；所有非 Read 可变打开要求单链接；公共 utility 的读写 open_file 同样执行保护，覆盖 contracts authority store 调用 |
| P1 | 更新助手已有 manager，却重新调用 standalone 激活入口打开根路径，丢失已固定身份 | 沿现有 UpdateManager 的私有根能力激活；standalone 保留为独立入口边界 |
| P2 | 崩溃遗留的其他 staged digest 或未知临时文件可继续累积 | 暂存准入仅允许当前 digest 的单个 package，并校验重试内容；未知、其他 digest 和 crash temporary 均保留并拒绝新暂存，交由显式恢复 |
| P2 | Windows notification identity marker 无界读取；打包 C# 将 readonly 字段以 ref 传入而无法编译 | 正规文件读取限 128 bytes 并核对 UTF-8/AUMID；readonly key 复制为局部变量，Windows 专属测试编译实际打包源码；不等于安装或可见通知验收 |
| P2 | 合法 jobs header 尾随注释或空白可能令 job.env 上下文检查漏检 | 按 block header 语义识别 jobs 并保留 env 上下文限制；覆盖注释/空白入口回归，排队 CI 仍是待执行证据 |

基线远端 run 36682622270 的六个平台在构造阶段就因输出污染失败；storage
以 --locked 拒绝不一致依赖状态。此前 run 36670666771 亦同。因此基线
CURRENT_DELIVERY 中所有执行标志 false 是正确的，没有成功全链证据可继承。

## 项目位置与优化原则

ui.native 是呈现及有限本机操作边界，不是另一个 runtime 或授权中心。
高价值优化是收紧现有边界：单一 mutation/journal 所有者，精确会话和资源身份，
持久化后再执行，UNKNOWN 不重放，更新取消与确认共享原子裁决，以及统一源码
与证据身份。增加插件、第二 supervisor 或绕过内核最终授权没有必要。

安装目标要求单一协调安装者。检查与原子替换之间的外部并发写入没有
文件系统 compare-and-swap 保护；此所有权限制已写入技术合同。被发现的
外部目标会保留并进入人工恢复，不能以自动回滚覆盖。

UI 改进保持 picker/read/mutation 分工：对话框可以独立工作，读取与 mutation
互斥；输入、历史和诊断保持有界；关闭窗口保留任务所有权。实体平台缺口必须
通过真实能力适配与验收补齐，不能用宽松路径命令替代验证 FD。

异步 binding 只是准备独立 authority owner 的输入，不执行平台效果或自行选择
grant identity、nonce、epoch、有效期和签名。真实 headless egui text snapshot
检查生成中及 stale-result 提示，不是 GPU、实体平台或无障碍验收。
暂存 package 上限为 512 MiB；原子替换期间可额外持有一份至多 512 MiB 的
临时副本，不能声称峰值磁盘占用仅 512 MiB。前驱备份限制单独适用。
Unix Read 不修改文件，允许当前主体所有且无 group/world 权限的 0400、0500、
0600 或 0700 文件及不可变迁移资产别名，
仍需内容和身份认证；单链接准入检查不能阻止可信主体随后新增硬链接。

## 验证与复审

最终源 32310 的常规 release 应用 243/243、严格 all-targets/all-features
应用 Clippy、资格 Python 227/227（13.041 s）及 native-map adapter 86/86
（7.671 s）通过；源码冻结结构检查和 19 项 convergence 回归通过。
两个完整规模主体通过：4096-active 用时 2.461 s，百万 retired 加 4096-active
共存负载用时 52.572 s。每项 open/rebuild 为 20 个独立新进程，原始数组的
分位数独立复算一致，预算未放宽：

| 最终 32310 release 本地诊断 | 测量 | 冻结预算 |
| --- | --- | --- |
| 4096 active open p95 | 31.413 ms | 2000 ms |
| 12288 mutation p50 / p95 / p99 | 0.022 / 0.043 / 0.234 ms | 25 / 100 / 250 ms |
| active 64-record page p95 / retained JSON | 0.047 ms / 28417 bytes | 25 ms / 2 MiB |
| 百万 retired indexed open p95 | 0.414 ms | 2000 ms |
| 百万 mixed、零派生资产 rebuild p95 | 1866.871 ms | 30000 ms |
| 4096 active + 百万 retired journal open p95 | 462.509 ms | 2000 ms |
| 共存 64-record page p95 / retained JSON | 0.042 ms / 28417 bytes | 25 ms / 2 MiB |
| active / retired+combined peak RSS | 22 / 31 MiB | 256 / 256 MiB |
| retired storage | 144415688 bytes | 256 MiB |

active snapshot 为 2608315 bytes，最终 WAL 为 0 bytes。百万权威夹具包含 977
个混合前缀段，每段至少 228 个前缀；各零派生资产重建得到相同 head SHA256
`a437b567ef1c9757305487f41331d5beb33ad2c19155ff11d0e675ce3fd7e44a`。
三个 release 二进制真实构建（0.39 s）、self-test 和实际子进程故障
qualification-e2e 均通过，receipt 七项故障/授权围栏检查为 true，三项 authority
grant 标志为 false。package/portal 36/36、投影 generate/verify/lint 与 7 项测试
通过，registry 记录 84 个文件。上述均为共享 Linux 容器本地诊断，
page cache 未控制、retained JSON bytes 不是 allocator profile；没有可用
durability syscall trace，也没有完整同次七主体或实体平台验收。百万夹具仍为
legacy identity-only tombstones，不能作为百万完整归档 receipt 的容量结论。

历史 ed5 阶段常规应用回归 212/212、相关 owner 回归 210/210 通过；应用的三项
ignored 项是两个完整规模主体及其子进程 worker，规模主体单独运行。
该历史阶段 Python 验证 226/226、36 项打包/portal 测试、7 项投影测试、4 项 registry
测试和源码冻结检查通过；严格 Clippy 两组通过。项目图遍历 195 个本地
manifest、0 错误，53 项分层回归通过；实际 Bazel 9.0.0 lock-update 与
lock-check 通过，锁无需改变。新增回归覆盖实际
temp-Git shell、重算摘要后的语义证据替换、真实更新子进程死亡/确认/取消、
链接与目录替换、复制内容漂移、实际 egui 粘贴/焦点事件，以及有界诊断失败后
的 displayed-binding 失效。当前环境拒绝 Unix socket bind，socket 夹具输出
明确诊断；软链接断言仍执行，socket 拒绝场景需 hosted CI 实际执行。

这些旧数量不覆盖新源。公共 Windows utility 已变更，不能用旧 owner 树或
旧 210 项结果代替最终源 owner 验证。修订后的 manifest 已实际执行 Bazel
9.0.0 lock-update 与 lock-check，两者通过且锁无需改变；它们是依赖元数据
检查，不是 Bazel 编译或 Windows 主机执行证明。

历史冻结源 `21cbe83cf85994bcbfd29666b5acd9d82cc15294` 的三个 release
二进制真实构建、自检及真实子进程故障 qualification-e2e 通过；覆盖父进程
死亡、更新助手死亡、回滚及 RecoveryRequired。两个独立输出的 Linux 无签名
包全部文件逐项一致，archive SHA256 为
`4c8cc41eb120d7b860ce926036c18412bda784f42f4e312ffdf73d64605444b9`。
这是本地包诊断，不是完整平台安装验收或供应链接受。此前 debug 二进制诊断
保留为历史记录，不代替最终冻结源结果。运行环境为共享 Linux 容器，
Rust 1.95.0，无完整桌面。

4096 active / 12288 转换与 20 个新进程的诊断测量通过声明阈值：open p95
523.042 ms，mutation p50/p95/p99 为 0.272/0.402/2.831 ms，64-record page
p95 为 0.110 ms、保留序列化 28417 bytes，peak RSS 27 MiB，快照 2608315
bytes，最终 WAL 为 0 bytes。OS page cache 未控制，序列化 bytes 不是 allocator
profile。该次代码身份为 f4ce125546ab743ebedbc793762add89b1143ac3；当时正在
修订 metadata 文档，所以该结果是本地诊断，不是干净 review head 的合格证据。

旧 f4ce125 的 debug 百万退休诊断产生 1024 个段，20 个新进程 indexed open
p95 为 8.026 ms；20 次 legacy rebuild p95 为 47848.341 ms，超过 30000 ms
预算，失败。独立共存诊断中 4096 active + 百万 retired 的 journal open 为
218729.403 ms；该旧二进制记录为 local-unpinned-source，仅作失败诊断。
这些 debug 结果保留原构建配置与身份，不能被新版 release 结果重新标记。
中间源 21cbe83 的 release 两个旧夹具规模主体分别用时 2.40 s 和 58.60 s，通过
所有内置性能/RSS 阈值。每项 20 个独立新进程，原始分位数、编译 profile 和
source SHA 独立复算/绑定；阈值没有放宽：

| release 诊断指标 | 测量 | 冻结预算 |
| --- | --- | --- |
| 4096 active open p95 | 28.658 ms | 2000 ms |
| mutation p50 / p95 / p99 | 0.022 / 0.037 / 0.176 ms | 25 / 100 / 250 ms |
| active history page p95 / retained JSON | 0.048 ms / 28417 bytes | 25 ms / 2 MiB |
| 百万 retired indexed open p95 | 0.449 ms | 2000 ms |
| 百万 retired deterministic rebuild p95 | 1922.288 ms | 30000 ms |
| 共存 journal open p95 | 434.262 ms | 2000 ms |
| 共存 history page p95 / retained JSON | 0.082 ms / 28417 bytes | 25 ms / 2 MiB |
| active / retired+combined peak RSS | 21 / 112 MiB | 256 / 256 MiB |

旧 debug 基线与新版 release 配置不同，不能把两者比值当作批处理算法的
独立加速倍数。这组结果仅说明当时的聚簇前缀、复用派生文件夹具满足本地阈值；
不能替代最终源的混合前缀、零派生资产重建测量。
strace 实际尝试被环境以 PTRACE_TRACEME Operation not permitted 拒绝，不能
声称 fsync 数量或写放大已完成实测验收。七主体 CI、release/package、Linux
真实 keyring/Xvfb 生命周期仍以独立同次 CI artifacts 为准。

历史冻结源 ed5fd222 的两个完整 release 规模主体实际通过，分别用时 2.482 s
和 49.096 s。20 个重建 worker 各自从零派生资产开始；977 段全为混合前缀，
每段至少 228 个前缀，每个 worker 重建 head 摘要一致。原始分位数独立复算，
源码和实际编译 profile 绑定，预算没有放宽：

| 历史 ed5 release 本地诊断 | 测量 | 冻结预算 |
| --- | --- | --- |
| 4096 active open p95 | 25.115 ms | 2000 ms |
| mutation p50 / p95 / p99 | 0.022 / 0.045 / 0.296 ms | 25 / 100 / 250 ms |
| active history page p95 / retained JSON | 0.040 ms / 28417 bytes | 25 ms / 2 MiB |
| 百万 retired indexed open p95 | 0.399 ms | 2000 ms |
| 百万 mixed、零派生资产 rebuild p95 | 1461.650 ms | 30000 ms |
| 4096 active + 百万 retired journal open p95 | 447.810 ms | 2000 ms |
| 共存 history page p95 / retained JSON | 0.060 ms / 28417 bytes | 25 ms / 2 MiB |
| active / retired subject peak RSS | 22 / 31 MiB | 256 / 256 MiB |

该历史源的三个 release 二进制真实构建、self-test 及实际子进程故障
qualification-e2e 均通过。以上是共享 Linux 容器本地诊断；page cache 未控制、
当时 review metadata 尚未提交，且没有 durability syscall trace，不能升级为
七主体验收或发布资格。权威夹具构造用时不是 store append 性能测量。

该阶段历史冻结源为 ed5fd2229502099addd6bedec2fae18783d5c162。迁移回归涵盖
混合段、重复身份、暂存篡改、正常失败清理、无资产重试、异常旧文件碰撞及
坏归档。每前缀暂存先执行条数/bytes 上限；同句柄内容受写入摘要认证。
确定性 authority-chain 命名使崩溃重试不能继续增加暂存集合；碰到遗留文件
拒绝迁移，需保留并显式人工移走。只承诺发布前失败保留旧 head；原子发布后
同步失败的结果不确定，不能假称旧 head 未变。规模夹具是 legacy identity-only
tombstones；百万完整归档 receipt 的容量仍未测量。

全局文档验证还存在既有跨分支 provenance 问题：其他模块历史锚点不是此
规范 ui.native 分支的祖先。新只读 v6 适配复用严格原生冻结门槛，只解决本
模块映射格式冲突；未重锚其他模块，也未放松其继承规则。新增 18 项真实
临时 Git 适配回归及相关联合 182 项通过，不能将其表述成全局 docs verify
成功。在干净 review head `9005dcee92537ad77e5d115bf367d10a0cfef756`
实际重跑全局验证：ui.native 适配通过；其余 39 模块仍因历史源锚点非祖先失败。
同一干净 head 的三项编译负向检查实际观察到 E0603；测试夹具按真实 host
归一化精确应用锁，核对依赖身份、checksum 及边后执行 offline/locked 编译。

PR #1308 的首次远端入口观测还发现 job.env 的 runner 上下文非法：run
36791294111 的 annotations 精确指向第154和322行，未创建任何 job。修订改在
runner 初始化步骤使用 RUNNER_TEMP 并写入 GITHUB_ENV；不能将修复或队列状态
表述为七主体 CI 已通过。

最终源码的编译隔离检查在干净 review head
`7237eca7ba4139d64138e1511afbdb45a507d0ad` 实际重跑，三项外部 crate
均观察到预期 E0603。夹具从最终应用锁
`612e3139224be6d1f36dab01850ee048bd7ec9e405dbbd8a556096dc17d3e701`
归一化，逐项核对依赖身份、checksum 和边，随后执行 offline/locked 编译。
相同 head 的新建 detached worktree 全局文档验证仍有上述 39 个非本模块
provenance 失败，ui.native 适配通过；不是全局验证成功。原生远端 run
36795845661 已接受并排队，尚无七主体成功证据。

Windows 最终只读审查还确认一个条件性可用性限制：新对象的缺省 owner
取 effective token 的默认 owner，而验证要求 primary TokenUser；合法组默认
owner 或线程 impersonation 可能导致新对象随后被拒绝。现有实现要求默认
owner 与用户 SID 一致且无线程 impersonation。它保持安全拒绝，没有观察到
授权绕过，也不能据此宣称所有管理员提升场景必然失败。真实 Windows 上的
普通用户、提升用户及 owner 不一致场景仍需验收；不能通过放宽 owner 验证、
接纳 owner group 或自动修改已有对象 owner 来消除此限制。

所有 productionQualified/deploymentQualified/releaseAuthorized 保持 false。
本轮停止条件是复现问题均有对应修复与回归，复审未发现新的同范围可执行
修复项；这不构成对所有未来缺陷或生产完成度的证明。明确保留以下验收工作：
完整七主体执行、存储硬预算、源覆盖率与持续 soak、非 Linux 资源能力适配，
实体平台/IME/DPI/无障碍、签名和独立供应链/发布审批。
