# 后继共同候选 R 的原生验证

R 的 74 项 Python 控制、5 项 AWS Auth 测试、33 项原生 UI 包测试在同一次 003 尝试中全部实际通过，零跳过。Bazel `--lockfile_mode=error` 通过；cargo-deny 仍失败于 **RUSTSEC-2026-0451**。整体门禁不通过，不能据此合并或宣称科学、生产资格。

## 精确源码身份

| 身份 | Commit | Tree |
| --- | --- | --- |
| 原冻结 C | b839558b26c2e5b667055ca4af4ad749ae41c043 | e411d25b47c166f35783a27054adb6a3f6682594 |
| 原证据 E | 6c63d1aab2a4914c3559b368b1ade5a4748e8df7 | 0290f23d80cbbca7a7fd9be546dbb305a05c70f9 |
| 共同受测 R | cfe941b4762a773679a552068d1560ae17a3f226 | e6fc9a1cb7c2441c1811d08356f7e31b2e886177 |

R 的父提交是 P `54d73e897e088369b37db1575af146d228b5db25`；P 的父提交是 C。R cherry-pick 了 U `0e6fbff34b4f9ad9555de057d8807666f2668e84`。C..R 恰好四个文件、262 行新增/42 行删除：P 的两个锁文件，以及 U 的 `room.rs` 与 `room_ime_commit_tests.rs`。逐文件 mode/blob 与各原冻结提交相等，原 P/U 工作树未修改。`just fmt` 和对 C..R 的提交格式检查通过。

本证据分支从 R 建立，仅追加观察文件和原始证据包的精确 SHA256 大文件许可。受测运行源码仍是 R；本报告不预填证据提交自身未来的 head。发布 head 和远程回读由独立交付收据记录，本文只观察本地 Git 身份。

## 共同门禁与原始记录

| 门禁 | 003 实际结果 | 进程 wall 秒 |
| --- | --- | ---: |
| common-python-controls | 74/74, 0 skipped | 14.360125 |
| aws-auth-tests | 5/5, 0 skipped | 0.464488 |
| native-ui-package | 33/33, 0 skipped | 3.080182 |
| bazel-lock-error-check | 通过 | 6.270007 |
| cargo-deny | 失败：RUSTSEC-2026-0451 | 3.123767 |
| complete-archive-integrity | 通过 | 1.515796 |

`VALIDATION.json` 保存每个命令、前后 head/tree/index/status、完整受控源码字节校验、stdout/stderr 的长度和 SHA256、进程退出值及成本。原日志与所有尝试在 `raw-evidence.tar.gz` 中；三个测试组的原 stderr 均包含实际测试名称与真实分母。这里的 112 仅是这三个工程测试组之和，不是学习样本数、科学收益或全项目覆盖率。

## 运行输入与两种源码字节身份

Python 实际为 3.12.3，torch 2.9.1+cpu、numpy 1.26.4、Pillow 12.0.0；四个线程变量均为 1，六个模块和原 C Python profile 逐字节保留。整体 R profile 另列 Rust 1.96.0、实际工具二进制 SHA、目标目录及 200% CPU/6 GiB/2400 秒外层预算。

UI 测试使用两份仓库 manifest 指定的 Noto 字体（manifest SHA `fb9e49a7f14b742ac7e390ceee9be115ad6e04a5f852eec67fb0a126870070a3`）。安装前 R 严格 clean；运行时恰好两个已声明、已按 URL/bytes/SHA 固定的 untracked 字体；测试后只按相同 hash 删除这两文件，R 再次严格 clean。测试期间不能称 checkout 全空状态。字体原件保留在 profile 指定的独立 runtime-assets 缓存，未混入 Git tracked 源码 archive。

实际 Makepad checkout 是 `/home/qian-qi/.cargo/git/checkouts/makepad-69d78fae78fc8901/337566c`，Git HEAD `337566c8b25d47f7e4fff6a202157b65bf183330`，tree `c6e18be7754f9634492ec5251bac3e8b4f7e09b7`。实际 Cargo metadata 将 draw/platform/widgets 三包解析到该目录。前后 status 都保留 `?? .cargo-ok`，没有删除 marker。

