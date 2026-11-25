# 2026-11-24：原依赖门失败、输入准备与保留边界

## 结论

本轮没有生成可用的依赖锁候选，没有完成 Bazel 双锁更新，也没有取得正确完整依赖图的 `cargo-deny` 通过结果。原 CI 日志保留范围内确认了七项 RustSec 错误，涉及五个包；只更新 `cookie` 不足以关闭安全门。原安全策略、advisory 抑制名单和验收范围均未改动。

本页和 [证据清单](dependency-gate-20261124/MANIFEST.json) 是证据增量。它们不授予真人授权、跨用户采用、模型训练、PoUW、付款或完整工程门资格。

## 源、日志与锁身份

桌面原生命令执行于 `9917930245b184cba7ded078221fe90a2335eab7`，tree 为 `7c7bd46198c1dbff84f6e0781ec6ff08970718ca`。独立依赖工作树只物化完整 Cargo workspace、Bazel 本地输入和相关源目录；没有用其他分支的整份锁替换本图。

关联 CI 为 [run 45401112182 / job 138473844454](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45401112182/job/138473844454)。其 run metadata 关联 PR HEAD 为 `9917930245b184cba7ded078221fe90a2335eab7`。原 workflow 的 checkout 没有显式指定源 ref，保留尾片也不包含 checkout 头段，因此 **CI 实际 checked-out SHA/tree 尚未核实**；本包明确保留为未知。相同的包版本不足以证明整棵树相同。

原日志 HTTP 响应为 `206`，保留范围 `bytes 16429577-20623880/20623881`：整份日志标称 20,623,881 字节，本包只保留末尾 4,194,304 字节。原始尾片 SHA-256 为 `eab3a16aab7c6ab2a4b642d6cf63aeedcc4d07bfb35be5ea49e7d3246d18f751`。压缩没有改变解压后的原字节；仅派生诊断移除了 ANSI 序列。本页不将局部尾片称为完整日志。

原生命令结束后和本证据父提交 `442f6fc48dbf80ad6f1dbfa5a1f9ba65e14a64a6` 均核对了下列身份：

| 文件 | 字节 | SHA-256 | 相对原源 |
| --- | ---: | --- | --- |
| `codex-rs/Cargo.lock` | 421,418 | `48b55c7ff5c23516fd0aeedca7c10a6e7902aeb5dc49fa4cef80971e1ae57d3f` | 未变 |
| `MODULE.bazel.lock` | 1,786,971 | `2be801e80e41fc993798e133a168c8202c73ed8c8e4e06f419779e317f7c0679` | 未变 |
| `codex-rs/Cargo.toml` | 23,138 | `6ac9ba7db88aefd65f20d3e917913e1723b4fb93444ffcfce278b8ae5a38e144` | 未变 |

## 七项真实诊断

[精简诊断](dependency-gate-20261124/ADVISORY_DIAGNOSTIC.json) 保留原错误标题、时间戳、advisory ID 和 Solution 行。完整保留范围中的反向依赖树可从原始日志尾片读取；精简 JSON 不声称枚举了所有反向依赖。

| 包 / 锁版本 | 原 advisory | 原日志类别与问题 | 原日志给出的 Solution |
| --- | --- | --- | --- |
| `chrono 0.4.45` | `RUSTSEC-2026-0543` | `unmaintained`；停止维护 | `No safe upgrade is available!` |
| `cookie 0.18.2` | `RUSTSEC-2026-0594` | `vulnerability`；fork 后私有 cookie nonce 可能重复 | `>=0.18.3` |
| `libsqlite3-sys 0.37.0` | `RUSTSEC-2026-0459` | `vulnerability`；所含 SQLite 的 `CVE-2026-119375` | `>=0.39.0` |
| `rmcp 3.1.3` | `RUSTSEC-2026-0457` | `vulnerability`；OAuth SSRF 检查主机字符串而非解析后的地址 | `>=3.7.0` |
| `rmcp 3.1.3` | `RUSTSEC-2026-0461` | `vulnerability`；HTTP tool schema cache 无界增长 | `>=3.6.0` |
| `rmcp 3.1.3` | `RUSTSEC-2026-0462` | `vulnerability`；HTTP client response body 无界缓存 | `>=3.9.0` |
| `url 2.5.8` | `RUSTSEC-2026-0592` | `vulnerability`；嵌套 `blob:` URL 的 origin 处理栈溢出 | `>=2.5.9` |

