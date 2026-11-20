# macOS 两处测试 fixture 路径修正

238 CI 的六项 external-material 正控在真实 macOS 临时目录路径上首先得到 ENOTDIR；产品原打开路径拒绝 symlink 祖先，而 macOS 的系统临时目录包含别名祖先。另一个 causal 控制已经用 canonical root 创建 owner，冷重开却重新使用未 canonical 的临时目录。

补丁只让六个材料测试在系统临时目录的实际 canonical parent 下创建 TempDir，并让 causal 冷重开使用与创建相同的 canonical root。原恶意 symlink／alias／材料篡改拒绝断言全部保留；产品路径安全检查、root 创建 helper 和 Cargo.lock 未变。两个候选文件的完整 SHA256 见 READOUT.json。

真实 `just fmt --base 238fc484...` 已退出 0，0.28308525 秒。随后 recorder 对 inherited sparse 文件的读取假设失败，未执行 native；该失败原样保留。修正 inventory 记录明确区分 11,751 个 materialized files 与 3,813 个未 materialized 的 skip-worktree Git 身份，没有将后者说成实际读取。所有 codex-rs 文件已 materialized。第二次 original locked/offline 项目命令因缺固定 tungstenite 依赖退出 101，0 native case。

第三次 Git-library 下载在约十四分钟无新增 Rust／测试日志后，经自有 PTY 一次 Ctrl-C 退出 -2；没有 PID kill，后续实际观察全部已知旧子进程消失。其网络 pack 字节当时未测量，所以不能证明网络停止或死锁。原 wrapper RESULT/EXIT 未写出，没有补造终态。

第四次沿用原 locked graph，通过 Cargo 支持的 Git CLI 获取缺失依赖。固定 tungstenite 已获取；crossterm 出现真实 connect timeout 和 HTTP/2 early EOF，正在 Cargo 自身的有限重试中。工具将原 PTY 标记 lost/target_reboot，但 07:58:59 UTC 操作系统读回仍发现同一 runner、just、nextest、Cargo 与新 Git child 存活，RESULT/EXIT 尚不存在。继续沿用这一执行，没有另开 Cargo owner；当前不声明 native 通过。

50 份稳定原件（prepare、native1、native2、已中断 native3、native4 固定输入及明确时间的观察）归档为 904,408 bytes，拆成两个不超过 480,000-byte 分片；完整归档 SHA256 为 `4d56a039b30841d5843f1d526adb1334a25af4b6d1fb27986c814a47fd3949ea`。所有源字节再次核对，云端重新拼接并逐 member 的 mode、长度及 SHA256 回读一致。它不包含尚不存在的 native4 终态。

本工作无模型调用、无训练、无 E6 完整业务父执行，不授予联合十项资格。

## 后续真实终态

08:16:38 UTC 独立 OS 观察确认旧 owner 全部已退出，原 wrapper RESULT 实际存在，SHA256 `dd55367752fc4bef8fbd6734f5a98dc586cc71044397b2c7c500dd6f041308c3`，exit 1。原项目命令 exit 101，用时 3,085.995982 秒，owner 3,087.345731 秒，依赖下载失败，stdout 仍为 0，没有通过的 Rust／native 结果。所有候选和保护字节仍相同；早期工具 lost 状态与进程存活的矛盾观察继续保留。

另一个隔离目录只获取了同一锁定 crossterm commit 的 shallow Git 对象，实际 fetch 22.761068 秒、owner 22.896533 秒；commit／tree 原 Git SHA 重算及严格 fsck 通过。它没有启动 Cargo、原生或模型，也未写全局 Cargo cache。后续只在原 native4 真正终止后沿用这些确切对象继续原项目验证，结果另记。
