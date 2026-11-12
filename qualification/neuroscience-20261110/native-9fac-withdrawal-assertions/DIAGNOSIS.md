# 9fac：四个首次 B 撤销断言的精确修正

原始执行为 job 131309678676，源码 9fac31e6f89569f0c582fc2a9cc2bf0b8f05c7ca；普通套件实际 1738 项，1726 PASS、11 FAIL、1 TIMEOUT，retries=0。原失败索引 blob 3d9e6598abd60bb22af198b74d3210492e9dcc86 保留，不能把本候选记作原执行通过。

## 因果与限界

四个既有测试在第一次撤销独立 retention B 后，仍期待 Evaluator 的 CommitUncertain。固定源码的服务端 original_state 已将原 Panel/Qualification 失败映射为 PredecessorUnavailable；客户端收到此状态即返回同一精确 variant，并且不归还原连接。Owners::completion 同时封存该主机，后续调用才返回 CommitUncertain。原同源 host 测试已经分别写出这两个次序的精确预期。

因此本差分仅把四个首次撤销断言的嵌套 Evaluation variant 改为 PredecessorUnavailable。Trainer 的 CommitUncertain 不变；publication 测试中 durable prepare 失败后再恢复、读取已封存主机的 CommitUncertain 也不变。所有方法、原 custody、签名、持久字节对照、原读取数量、128-frame 上界、真实期限和失败门均保留。没有用通用 is_err 或多 variant 接受替代断言。

原 panic 没打印第一次的实际返回值。上述定位来自已核验的固定源码完整映射及同源既有测试，不伪称已经获得重新执行结果。格式、编译、source QA、native 重跑均 NOT_RUN；root 将统一验证。

## 尚未修复的相邻失败

另外三个 C 测试经原只读 S Evidence 服务失败，其结果尚不能仅凭摘要判定为时间预算或 frame 用尽。该服务两端都保持 500 ms，回调内部真实读取 T/B 与原 S journal。需分别观察请求是否到达、实际回调结果和用时、同一原 exchange 的终态；本四行修复不改该服务或其门。

研究状态 HOLD；owner_decision=null。本补丁不含新增 bridge、Root bootstrap 或 12 方法 WIP。