原尾片最终分类是 `advisories FAILED, bans ok, licenses ok, sources ok`。这七项是 advisory 错误；没有观察到独立的 `oauth2` advisory，OAuth SSRF 对应的包是 `rmcp`。`chrono` 的“没有安全升级”是原维护状态 advisory 的结论，不是本轮推测或新设定的禁止名单。

当前 workspace 将 `libsqlite3-sys` 约束为 `0.37`、将 `rmcp` 固定为 `=3.1.3`，因此这两项不能只靠定向改锁达到原日志修复下限。`chrono = "0.4.43"` 仍解析至受维护状态诊断影响的版本；其处理需要实际源/API 迁移与回归。`url = "2"` 和 reqwest 的 cookies 特性也属于本图。后续修复必须在本分支的真实 manifest 图生成两份锁并重跑原门；其他候选的版本、vendor 修改或通过结果不自动适用于这里。

## 原生命令及失败边界

使用 Rust/Cargo 1.96.0、cargo-deny 0.19.0，更新命令的工作目录是原 workspace 的 `codex-rs`。未关闭任何安全检查。表中每个阶段的精确 argv、cwd、开始/结束时间、exit code、stdout/stderr 字节与 SHA 均保留在 [原件包](dependency-gate-20261124/NATIVE_SECURITY_INPUTS_ORIGINALS.tar.gz) 对应 JSON 内；持久 job ID 的映射见清单。

| 原命令 / 阶段 | 结果 | 已记录时间（秒） | 原件中的实际边界 |
| --- | --- | ---: | --- |
| `cargo deny --manifest-path codex-rs/Cargo.toml --all-features check` | exit 124 | 900.010663509 | 原完整图门超时，stdout/stderr 均为空，未取得诊断或通过结果 |
| `cargo update -p cookie --precise 0.18.3`，默认 Git transport | exit 124 | 900.016424623 | Git 源 SSL reset，终止时仍未完成解算 |
| 同一 update，原生 Git CLI transport | exit 101 | 238.856755839 | 精确 Git 源推进后，`icu_segmenter_data` 官方 index 下载低速超时 |
| 同一 update，关闭 HTTP multiplexing | exit 101 | 44.484797039 | `unicode-segmentation` 官方 index 下载超时 |
| 同一 update，offline | exit 101 | 0.729883577 | 缺 `icu_segmenter_data` index；offline 不代表安全数据库新鲜度通过 |
| `cargo info icu_segmenter_data@2.3.0 --registry crates-io` | exit 0 | 48.337755491 | 只补齐这条公开依赖输入 |
| 同一 update，补齐 ICU 后 offline | exit 101 | 0.716865261 | 缺 `error-code` index；仍未生成锁 |
| 600 秒有界公开缓存准备 | job exit 124；81 条 native 子命令 exit 0 | 子命令合计 596.436201077 | 达到既定时间边界；不自动开始第二轮 |

Git 输入仍使用锁中精确 revision。原生导入公开 `rules_rust` 对象与随后 `git fsck --full` 的命令、成功输出和耗时也在原件包；没有手改依赖锁、复制凭据或全局 Git/Cargo 配置。下载本身不是编译或安全门通过。

缓存准备前清单有 232 条版本记录、210 个不同名称；最终按 crates.io 小写名称规则检查，仍缺 **151 条记录、138 个名称**。初始清单原字节保留，最终清单明确记录了包括 `Inflector` 在内的路径大小写归一化。81 条成功命令只表示相应 `cargo info` 成功，不表示整个 workspace 已完成 `cargo metadata`、可离线编译或可生成锁。

600 秒阶段记录的用户 CPU 合计 6.458917 秒、系统 CPU 合计 3.285781 秒、最大已观察 RSS 30,868 KiB。资源统计范围是被等待的原生命令子进程，未覆盖完整进程树和编排开销。**这些是工程依赖获取与诊断成本，不能写成模型训练成本、完整训练加速比或单位采用收益。**

原抑制策略保护检查在同一原源上通过：`python3 -m unittest -v scripts.tests.test_hepta_rustsec_guard` 为 4 项通过；`python3 scripts/check_hepta_rustsec_advisories.py --repo-root .` 返回 `RustSec policy guard: no tracked advisory suppressions`。它们只证明原策略守卫结果，不替代失败的 `cargo-deny`。

## 本地 caller 原件与本次安全源的关系

