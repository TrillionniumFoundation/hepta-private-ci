# 固定 86dd 维护依赖恢复准备

本包核对 PREPARATION `86dd56a930277e0d1aef3e475e35c2b5d60b43b7` / tree `383ab85c39ef9d848252ef5c25922d13d9fae6c6` 的原维护入口、固定工具和 V8 配套材料。它提供供 Root 审阅、由 native agent 执行的外置恢复方案；本审计没有启动 H 进程、安装、二进制下载、Cargo、测试或源码/ref 写入。

完整机器可读方案为 [MAINTENANCE_DEPENDENCY_RECOVERY_PLAN.json](MAINTENANCE_DEPENDENCY_RECOVERY_PLAN.json)，Git blob `8936bfb0e0dbab9e471a158f1161567273798360`。其中包含每个确切 URL、release/asset ID、文件大小、SHA-256、15 个固定 repo 源码身份、原环境和 gate 入口引用。

## 当前已观察边界

17:21:40 UTC 原 metadata snapshot `33f5f7e4f7c40b2363924f866667ae4456e891bb` 表明：实际 c0f target `/data/hepta-utility-36fa-final-native-target-v1` 和历史 V8 archive 的指定路径当时不存在；同目录 bindings 是 39,884 B 普通文件。bindings 此次只 stat，当前完整哈希仍 Unknown。uv/ruff 仅在记录的历史 seed PATH 和当前 operator PATH 上解析不到，UV 四个安全环境变量为 null。这些事实不代表全机未安装工具或所有其他缓存都不存在。

原 c0f input `d64b521f2cfaa36039d0b4a2b4d7a5774433f0b1` 先载入 b19 的环境 seed，再显式将 CARGO_TARGET_DIR 设为上述 `/data` 路径；真实 RUNTIME `0dd826e7040f841ee2f8d056c190407cf4af2a49` 与 TARGET_RUNTIME `68934b7a5b168585bec7116b4bec944f617d716e` 相符。本包没有把 b19 的另一个 `/home` target 当成 c0f 的实际 target。

## 固定材料

| 材料 | 版本 | 字节数 | SHA-256 |
| --- | --- | ---: | --- |
| uv-executable-archive | 0.11.3 | 23,914,165 | `c0f3236f146e55472663cfbcc9be3042a9f1092275bbe3fe2a56a6cbfd3da5ce` |
| uv-archive-checksum-text | 0.11.3 | 101 | `87b44e8a7b4ea30a8f515dedeb8ea5fddabeb9e45bc7586b738cc71cd7d2d59c` |
| ruff-locked-wheel | 0.15.13 | 11,434,486 | `cc411dfebe5eebe55ce041c6ae080eb7668955e866daa2fbb16692a784f1c4ca` |
| v8-sandbox-archive | 150.4.0 | 29,366,352 | `a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583` |
| v8-sandbox-bindings | 150.4.0 | 39,884 | `7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506` |
| v8-pair-checksum-text | 150.4.0 | 262 | `6774b42c9424c098c72a805c08d4e94be17c591cf02b1dc2633060255a8a61be` |

UV 版本 0.11.3 来自本候选 native workflow 的明确 pin；其官方 release ID 为 304428942。Ruff 0.15.13 来自 `scripts/uv.lock`，GNU x86_64 wheel URL 和 digest 保留原锁记录；`scripts/pyproject.toml` 与 lock 均要求 Python >=3.10。项目为 virtual project，当前锁定依赖只有 Ruff。

V8 crate 为 `=150.4.0`，Cargo.lock crate checksum 为 `42a978ff11f15b24e5c05a7123cf2b68f41e763546699781a924ef4e2cf43a49`。归档使用 `ptrcomp_sandbox_release` / `x86_64-unknown-linux-gnu`，来源为 openai/codex 的 `rusty-v8-v150.4.0` release 361445880（原 API 标记 prerelease）。三件官方 asset digest 与固定 repo README 的既有核验记录逐项一致。没有选择 denoland 的非 sandbox 归档，也没有把未成功的独立源码构建当成可用供应物。

原 repo 中 `third_party/v8/rusty_v8_150_4_0.sha256` 只列 Windows MSVC 两件；它不能替代本 GNU sandbox 配对的 release checksum。

## 外置恢复与维护入口

拟用 native agent 提出的 `/data/hepta-utility-36fa-runtime-materials-86dd-v1` 专属目录，所有工具、wheel、虚拟环境及缓存均在外部。只创建新目标，已有文件只能在完整身份匹配后复用；不覆盖旧文件、不修复历史缺失路径、不 sudo、不做全机扫描。

下载前、下载后及解包前分别核固定源码输入、HTTP/长度/摘要和内容结构。UV checksum 文本自身也须先匹配官方 API digest，再核它指向的 archive 名称与 digest。V8 checksum 文本必须覆盖且仅覆盖这次 archive/bindings。保留代理、CA 和 TLS 校验，记录真实结果；材料下载和准备成功以前不进入维护。

原 `just fmt` 调用 repo 的 `scripts/format.py`。scripts 分支保留：

```text
uv run --frozen --project scripts ruff format <原选择的路径>
```

不能替换为裸 ruff、跳过文件或借恢复更改原测试/维护 argv、预算、断言。原 c0f wrapper 的实际 fix/fmt argv 与 workflow 中的另一组 argv/budget 在方案里分别列出，不能混用。下一次维护精确参数仍由 Root 已审 driver/input 决定。

预先完成 Ruff 的外置虚拟环境/cache 同步，再冻结 `UV_OFFLINE=true`、`UV_PROJECT_ENVIRONMENT`、`UV_CACHE_DIR`、`RUFF_CACHE_DIR`，保留原 Cargo/Rust/目标/作业数等配置。官方 UV 0.11.3 源码实际包含 `sync --frozen --offline --check`、`--python`、`--find-links`；因此可以在准备阶段检查环境是否已经同步，随后仍运行原维护命令。方案里的 offline wheelhouse bootstrap 尚未执行；其真实成功必须被观察并保留，不能靠静态存在这些 CLI 选项推定成功。当前 Python 版本也须实际记录并满足 >=3.10，不隐式安装新 Python。

原 V8 resolver 在两个 RUSTY_V8_* override 同时存在时直接返回，不自行验证这些覆盖文件。因此恢复 admission 必须先独立核两件完整内容，再显式冻结新路径。旧 bindings 仅在当前完整 hash 等于固定值后可按原字节复制复用；文件大小相等不足以采用。

## 来源与未完成事项

官方 UV 与 V8 release API 的完整原响应各已离机保全。通过 GitHub connector 直接读取两个 checksum browser_download_url 时均得到 404，原响应也被保存；release API 同时列出了两资产和 digest。这是该读取方式的实际结果，不证明发布资产不存在，实际 bounded 下载和文本校验仍待 native 执行。

原工具源码和运行证据的索引在 [SOURCE_AND_RUNTIME_EVIDENCE.json](SOURCE_AND_RUNTIME_EVIDENCE.json)。当前全 Cargo offline cache 闭合、其他未探查路径、旧 binding 当前哈希、解包后的 UV 可执行文件身份、真实 bootstrap/check 返回值和后续 fix/fmt 结果仍需各自实际证据。恢复环境不会提前提供任何 source/caller/native 或真实 A/B/C 资格通过结论。
