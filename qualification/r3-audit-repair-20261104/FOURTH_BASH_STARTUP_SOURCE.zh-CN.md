# Bash5.3 启动路径：源码支持与实际机制边界

结论：所核 Bash5.3 原始源码支持当前 `--norc` 修复方向。remote startup 分支不检查 `privileged_mode`；`isnetconn` 的正常 getpeername 实现把 EPERM 归为肯定结果。但**未 trace 实际失败进程，不能把 seccomp→EPERM 这条机制写成已直接观测**。

## 固定来源

- [GNU maintainer 的5.3发布公告](https://lists.gnu.org/archive/html/bug-bash/2025-07/msg00005.html)确认版本与官方发行渠道。
- [shell.c 固定提交](https://gitea.psi.ch/pmodules/bash/src/commit/b8c60bc9ca365f8261fa97900b6fa939f6ebc303/shell.c)：`b8c60bc9ca365f8261fa97900b6fa939f6ebc303`，Chet 的 Bash5.3 distribution；本次从声明同步 GNU 的 PSI 镜像读取。
- [netconn.c 的5.3发行源码](https://fossies.org/linux/bash/lib/sh/netconn.c)：Fossies 检索返回原源码42–54行及成员版本；直接打开403，未取得原 tar／文件字节哈希。
- [5.3 patch9 固定提交](https://gitea.psi.ch/pmodules/bash/commit/637f5c8696a6adc9b4519f1cd74aa78492266b7f)：`637f5c8696a6adc9b4519f1cd74aa78492266b7f`，显示 patchlevel 8→9；修改两个 Readline 文件和 patchlevel.h。本次没有独取该 commit 两个目标文件的原始字节，不能声称与 ROG5.3.9 binary 一致。

## 源码查证

`main` 在执行 `-c` 内容前调用 startup；外层 `running_setuid` 判断真实／有效 UID 或 GID 是否不同，与用户显式给出的 `-p` 模式不同。remote 分支需要非交互、非 login、不是 sh、有 command、shell level低于2，且 `no_rc` 为零；SSH 判定或网络判定成立便执行 bashrc。这里没有 privileged 判断。后面的 BASH_ENV 分支才要求 privileged 为零；`--norc` 则直接设置 remote 分支所检查的 no_rc。

在启用 getpeername 的 `isnetconn` 实现中，失败时仅 ENOTSOCK、ENOTCONN、EINVAL、EBADF 返回否定；EPERM 不在这个集合，所以返回肯定。该结论受原编译宏分支限定，不扩展到不使用 getpeername 的平台实现。

因此，**如果**实际 Bash使用该实现、满足上述启动条件，而且当前 seccomp确实在该调用上返回 EPERM，就会先进入 bashrc，再执行包含 snapshot恢复的 command。这个解释与 root已观测的提前 source相容；`--norc` 正好关闭该入口，`-p` 的独立 BASH_ENV保护继续保留。

ROG binary身份、实际 diagnostic、仓库seccomp行和7行候选由root已有收据提供；本次不借其缩写伪造完整SHA。GNU直接源／Debian读取不可达，最终证据明确限定为5.3系列镜像源码。没有native、trace、测试或权限变动；候选是否修复原例仍交既定原native验收。

机器收据：`a9a61bb9fd038e782254f68abd3f30d8db358c10`。
