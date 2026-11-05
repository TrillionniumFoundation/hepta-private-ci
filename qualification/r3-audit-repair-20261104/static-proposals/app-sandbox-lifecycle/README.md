# App disconnect 后 sandbox 子进程残留：独立静态核查

**已确认生命周期缺口存在于原 5 秒退出验收；尚未确认本机父死亡信号是否在 exec 时被清除。** 当前交付是固定源码、原始观察和最小修复方向，没有生产补丁，也没有运行新的原生实验。

## 原始事实及限制

完整诊断包 `106cf2684ee66709db063d714c5d31f86d42fd45` 的 9 个内嵌文件已逐字节和 SHA256 核对。原源码树为 `f8251e1d14fa8524ab469281296cd4cf708f173c`，原 App case 在 5.491 秒失败，保留原 5 秒 marker 退出预算和零重试。

观察链为 App → bwrap → inner sandbox helper → Python。外层 bwrap 的 PID/PGID 为 702763，内层 helper 和 Python 的 PGID 为 702768。外层在第一次观察约 0.310 秒后不再出现；内层以同一 PID/starttime 身份被重新收养，仍处于 sleeping 状态直到原用例结束。它们并非仅残留 zombie。原观察没有记录 signal syscall、PR_GET_PDEATHSIG 或 LSM 转换，因此不能从该链直接宣布某个 kill API 或 AppArmor 是根因。

实际系统件已另有只读收据 `92e337c9814e0dd761fda33b277a68387cd7fa4f`：/usr/bin/bwrap 为 80,424 B，SHA256 `523da3e7399044be5163aee6f57a77a6bef7454376e28f0a0627920bae1b76b6`，版本 0.11.1，Ubuntu 包 0.11.1-1ubuntu0.3，内核 7.0.0-42-generic。上游 v0.11.1 源码可以核对机制，但不等同于独立重建过这份 Ubuntu 二进制。

## 同源调用链

当前 launcher `d4e9b521` 始终加入 `--as-pid-1`。bwrap 参数同时保留 `--new-session`、`--die-with-parent`。普通无 synthetic/protected-create 目标的路径直接 exec bwrap；另一条清理 supervisor 路径才在 fork 后调用现有 `terminate_with_parent`。这个旧函数没有为真正的 inner namespace reaper 建立跨 exec 的稳定父身份。

inner `linux_run_main.rs`（`b50f1973`）验证没有 effective/permitted capabilities，应用原限制后 fork 用户命令，再安装原信号转发并执行 waitpid(-1) 回收。当前该路径没有重新建立父死亡信号，也没有持有指向 exec 前父进程的稳定存活引用。

三个选项都有实际合同，不能为修退出而删除：

| 选项 | 不能删除的原因 |
| --- | --- |
| `--as-pid-1` | 原 managed_proxy 测试明确要求用户命令的 PPID 为 1、PID 1 的 Seccomp 为 2，且 PID 1 与命令都比父测试多一个 filter；另有真实孤儿回收断言。 |
| `--new-session` | 它隔离控制终端；通过取消 session 隔离来恢复同一进程组会改变原安全边界。 |
| `--die-with-parent` | 它仍提供 bwrap 的父子退出链，不能用新机制为由移除。 |

原测试源码为 `codex-rs/linux-sandbox/tests/suite/managed_proxy.rs`，blob `2b03c9d020f4a1af239010ad1bae45f10a989e73`。这三例属于 codex-linux-sandbox::all。

