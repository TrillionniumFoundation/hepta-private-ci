# Q24 原生读取中实际运行与等待的时间

c12 同源的 Agentd 原目标在 Linux musl 远端四个分片上执行一次，保留默认并发、500 ms、六次原所有者读取及现行断言。四片分别通过 379、393、384、396 项，分别忽略 40、36、51、44 项。原 test.log 中 healthy 与 timing 均为 `ok`。两例的首次证据读取均实际写回六次，并通过原 attestation 相等断言。healthy 还执行了主动撤销后的原拒绝断言。上轮同源两个超时仍单独保留。[本轮作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45152505670/job/137617143440) · [本轮诊断源](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/c25cf4146572501427cc35f1c03f4d585c1c4758) · [上轮双失败实物](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/9b81625020bde536ffa1c13e7b31834a13cfe8d2/qualification/q24_c12_clock_observation/README_ZH.md)

每格给出单调时钟经过时间 / 同一同步服务线程实际运行的 CPU 时间，单位均为毫秒。两调用之间的负载不同。子项计时包括其子调用，表中各行不能相加。600 次、300 次均指六个所有者请求内部实际进入的操作数。

| 区间 | 每次证据读取的次数 | healthy 首次 | timing 首次 |
|---|---:|---:|---:|
| 调用者端到端 | 1 | 319.303 / 未采集 | 471.152 / 未采集 |
| 六个所有者处理区间合计 | 6 | 294.696 / 233.822 | 436.068 / 277.456 |
| require_task_input_current | 18 | 131.637 / 107.891 | 196.916 / 126.082 |
| Cell selection | 12 | 92.417 / 75.752 | 135.720 / 88.147 |
| 重新读取并验证 registry CURRENT | 300 | 104.621 / 79.327 | 166.209 / 99.237 |
| Control store.load | 600 | 98.006 / 77.758 | 142.333 / 90.149 |
| 其中的当前绑定 digest() | 600 | 27.495 / 20.121 | 37.933 / 23.062 |
| 核 selection 签名 | 300 | 16.097 / 14.121 | 20.480 / 15.563 |
| retained FinalUse 的 authenticate | 300 | 26.352 / 23.623 | 34.571 / 25.756 |

六个处理区间的经过时间减线程 CPU 分别为 60.874 和 158.612 ms。差额包含 I/O、调度与其他等待，现有记录只识别其总量。每种已标注的 mutex/try_lock 获取在两个首次读取中各自累计均不足 0.3 ms。原计时取自服务现有同步路径，增加的计时、记账及输出会影响测量。在本次两条通过的首次读取中，无法用这些差异反推出旧失败时的 CPU 或等待。

## 实际错误分支

首次 healthy 与 timing 的所有者均没有错误记录，两次最外客户端均选择 `select_frame_ok`。以前未撤销的 healthy req11 在 `read_learning_selection` 返回 `Unavailable`；该次失败的计时归档没有本轮的内部错误类别。两次实跑之间不存在可拼接的同一请求。

healthy 明确撤销后的第二次读取用时 4.074 ms。服务进入 (cut=4, request=6)，最早记录的错误是 `live.revalidate_and_clock: invalid_other`，随后为 `live.authorities: Unavailable`、`task.live_current: Unavailable`、`input.task_current: invalid_unavailable` 与 `input.all: error`，客户端选择 `select_frame_error`。此处两个 mutex 获取与时钟成功，随后没有进入 registry、签名或候选文件的内部验证。源码在 registry 调用前会检查恢复状态、时钟和撤销边界。本轮静态类别只区分到 `invalid_other`。主动撤销之后的拒绝和旧未撤销 req11 的根因须分别解读。[执行的原断言](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c12ee03f3185d5a13949faca54f066dfd634e509/codex-rs/hepta-agentd/src/circuit_next_use_command_owner_tests.rs#L584) · [原验证顺序](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c12ee03f3185d5a13949faca54f066dfd634e509/codex-rs/hepta-agentd/src/neuron_generation_update_selection.rs#L206)

## 可独立优化的范围

`control.head_digest` 是本轮单独计时的纯计算。调用者传播错误。函数检查三个 StableId、generation、writer epoch 及六个非零摘要，然后编码并生成摘要。如果研究复用，应在每次物理读取、时效、签章及全部校验保持时，只考虑完整不可变绑定相等时的纯编码与散列。此次观察只计数，不保存输入值，尚未核实完全相同绑定的实际命中率或收益。registry 总耗时还含当前头、receipt 与物理快照验证。把 registry 总耗时视为可缓存纯计算会高估收益。以前经过资格验证的有界解析复用已在该源码中。本轮没有新的已验证生产补丁。[绑定校验与摘要](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c12ee03f3185d5a13949faca54f066dfd634e509/codex-rs/hepta-neuron/src/cell_generation_current.rs#L82) · [Control 原读取](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c12ee03f3185d5a13949faca54f066dfd634e509/codex-rs/hepta-agentd/src/neuron_generation_current_store.rs#L187) · [原 registry 读取](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c12ee03f3185d5a13949faca54f066dfd634e509/codex-rs/hepta-learning-artifacts/src/owner_read_view.rs#L66) · [已采用的历史资格](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1bbd691b829ca827bd353d3c77c4856b61e95bc4/qualification/q24_c12_clock_observation/PERFORMANCE_ZH.md)

## 离线复核

GitHub 工件 14807288533 的原 ZIP 为 actual.zip，SHA256 为 `72f7baef7dae44c669480b082d19e2b3f0232dadabc98f7ab8f056d35ba4cd6d`。复核器校验整体 SHA、十五项源预像的清单、原测试和 BUILD 两个精确 Git blob、四次首次远端执行、四组 test.log 与 XML、两个具名结果、每个读的 cut 和 ID、真实写回、每个 CPU 时钟读数及类别计数。原有阶段的日志与输出均在 ZIP。所有者观察器使用同一线程的 CLOCK_THREAD_CPUTIME_ID 和单调时钟，不输出读取的数据、路径或凭据。

先前工件 14806422283 保存在 first.zip。它记录新增分类器的借用类型编译错误 E0308，执行原测试数为零；修正涉及诊断闭包与源码溯源预检。两份原件均保留。[编译阶段作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45150817823/job/137611439619)

```sh
python3 verify_build_error.py first.zip
python3 verify_owner.py actual.zip > replay.json
cmp replay.json result.json
python3 summary.py replay.json > operations.json
cmp operations.json summary.json
```