另保留 [caller 原始 JSON 的 gzip](dependency-gate-20261124/CALLER_PROOF.json.gz) 和 [原执行说明](dependency-gate-20261124/CALLER_VALIDATION.json)。原命令 `python3 -B scripts/verify_hepta_callers.py verify` exit 0，输出 `PASS_HEPTA_CALLER_CLOSED_SET`：扫描 6,180 个 Rust 文件、182 个边界、166 个受保护文件，`authorityGranted=false`。

这是本地安全源准备阶段、随后提交 `276aca492803e9cb9a7c84a19fdec4e92daeb7cd` 的 caller 验证记录。原 JSON 没有嵌入 commit SHA，本包没有补写原件或伪造对最终提交的执行绑定。它不证明真实 native CLI、Bazel、完整工作空间测试或真实跨用户授权已运行。该阶段 native 拒绝路径与 CI 接线已有源修改；实际二进制验证仍需原执行通道完成。

## 证据复核

本目录使用二进制 gzip/tar 保存原件，没有把压缩 payload 放入 base64 JSON。核心压缩件如下；其余小文件的字节数与哈希见 `MANIFEST.json`。

| 压缩件 | 压缩字节 | 压缩件 SHA-256 |
| --- | ---: | --- |
| `NATIVE_SECURITY_INPUTS_ORIGINALS.tar.gz` | 68,281 | `0bb05acbcbf6a0a49937e2cb7758eb2b3274e3df6e073765b7542e12233ca68e` |
| `cargo-deny-138473844454-tail.log.gz` | 362,191 | `9394f0c76ba79880cdad96db9ed34464a1aab0afe384e5af63aef94ee3e739f0` |
| `CALLER_PROOF.json.gz` | 8,318 | `47358cd9394c4a9d504f01006a194cbab409b52f4d3d28c0d06a2462ca0e29f2` |

native 包含 280 个原始文件及一个 `ORIGINALS_MANIFEST.json`。所有 280 个文件的字节数与 SHA-256 均已逐项核对。caller 解压后为 84,890 字节，SHA-256 为 `ea50b804a14d25c4f98fea33a51cd006bab43c8886823e99a47aca036aa6cac1`。

可在仓库根运行下列只读复核，不需要下载依赖或运行模型：

```sh
python3 - <<'PY'
from pathlib import Path
import gzip, hashlib, json, tarfile
p = Path('qualification/paired-consumer-integrated-20261123/dependency-gate-20261124')
m = json.loads((p / 'MANIFEST.json').read_text())
for f in m['files']:
    b = (p / f['path']).read_bytes()
    assert len(b) == f['bytes'] and hashlib.sha256(b).hexdigest() == f['sha256']
with tarfile.open(p / 'NATIVE_SECURITY_INPUTS_ORIGINALS.tar.gz') as t:
    original = json.load(t.extractfile('ORIGINALS_MANIFEST.json'))
    for f in original['files']:
        b = t.extractfile(f['path']).read()
        assert len(b) == f['bytes'] and hashlib.sha256(b).hexdigest() == f['sha256']
b = gzip.decompress((p / 'cargo-deny-138473844454-tail.log.gz').read_bytes())
assert len(b) == m['ci']['retained_raw_bytes']
assert hashlib.sha256(b).hexdigest() == m['ci']['retained_raw_sha256']
b = gzip.decompress((p / 'CALLER_PROOF.json.gz').read_bytes())
assert len(b) == m['caller_receipt']['raw_bytes']
assert hashlib.sha256(b).hexdigest() == m['caller_receipt']['raw_sha256']
print('Retained bytes and hashes verified; no engineering gate is implied.')
PY
```

包内未收录凭据或配置文件。保留的原件、CI 尾片和 caller 原件已检查常见 GitHub token、AWS key、私钥、未遮蔽 Authorization、签名 URL 及 URL 用户密码模式，未发现匹配；模式扫描不是对一切秘密编码的形式化证明。

辅助归档进程的工具回执曾超时，分页恢复遇到 `durable inventory source entry bound exceeded`，因此其 job ID/终态保持未知。本包仅依据随后独立读回并逐字节校验的文件结果，不推断该辅助进程成功或重开不确定执行。

原 Q24 cold/Adopt/FinalUse 没有重新启动，没有重置 1,800 秒原预算。[此前归档原件](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/93f7f21af1b7a4f676e18067a2b7be4d1e66871f/evidence/e6-terminal-originals-20261121-ac5459/bf6d-build-readiness-20261124) 记录累计 1,798.003951198 秒、原 target/donor ELF 缺失的状态，不能由本页工程缓存准备覆盖。完整依赖安全门、原生命周期与真实跨用户采用仍分别保留原验收标准。
