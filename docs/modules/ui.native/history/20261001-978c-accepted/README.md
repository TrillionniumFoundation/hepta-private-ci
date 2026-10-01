# ui.native 本轮审计与最终验收结论

本轮多次执行对抗审计、红绿复现、源码修复、独立交叉复审和重新验收。
末轮在已检查边界内未发现新增可定位、可复现缺陷，达到本轮有界收敛。

普通产品源码为 `0a129b41c2a2d42ca907ea8257bf780108bc664f`，tree
`f90313f067446c629b8da50058ee1bd2101e76e7`。冻结闭包包括 420 个 Git blobs、
32 个选择路径、16 个本地 Cargo 依赖。实际合格候选为
`978c1923eda66373e9dce4fe0efa890bc60ac404`，tree
`1d8aa1f0d23094d9c5c3c52cd695c865c2b9a8d3`。

[实际 CI run 36842710605 / attempt 1](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36842710605)
的 9 个任务全部成功，包括六个平台 head/merge 主体、存储、身份和严格汇总。
实际三平台 merge 均为 `d64ceb854bb045302f5624f3b63f365a6b34739b`，
按 base `9be52d267d02a76f73e8a94fd086191c351d1c70`、candidate `978c1923…`
的顺序构造，tree 完全一致。本次实际 workflow 引用为
`9360eb0688b54f8accea54489c3d1d72c071812e`。

| 平台 | 每个 head/merge 的应用测试 | 依赖模块测试 | 实际检查 |
| --- | ---: | ---: | ---: |
| Linux | 245 | 214 | 18 |
| macOS | 256 | 232 | 16 |
| Windows | 210 | 173 | 16 |

各主体的三个独立规模入口仍标为 ignored；专用存储主体实际执行规模验收。
Python 每个主体共 240 项：Linux/macOS 各 239 通过、1 个 Windows 专用 skip；
Windows 各 236 通过、4 个平台专用 skip。macOS 每边实际通过 32 项 ACL、
2 项 FIFO 回归；Windows 每边实际通过 15 项 ACL/原子发布回归及新锁守卫回归。
Linux/macOS 新增原生及共享 Store 锁生命周期回归、此前两个实际失败路径均通过。
release、三项编译隐私拒绝、七项实际子进程故障、自检、打包及包内运行检查通过。
Linux 两边还通过安装态 GUI、gateway、keyring 和正常关闭观察。

独立复核从六个原始平台 ZIP 重放候选 Git blob 中的完整汇总验证器，结果对象及
序列化字节与 CI 的 `platform-qualification.json` 完全相同。每份包、锁文件、
SBOM 的 1968 个 components、provenance、日志与源码摘要均核验。原预算未放宽；
本次 48 份 syscall trace、原始测量、九项分位重算及同次存储绑定均通过。
百万退休身份重建 P95 为 4714.612 ms；4096 活动项与百万历史项共存时打开
P95 为 343.402 ms。测量为 release、新进程，OS page cache 未控制。

主要修复包括：同句柄私有文件 ACL/属主/目录身份和硬链接验证；更新备份摘要、
持久确认、取消、回滚与外部安装保护；显式锁释放及 opaque guard；有界 UI 输入、
分页、诊断和过期 binding；百万历史项重建与严格性能预算；LF 合并身份、
跨平台构建/打包和供应链重验；阻止共享地图跨源码迁移历史执行资格。

模块仍承担桌面呈现、本机操作边界及本地执行观察。gateway 负责认证读取，
authority 负责独立授权、nonce/epoch/撤销，operations 负责领域意图与 outbox，
supervisor 负责生命周期，private-state utility 提供 OS 原语。

已有详细开发文档：候选中的 `docs/modules/ui.native/TECHNICAL.md` 为 14 章、
47073 bytes、6077 个项目统计词；`apps/hepta-native/DEVELOPMENT.md` 提供工具链、
构建、测试、打包、排障和证据采集。已提交的开发文档与审计报告保留发布前快照，
本目录及 PR 提供该精确候选的最终执行结果。

完成度仍有明确缺口：macOS/Windows verified-resource Open/Reveal 需要受认证的
FD/HANDLE 消费接收方、规范对象与接收方身份、独立 issuer 策略，以及绑定
operation/session/grant/resource 的 ACK 和可查询回执；目前代码正确拒绝这些效果。
实体 Windows/macOS/X11/Wayland、IME/DPI/无障碍、安装、持续运行、签名和独立
供应链接受仍需验收。production、deployment、release、physical、accessibility、
production-signing 资格均为 false。

全项目 docs/maps 检查仍被 `utility.ndu` 与 `intelligence.control` 的同一既有
NDU source drift 阻断。基线与候选的相关映射和源文件逐字节相同；历史实际执行
声明保持原样。这两项失败与本次 ui.native 仓库级资格分别记录。

本目录记录的资格只绑定 `978c1923…` 和上述 run/attempt；后续候选需要重新验收。
当前合格 PR head 保持 `978c1923…`。本目录通过独立归档 ref 保存，相关文件摘要
和原观测路径列于 [INDEX.json](INDEX.json)，主结果为
[complete-verification.json](complete-verification.json)。原始验收 JSON 与独立证明
逐字节复制，早期快照及所有旧失败记录保持原样。原观测中的 scratch 路径是当时
采集位置，当前归档副本按 INDEX 的相对路径查找。

`storage-artifact.zip.b64` 解码后保留本次原始存储 ZIP（包括 48 份 trace）；
`aggregate-artifact.zip.b64` 解码后保留实际最终汇总 ZIP。INDEX 同时提供编码文件
与解码 ZIP 的长度和 SHA256。平台二进制包及其原始完整产物由本次 Actions 引用。
归档提交的 `[skip ci]` 仅用于保存这份执行记录，合格候选的完整 9 项 CI 已实际执行。
