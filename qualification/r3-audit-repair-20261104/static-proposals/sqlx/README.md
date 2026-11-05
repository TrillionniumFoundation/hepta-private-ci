# SQLx 原生连接生命周期所有权候选

## 当前结论

这是一个尚未编译、尚未执行的依赖层源码候选。它为显式调用者提供真实资源所有权从 worker 启动前到 SQLite 原生连接关闭后的保留机制，用于补上原 after_connect / hook 注册前的取消缝隙。它没有改变项目依赖、共享原生工作树、Git ref 或 Current 授权路径。

当前完整补丁为 `abe067bc6f2ca9601eef83b0cd4e0db4811827ac`，5 个文件、467 行新增 / 9 行删除，共 476 行格式化前变更。原生产逻辑为 77 行变更；其余为测试模块挂接和 4 个真实物理控制。精确逐文件身份、原源与反事实补丁见 repair-manifest.json。

## 已对齐的真实来源

实际缓存中 sqlx-sqlite 0.9.0 的 .cargo_vcs_info 指向 `003b698e99e024f3621b8043a2426fde5b741171`，不是此前检查的发布 tag commit `75bc0487eb661da811bb7a3c5d158f1bd463fef4`。增补证据 `246b438e9f8026abaa4c48b62dd4d55ffa470cee` 已逐文件确认：12 个引用源文件相等，SQLite/Core 子树相等，17 份原生收据完整文本重新计算的哈希一致，11 个实际 Rust 文件与 Git 源相等。

原生执行者读取的 SQLite crate 归档 SHA-256 为 `488e99c397a62007e4229aec669a179816339afc6d2620ca6fa420dbee2e982c`，与真实 Cargo.lock 相同。这里独立复核了收据完整成员文本及其哈希，没有声称另行下载、解压了该二进制归档。实际规范化 Cargo.toml 的 dev-dependencies 为空；新控制只使用原正常依赖，不借未发布的 sqlx 测试宏。

## 生产合同

显式 API 接收拥有实际资源的 opaque Arc。SQLx 将其副本放入 EstablishParams，随后才启动既有 worker。ConnectionHandle::open 的拥有型参数跨越真实 sqlite3_open_v2 调用；有效的原生 handle 在任何错误处理前获得该所有权。NULL 结果保持原 OutOfMemory 错误，非 NULL 的错误 handle 仍按原逻辑清理。

真实 sqlite3_close 成功后，字段才可以释放资源。关闭失败时，在原 panic 之前遗忘该所有权，防止 unwind 把仍在使用中的保护锁提前释放。此失败路径刻意保留到进程退出；即使之后外部 unsafe 调用最终关闭了 SQLite，也不会恢复该所有权。这是可用性代价，原错误没有被变成成功。

默认 None 的调用者不改 SQL、权限、后端选择、关闭调用和错误路径。私有 Debug 输出会增加一个可选字段，不能声称其字节不变。Options / pool 的副本可以让资源保留更久；调用方不得让 token 反向拥有这些 options 或 pool 形成循环。API 不认证 Current、不检查 lease / expiry / revocation，也不替代 commit hook。

## 四个物理控制

| 控制 | 必须实际发生的条件 | 物理结论 |
|---|---|---|
| native open 取消 | sqlite3_open_v2 内实际 auto-extension 回调阻塞；drop connect future 与 options | 独立父进程新打开的锁文件仍拒绝竞争；回调释放、真正关闭后才能获得锁 |
| 初始 PRAGMA 取消 | future 持续驱动越过 establish oneshot，实际 SQLite progress 回调进入后才取消 | 同样要求回调仍阻塞时真实跨进程锁竞争失败 |
| pool 扩容、替换和取消 close | 同时借出 5 个实际连接，TEMP marker 区分替换；取消 pool.close 后保留一个 detached 活连接 | 真实 SELECT 成功时锁仍被占有；最后一个连接关闭后释放 |
| 初始化错误与 BUSY close | 原 invalid PRAGMA 返回 code 1；真实未 finalize statement 导致 SQLITE_BUSY，原 WorkerCrashed，随后 sqlite3_step 仍返回 ROW | 正常初始化错误清理释放锁；BUSY 关闭失败继续占锁，直到自有子进程退出 |

4 个父用例通过普通 libtest main 启动各自子进程，SQLite 全局 auto-extension 状态仅存在于这些自有子进程中。一个 #[ignore] 支持入口只由父用例显式调用，不算第五个 PASS，也不能将其忽略计成产品资格。没有 constructor / pre-main、伪 nextest 协议或新增生产线程。

新控制的边界保持 5 秒。父进程先实际竞争文件锁，再查询子进程 gate_status；原生回调已经超时或提前返回时，不能把失败误计为因果证据。清理只处理各父用例的自有子进程和 reader thread；本结构不创建子孙进程。

## 负控与静态验证

两个反事实分别只移除 worker 所有权传递、只移除失败 close 时的 forget。前者必须在真实 callback 仍阻塞时观察到错误提前释放；后者必须先证明原始初始化错误、SQLITE_BUSY、WorkerCrashed 和真实 ROW，才观察错误提前释放。它们是最终 API 候选的反事实，不冒充未改 SQLx 0.9.0 的原失败。

`baa8eff98f3f88bd960d84f7985e23c8f5b406be` 保存了完整补丁、两个负控和两个恢复共 5 阶段的真实静态 git apply / --check 及精确后像验证。只运行了隔离源码重建，没有 Rust 编译或 SQLite 实验。

两个此前未执行草案保留：`38de56f757adfc08eb99c0ffd153a6c46400fc4a` 的 SqlSafeStr 推断已改为明确静态 SQL 字符串；`300fb77060af5f91fcd1ef108d79d85f9bf7009a` 的单次 poll 夹具已改为持续驱动到实际回调。这两项都是运行前发现并修正的测试缺陷，不能列为产品失败或负控结果。

## 下一执行顺序和仍开放的边界

先由 root / 唯一 CI 写入者冻结实际依赖采用目录、规范化 manifest、许可证与锁生成输入，再运行原 Cargo / Bazel 锁生成门。不能只把这 5 个文件放入工作区就声称替换已经完成。原生阶段需冻结 bundled、sqlx-core/_rt-tokio 和真实工具链 / SQLite 版本，分别执行两个严格负控、恢复精确后像、4 个正控，以及对应原 owning regressions / fix / fmt。

这里没有让任何项目 Current / state 调用者传入 OpenGuard。跨独立 pool 的所有权、完整 Current / recovery / writer / original_sender 接线、最终 use 和原平台资格仍需独立完成。之前的“no fork”只是 public API 研究阶段的范围约束；本候选来自 root 后续明确授权的依赖层源码准备，不是绕过永久禁止。