SDK 自身 attributes 将 29 个 CSV/PS1/CMD/BAT 文件按 `eol=crlf` 物化；它们的物理字节和原 LF Git blob 不同。`SDK_CHECKOUT_NORMALIZATION.json` 逐项保存原 blob、原/实际 SHA256 与长度、精确可逆 LF→CRLF 关系及 attributes，profile 只接受这些事先冻结的物理 pins。其余受控 SDK 文件原始字节相等，全部 6008 个 Rust 源文件精确等于原 Git blob；完整实际 SDK 输入在 UI 前后相同。没有为了消除原失败而修改 SDK 或 Git 配置。仓库的 WASM IME patch 有独立 SHA pin，但未应用到本次原生 SDK；原生 FullTextState 路径通过不代表浏览器 JS→WASM 传输通过。

## 尝试历史与成本

001 在测试前的完整 SDK raw-byte guard 处失败，未执行任何测试。它正确发现上述 29 处物化差异，原始失败保留。002 用修订后的物理字节 profile 重跑并通过 74+5，随后用于身份记录的 `cargo metadata --offline --locked` 因缓存缺少 ctor 0.2.9 而失败；UI 尚未执行，002 不计共同通过。003 仅允许该 metadata 按冻结锁文件正常获取缺件，保持 `--locked`，所有三组测试从头重跑，不拼接 002 的成功结果。

| 尝试 | Wall 秒 | 进程及后代 CPU 秒 | 解释 |
| --- | ---: | ---: | --- |
| 001 | 1.960725 | 0.913247 | SDK 原字节 guard 失败，0 测试 |
| 002 | 25.052535 | 19.060857 | 79 项部分通过，metadata 缓存缺件失败 |
| 003 | 46.187201 | 43.413116 | 同版 112 项通过，cargo-deny 保留失败 |

三次活跃验证 wall 合计 73.200462 秒，CPU 合计 63.387219 秒。这不是端到端历时；各步骤耗时已包含在对应 attempt 总成本中，不能再相加。另有源码组装、只读 SDK 差异诊断、工具准备、归档传输与发布开销；本表不将其伪装成已量化训练成本。本轮没有重跑 PRED 确认或新的学习任务。

## 完整 tracked 源码归档

`git archive --format=tar --prefix=source/ cfe941b4762a773679a552068d1560ae17a3f226` 产生 `/home/qian-qi/work/cell-integration-20261108-08b6/followup-validation-003/source.tar`，162334720 bytes，SHA256 `f725f8c46c27b07fd27a10b8cb00b8b79f45f9641e18a93fcf694ad3f2be5c7b`。全部 11,387 tracked 文件的集合、原始字节、模式和 symlink 由原 `hepta_source_archive.py` 实际验证；完整逐文件 inventory 位于包内 `followup-validation-003/archive-integrity.json`。162 MB 级源码 tar 留在上述 native 路径，不重复放入本证据 Git 包。archive 中的源码就是 R 的 tracked Git 字节；字体等运行输入另行 pin。此检查只有 integrity 意义，不认证测试执行、远程 CI 或发布。

## 尚未证明

`joint_learning_configuration` 仍为 null，scientific/production qualification 均为 false。cargo-deny 的 vodozemac 漏洞未修复；全套托管 CI、Firefox/WASM/Playwright、全 Rust workspace、真实后继任务中的学习/采用净收益均未在本轮重新证明。原 PRED HOLD 和其他负面结论不因工程门禁通过而改变。

复现时按 archive binding 与 profile 校验 R、原 SDK 与 29 个物理字节 pins，使用原字体准备脚本从保留 cache 离线安装；运行包内 003 worker 或按各 step 的 argv/cwd/env 顺序执行。worker 中固定的 native 路径是本次原件，不是可任意重定位却仍宣称相同的模板。原始 001/002 失败也应保留。
