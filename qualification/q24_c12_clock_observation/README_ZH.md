# Q24 原 500 ms 截止分支的实际次序

一次原生观测复现了两个原测试失败。两例中，最外层客户端实际选择自己的 500 ms 定时器均早于同一请求的最外层服务开始关闭 socket。结果直接来自同一测试进程的单调时钟、原错误分支和 shutdown 调用两侧的记录。[唯一作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45145844152/job/137594801115) [实际诊断源码](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/910fee9b64cafdf1da406b815d64e51f7c32fc20)

| 真实测试第一次读取 | 客户端用时 | 实际选中定时器迟于已设截止 | 服务开始关闭迟于客户端选择 | 六个原所有者读与“客户端进入至选择”交集 |
|---|---:|---:|---:|---:|
| healthy，在明确撤销之前 | 501.155 ms | 0.730 ms | 9.147 ms | 472.347 ms |
| timing | 502.260 ms | 1.840 ms | 15.788 ms | 469.390 ms |

healthy 的顺序为 (cut, request) = (4,4), (3,8), (3,9), (4,5), (3,10), (3,11)。前五个实际写出响应。第六个进入真实处理并完成 coordinator 的 decision 检查，随后在首次 cell.read_learning_selection 调用处失败。服务端于进程时钟 59,069,346 µs 记录 handler 错误，晚于外层调用方选择定时器 1,248 µs。该阶段原日志给出底层配置 Unavailable。req11 服务开始 shutdown 于 59,069,347 µs，返回于 59,069,355 µs。最外层服务开始 shutdown 于 59,077,245 µs。观察到的顺序无法证明底层选择读取因调用方取消而失败。第一次健康断言已失败，之后预定的主动撤销未执行。

timing 的顺序为 (4,6), (3,12), (3,13), (4,7), (3,14), (3,15)。六个内层请求均完成了真实写回。最外客户端在进程时钟 97,288,327 µs 选择定时器。最外服务的原 handler 后来成功返回，随后原有时限检查于 97,304,112 µs 选择 clock_expired，开始 shutdown 于 97,304,115 µs。两进程的时间原点各自独立，表内比较均在单进程内计算。

## 对照范围

旧红作业的实际 prospective merge ae404b29 与 #7016 的 c12ee03f 对应相同 Git 根树 9554ddb1。十四个修改前的原代码文件逐个匹配该树。观测作业保留原 Agentd 四片、默认片内并发、500 ms、全部六个原所有者读与原断言。四片均实际远端执行，1550 过、2 失败、原 171 忽略。此作业只运行 Agentd 目标，旧全仓其他数百个目标造成的调度负载与新增记录开销均会影响具体用时。观测分支不构成生产修复。

旧 shard 2 的四个连续非重叠阶段合计 491,336 µs。该原件显示 req11 没有成功回包，缺少可以排序的外层选择与 shutdown 时刻。本次证据为上述两次新复现建立次序。旧原件保留自己的可识别范围。[旧 ZIP 和原说明](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/e3fce928e4395868148da24c1d91e83a5765e37a/docs/learning/evidence/musl-child-completion-20261123)

## 离线复算

本目录保存 GitHub 原 ZIP（工件号 14804747722）和标准库 Python 复核器。运行 `python3 verify_clock.py clock.zip > replay.json`，再执行 `cmp replay.json result.json`。复核器检查整个 ZIP 的 SHA256、各片原 test.log 的 SHA256、四个远端执行、两个原测试名、进程身份、实际选中分支、每项时间和各原读区间的交集。clock.zip 的 SHA256 为 `4f43ffedc4a4843c9396456944ac00b476f0b1b7ab97e3f0524555a514000026`。

旧读回独立使用 `python3 replay_prior.py /path/to/native-musl-comparison.zip`。history.json 是其输出。观测保留错误分类、时间与本地请求编号，不记录帧体或凭据。

