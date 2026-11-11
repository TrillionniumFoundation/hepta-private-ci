# MEM8 执行检查点 v13

本检查点记录已实际观察和完整回读的工程进展。**10 项科学/采用 blocker 仍未关闭；不能宣称全量完成。**

## 当前源码与实际门禁

源码 PR #5935 已更新到 `189711e3563ea13a5328d52e99a286f082045b98`，完整 tree `e253b99e0a5c3b3a680569da0d224fabff0781ba`，父提交为 `2ae5215beaf8d7b7df111a090b82134beae2683d`。69 个累计修补路径已逐一发布并完整回读。此前 source-only 格式化、调用边界和完整树扫描通过。

同一完整 tree 的 `just bazel-lock-update` 已实际成功：本地资格提交 `65ff5d15075f9193664ab0b5f74e2264cfe0c24c` 上执行一次，exit 0、lock 无漂移、donor 和工具未变。它和发布提交是两个不同 commit；这里只关联同树 lock 证据，没有转移 native 测试结果。Root 已验证 43 个档案成员与原命令 receipt/raw log。

原 blocking run **43002359918 / attempt 1** 已结束：37 jobs = 23 成功、10 失败、4 跳过。10 个失败中含 Windows 汇总和 CI required 两个汇总 job，不计为额外测试执行。普通 Actions 使用 merge commit `83b67d85bc8ba58ca1f4e758efdc32dbe5f11c58`，其完整 tree 与源码提交相同，身份仍分别保存。

Windows private 的 signed-credit 原用例在精确发布提交上通过：1 passed、0 failed、270 filtered、0 retry；原 receipt 的前后 source/tree 均 clean。此结果不覆盖全部 Windows 或系统恢复能力。

## 原失败被保留，候选尚未冒充成功

35 成员的原 CI 档案包含 6 份完整 job log、model/infer 候选与准确来源索引。Root 已从 Git 全文回读，逐成员和解压后 raw log 验证哈希，并从原行重算失败块。GNU 和 musl 中相同的模型失败 payload 不计作独立执行；Windows hard-link 的三次原 attempt 与末尾重印严格分开。

模型目录的 readiness 检查存在一个确定的候选回归：mock 的 ModelsResponse 自定义序列化再反序列化会补出 model_messages，而原比较拿缓存对象与转换前 fixture 相比。修补只按实际 wire 往返生成 expected cache models，保留全字段比较、HTTP 单次 mock、原 RPC 断言和预算。此前静态审阅漏掉了这一点，勘误已收录。

Windows 文件字节负控原先在 append-only handle 上调用 set_len，实际先收到 OS5，尚未进入篡改观察断言。修补让这个专属负控以 fresh read/write descriptor 进入原 private replay/lock 路径，在同 FD 等长改写，保留字节、缓存、cursor 与持锁断言；生产 append-only open 没有改变。

远程控制 fixture 的 WebSocket 入口绕过了同端口模型 GET 分流。候选补上分流后继续使用原 WebSocket parser，保留缺升级头、截断 EOF 和已预读 trailing junk 的拒绝语义。原失败日志没有记录被 accept 的 request-line，因此这里只确证 fixture 缺口和症状一致，不把原请求身份写成已证实。

受限测试时钟、启动/Matrix/Neuron 诊断也已完成静态审阅。诊断不等于修复；Neuron 原 30 ms RPC、Conflict、单次 worker 和文件字节断言都保留。

## 新一轮源码请求仍待对账

92 路径、相对已发布提交新增/变更 31 路径的 source-only 输入已冻结。原请求与一次完全相同幂等键的对账均遭遇 MCP 前端超时，没有 job ACK。输入文件在一次只读观察中为 FileNotFound；登记快照 continuation 又因 membership changed 被服务拒绝，已停止，不重建快照、不换 key 重放。

所以这一轮 source gate 的**任务身份、是否实际执行、终态均为 UNKNOWN**。未声称格式化、编译、native 或 Bazel lock 已覆盖这个新候选。原请求、两次前端错误、只读结果和停止对账证据单独保存。

## Mac 与后续 CI 的边界

Mac artifact preparation v2 在原 300 秒下载上限结束：fetch timeout/-9，外层正常记录 exit 1，0 次 zsh control、0 次 native/model 执行。Root 逐字验证外层 18 成员、原始嵌套 18 成员，以及 job/nonce/exit witness/raw log 的绑定。此前 30 秒 fetch 失败保留。

一次独立 HEAD-only 观察在 10.353 秒后得到 HTTP 200，跟随一个 HTTPS redirect；没有下载 bundle 或运行 zsh。其 supervisor job identity/terminal witness 未恢复，只读安全结果完整回读。这不改写两次下载超时，也不构成原 Mac 失败的复现。

MEM run 43002359609 的 11 个 memory 和 6 个 Agentd 用例已通过；随后 qualification feature 检查未产出 receipt，protocol/fix 未执行。原始来源审查确定 workflow 从错误的 CARGO_TARGET_DIR 位置寻找 Nextest JUnit；最小 workspace-relative 路径修补待下一次源码门禁。不能把整个 MEM run 标绿。

启用 Windows sandbox 后的既有 hard-link 写入、ordinary-host deny ACL 下删除、plugin cache OS5、image-edit mock 未到达，以及 Mac 的剩余失败继续保持未关闭。任何仅覆盖某一种写入口的防护都不代替整个沙箱边界证明。

原 Blob size job 在 Fence readiness、checkout 之前失败。主 run 结束后，对同一 job 的一次定向重跑 API 已被接受；新 attempt 结果仍待观察。先前因为 run 尚在执行而收到的 403 保留为“未执行”，没有重跑 native 失败 job。

## 采用与真实效果

本阶段新增 scored actor episode 为 0；没有重放原 admitted provider turn；原 provider terminal 仍 UNKNOWN。没有新增 source exposure 准入。档案恢复、测试 owner fixture、源码门禁或 CI 部分成功，都不能替代真实 owner/独立信任域/实际效果状态的冷恢复和后继任务收益。全部 10 项采用 blocker 继续按原门槛保留。

详见本目录的 CHECKPOINT_REPAIR_V13.json、ROOT_BAZEL_READBACK_AUDIT.json、ROOT_EXTRA_READBACK_AUDIT.json、ROOT_CI189_READBACK_AUDIT.json 与对应不可变原始档案。历史 v12 的当时 pending 状态保留，由本检查点补记后续观察，不回写历史。

