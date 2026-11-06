# r29 原默认工作区门：闭合原件

**ENGINEERING_DEFAULT_WORKSPACE_FAILED；科学 HOLD、权限 DENY_ALL。** 本组绑定 source52 commit `1e0910becc37383e6d17ecf861ea844fd07d8862`、staged tree `211f15baff19095e8c98bcea2b0ed99ca2270ade`，195 个变更路径（181 Rust＋14 other）。原生 HEAD 仍为 framework `bef6fa7645df9df12b69fda499e97eed25de6c75`；Git 对象身份不冒充 checkout。

原命令是 `just test --locked --retries 0`，没有 `-p` 或新增 filter。执行前的本轮 metadata 原进程退出 0，193 个 workspace members 与 193 个 default members 的实际 ID 集合一致。原 workspace 进程返回 `100`，有效返回 `100`，外层自然返回 `100`。

完整原日志有 20228 个唯一 binary/name 结果：20227 PASS / 1 FAIL / 0 TIMEOUT；另报 130 skipped。

本轮工作区失败，最终 fix/fmt 的工作区 PASS 前置未满足；归档成功不会授予收尾执行资格。

原 gate 总时长 `2768.9677839279175` 秒。完整日志见 [workspace tests log](original/evidence/native-workspace-r29-tests.log.gz)，本轮完整 metadata 见 [metadata](original/evidence/native-workspace-r29-metadata.json.gz)，每个原错误字节块见 [failure-blocks/INDEX.json](original/failure-blocks/INDEX.json)。结果由完整原日志独立解析，排除 Summary 后的重复失败摘要，没有将原 r28 数字与工作区结果相加。

## 原件与核验

- [CLOSURE.json](CLOSURE.json) 和 [INDEPENDENT-READBACK.json](INDEPENDENT-READBACK.json) 是本次新读回结论。
- [checkpoint-r29-closed.tar.gz](checkpoint-r29-closed.tar.gz) 原样保留 315 个 regular 成员、314 条 INDEX 和全部 195 份源码。每个源码的 raw SHA、Git blob、原 Git mode 与双锁均已核验；tar 的传输权限单独处理。
- 原 r28 的 26 件 gate 原件加自然终态保存在 input/r28-prerequisites；其 Python32、四包 strict 和四包1564 PASS 是本轮启动前置，独立于本轮统计。旧 r24/r26 失败和启动 null 快照没有被改写。
- 全部原 log、rows、metadata、raw rc、receipt、resources、source guards、controller 输出、runner 和闭合授权均保留。大 UTF-8 文件采用 mtime=0 gzip，逐项解压字节相等；同字节大文件通过映射去重。
- [ORIGINAL-MEMBER-MAPPING.json](ORIGINAL-MEMBER-MAPPING.json) 和 [SOURCE-DESTINATION-MAPPING.json](SOURCE-DESTINATION-MAPPING.json) 提供完整定位；源码和原双锁仅留在原 archive，不重复复制第二棵源码树。
- exporter 自然退出 0 仅证明归档成功，不改变原 gate 结果。所有当前计数来自本轮原件，没有硬编码当前测试数量、重跑测试或借用旧轮次资格。

本门保持原默认 features、ignored/platform/service 条件；不宣称全部 feature、平台或真实外部服务覆盖。最终 fix/fmt 的执行和归档需要后续独立证据。本地读回没有执行 Rust、Cargo metadata、format、Git 命令或 native 任务。

附件纯字节复核：`python3 verify_and_assemble.py --verify-only --output <本目录>`。
