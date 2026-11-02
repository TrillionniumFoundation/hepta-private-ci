对固定完整进程集合 I，记 r_i(t) 为进程 i 的 RSS，H_i 为覆盖其整个生命周期的 RSS 高水位上界，则

\[
\sup_t\sum_{i\in I}r_i(t)\leq\sum_{i\in I}\sup_t r_i(t)\leq\sum_{i\in I}H_i.
\]

共享页被多个 RSS 重复计数只会使这个上界更保守；不同进程峰值不同时发生也使它更松。它不等于同时 RSS 峰值，也不等于唯一物理内存峰值、cgroup 的匿名页/页缓存/内核责任或设备内存。

本轮两个夹具为每次 fork 建立完整角色清单，并将外层 wait4 与各父进程的 wait4 收据合并，要求每个 namespace PID 恰好出现一次。每个最终 ru_maxrss 作为对应进程的高水位上界；如果它还携带已等待后代的最大值，额外重复只使求和更保守。内存求和允许这类保守重复；CPU 的嵌套累计不允许重复相加，CPU 一律取唯一外层阶段收据。

实际已核对父、子、孙、短命任务、根退出后收养与共享的 32 MiB 页面。短命任务另外触碰 48 MiB 页面，在粗粒度采样中没有驻留内存读数，但其最终 wait4 收据仍进入上界。该验证只适用于完整受控 fork 树。任意研究/生产命令缺少完整创建和逐进程退出收据时，不能从已观察进程数或一个最大进程的 ru_maxrss 推断整个族的上界。

Linux 的 ru_maxrss 是最大进程驻留集指标，不能把 RUSAGE_CHILDREN 的该字段当整个进程树的同时峰值。参考主来源：[Linux man-pages](https://www.kernel.org/pub/linux/docs/man-pages/book/man-pages-6.05.01.pdf)，[Linux getrusage 实现](https://kernel.googlesource.com/pub/scm/linux/kernel/git/stable/linux/+/refs/heads/linux-5.15.y/kernel/sys.c)。这里给出的是在完整 H_i 覆盖前提下的数学推论，不是对本容器宿主内核版本的源码证明。