上游 bwrap v0.11.1（`687ed71f7044ca997a100eef847a5de71164581b`）在 monitor 中和最终 exec 前设置 SIGKILL 父死亡信号。官方内核 v6.12 的 AppArmor 源码确实存在 profile 转换时清空 pdeath_signal 的分支，但这仅证明一种可发生的机制，不证明本机执行了它。Linux 的合同还明确：PDEATHSIG 不补发已经发生的父死亡；跨 PID namespace 的父进程可使 getppid 返回 0。因此单纯在 inner 重设信号并检查 PPID 0，仍留有竞态。依据：[PR_SET_PDEATHSIG](https://man7.org/linux/man-pages/man2/PR_SET_PDEATHSIG.2const.html)、[PID namespaces](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html)。

## 最小安全方向：在最终启动点捕获自身 pidfd

若临时只读诊断证实需要在 inner 恢复关系，建议采用稳定 pidfd 加原父死亡信号，避免只用数字 PID。

1. **在真正执行 exec_bwrap 的进程中、所有 cleanup fork 之后，打开指向自身的 pidfd。** 该进程随后成为外层 bwrap monitor。不能在 build_bwrap_argv 或清理分支 fork 之前取得：那样捕获的是祖先 supervisor，而不是 inner 的实际 bwrap 父进程，会漏掉 bwrap 提前死亡。
2. 在私有调用点区分真实 inner-reaper 启动与 /bin/true preflight；只有前者携带新的内部生命周期 FD 参数。最终用户 argv 仍在原分隔符之后，不能被解释成 launcher 元数据。
3. 沿已有 preserved_files 所有权链把 FD 传过 system 和 bundled exec。上游 bwrap monitor 会关闭自己的额外 FD 副本，但该 pidfd 已传给 sandbox 子进程；关闭副本不会伪造目标进程死亡。普通管道不能直接替代，因为 monitor 会在仍存活时关闭多余写端。
4. inner 立即接管 FD 并恢复 CLOEXEC，保留原权限校验。先设置 SIGKILL 父死亡信号，再对稳定 pidfd 做零超时 poll。原父已退出的 IN/HUP 必须使 namespace init 退出；错误或无效 FD 必须拒绝。只有明确存活才允许继续。
5. 在 fork/exec 不可信命令前关闭 pidfd，并证明 reaper 后续没有能再次清除该关系的 exec 或 credential 转换。不能把任意用户传入的数字 FD 宣称为已认证父身份；保证须来自完整私有构造链。

这个顺序覆盖父在 exec/重设前已经死亡的窗口，也覆盖重设与存活检查之间的死亡。检查后仍活着时，既有直接父关系加恢复的信号接手后续死亡；PID 1 退出会由内核清理 namespace 子进程。pidfd 的稳定身份和退出可读性由 [pidfd_open](https://man7.org/linux/man-pages/man2/pidfd_open.2.html) 定义。

这仍需明确兼容性决定：pidfd_open 自 Linux 5.3 提供。ENOSYS、EPERM 或原 syscall 策略拒绝不能静默退回不安全的 simple rearm。也不能把该局部保证外推为 App 父进程在 bwrap 自身注册前死亡的所有启动窗口都已解决。

## 必须保留的真实验收

- 原 App disconnect case、同一实际 feature graph 和 helper epoch、原 5 秒 marker 断言。完整 raw/JUnit 必须证明 inner helper 和 Python 都实际退出。
- 新增真实“父在 inner 重新建立关系前死亡”受控窗口。用本次确切 owned launcher 身份退出，再释放内层 gate；必须禁止用户命令被接受。去掉稳定存活检查的反事实应暴露该窗口，不能把任意超时当作因果证据。
- 原两例 seccomp-filtered namespace reaper 加一例 orphan reaping 保持完整；bubblewrap/proc 不可用的提前返回不算该合同通过。
- FD 必须在用户代码运行前关闭；无效 FD 在运行前拒绝；普通路径与 cleanup-fork 路径都绑定真正 bwrap，preflight 不受影响。system 与 bundled 证据分开。

Root 的临时观测补丁 `b8fd274928353fc28f79ef5bb653b4466d48b439` 只增加自身 PR_GET_PDEATHSIG/标识、原 killpg 返回值和按固定 fixture process id 转发诊断行；没有 setter、安全参数或原断言变化。其运行结果不在本收据内，结束后仍须精确恢复 `f8251e1d`。
