# exec-server：稳定句柄授权读取 RPC 的 fail-closed 修复

## 原始失败与实际合同

基于 head 1e91c5cf18272505508b9ce880fd34879bb6a546，GNU job124814581056 出现3项相关失败：
authorized_read_rpc_is_capability_gated_and_denies_outside_root；
file_system_bounded_authorized_read_enforces_limit_without_prefix::remote；
file_system_bounded_authorized_read_rejects_symlink_and_parent_escape::remote。

精确源码表明：
- lib.rs 的 local_environment_info() 以 local_file_system::stable_handle_authorized_read_available() 填充能力声明。
- local_file_system.rs 仅在 macOS 使用已探测的稳定句柄实现；非 macOS 的该能力函数恒返回 false。
- RemoteFileSystem::read_file_bounded_authorized 先读取服务器能力，未声明时就在客户端返回 Unsupported。
- 直接 FileSystemHandler::read_file_authorized 原先没有同样的能力检查。在 Linux 上它会落入普通 ExecutorFileSystem bounded-stream fallback，从而可能成功，尽管能力声明为 false。
- 原 local_file_system.rs 的注释明确指出普通 stream fallback 不足以证明该 RPC 所要求的 pathname/inode provenance。

因此修复不能靠将 Linux capability 改为 true。

## 最小产品变化

仅在 read_file_authorized 中，在现有 max_bytes 参数校验之后、任何用户文件操作之前，调用与能力声明相同的 stable_handle_authorized_read_available()。不支持时返回现有协议约定的：

code = -32603
message = "bounded authorized file reads are unsupported"

Linux 上，直接调用 stable-handle authorized-read RPC 将由此前可能使用普通 fallback 读取，改为明确拒绝。能力声明仍为 false。已遵从能力声明的 RemoteFileSystem 客户端本来就会拒绝，此处未扩大其行为。

这不关闭普通文件读取。fs/readFile、open/readBlock/stream、普通 LocalFileSystem bounded-stream API 均未改动；macOS 的实际稳定句柄 backend、路径授权、symlink/inode、大小限制和错误脱敏逻辑也未改变。

## 测试源码保持两条不同路径

1. authorized_read_rpc.rs 使用 ExecServerClient 直接调用 RPC，不经过 RemoteFileSystem 的客户端能力 guard。原合法路径和 outside-root 断言保留；新增 oversized、parent escape、Unix symlink escape。支持时检查原有字节/超限/权限拒绝；不支持时检查服务器返回 -32603 和固定 unsupported 信息。每种请求均在条件分支之前调用，不以 early return 或 ignore 避开。
2. file_system_unix.rs 的两项测试调用 RemoteFileSystem API。不支持时由现有客户端 guard 返回 Unsupported，这不等于服务器 RPC 已被执行。精确大小、超限、symlink、parent traversal 四个调用均保留，支持分支保留原来的 bytes/bound/path 拒绝断言。
3. 测试 helper 只为 Unix 测试保存其 actual backend 的能力信息。远端读取 environment.info()；本地非 Darwin 仍测试既有普通 bounded-stream API。元数据字段的 cfg(unix) 避免 Windows helper 的未使用字段，没有改变任何原测试的编译或执行平台选择。
4. 新增 symlink 请求仅在 Unix 构造，因为使用 Unix symlink API；原始跨平台 authorized-read 测试在所有原平台继续存在。

parent escape 的 PathUri 构造也已检查：from_host_native_path 只拒绝非绝对路径；绝对 TempDir 路径经 AbsolutePathBuf::from_absolute_path_checked/absolutize_from 词法规范化后变为 outside-root 目标，再由测试源码提交 RPC。它不是保留“..”段的原始 wire fuzz，也没有把客户端 URI 构造失败算成服务器拒绝。

## 已做与未做的验证

- 真实仓库 just fmt，在独立精确文件 Git fixture 中使用原 scripts/format.py、justfile、Rust1.95 和原 rustfmt.toml，退出码0。
- git diff --check 与反向 git apply --check 成功。
- 另一 agent 只读审阅了4文件 diff，检查了 guard 在读取前、字段 cfg 闭合、类型/所有权以及路径构造；提出的 parent-path 构造问题已用精确源码核对。
- **本地未执行原始 exec-server suite，未在本地发生所描述的网络 RPC 测试。** 原 workspace 声明187个成员，本隔离 fixture 仅恢复了 exec-server 的 manifest，缺186个成员及完整依赖/build context。格式通过不是编译或测试通过。
- 新头 native GNU/macOS/Windows CI 仍是接受门槛。需要实际验证直接 RPC 的支持/不支持分支、原路径与超限拒绝以及普通文件 API 没有回归。

没有改 Cargo.toml、Cargo.lock、MODULE.bazel.lock、协议 schema、任何产品权限白名单，或 capability 的返回值。没有把这3项原失败登记为已经通过。

