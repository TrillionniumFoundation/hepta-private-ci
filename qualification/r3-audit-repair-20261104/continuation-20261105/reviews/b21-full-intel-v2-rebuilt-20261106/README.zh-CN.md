# B21 原完整 Intel Bazel 上下文：重新构建的诊断候选

## 结论与身份

此包是**新的、仅修改一个诊断 workflow 的候选**。旧 scratch 中的 `863a36de822ea127bf9aa8a0e5d131626952cfe2` 全文未恢复；旧版没有完成独立接受、冻结或发布。`RECOVERY_ORIGIN.json` 保留这一事实。本包不声称与旧版字节相等。

最终 workflow 共 965 行，其中 749 行是同一 collector 的机械内嵌。审查分成原 wrapper/任务语义与 collector 隐私/收件逻辑两个独立组件进行；最小可运行阶段必须同时具备全部实际 attempt 收件和 fail-closed 上传门，不能先发布缺少其中一环的片段。源码审查资格与以后的 native 运行资格分别记录。

此候选完成源码、完整 Git 树和合成证据场景验证。源码已经用 `create_tree(content)` 物化为无引用的 Git blob，并按预期 SHA 全文 GET 逐字节核对。**没有修改 ref、创建或更新 PR，也没有运行 Bazel、Rust 测试或任何产品原生验证。** 独立审查、根审查及后续实际发布分别由独立回执记录；本文不能替代这些步骤。

| 对象 | 身份 |
|---|---|
| 固定原产品 commit / tree | `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed` / `3982ba56dc5a3f1da0c1de7ea57992f88125c359` |
| 直接 parent commit / tree | `cc65856cc0b20d03db506c19495d53d61162102d` / `eaded1870d080eaa55efae6208354729140e784c` |
| 唯一修改路径 | `.github/workflows/b21-intel-original-pty.yml` |
| 新 workflow 实际 blob | `fb5881fa310d3548cd604d2827fe9c29aa1b3873`，50,740 B |
| 内嵌 collector 实际 blob | `00dc37697adde6154a347963ab19e8a6edebac07`，34,905 B |
| 新完整候选 tree（本地重算，尚非 source 发布） | `46fca3e684217066c260dc10d0dc319a33e0a93c` |
| 不变的原产品叶 | 10,582；候选共 10,583 叶，逐一重建 1,571 个树节点 |
| 源码实际回执 | `candidate-postimages.actual.json`、`source-registration/` 原始 create/GET |

## 为什么取得完整上下文

此前单独 PTY 目标的原 Intel 运行能证明那一次目标执行的结果。它不能验证原全仓 Bazel 并行负载，也不能说明历史约 2.023 秒 drain 失败的原因。因此此候选机械恢复固定 `bazel.yml` 的完整 Intel leg，取得此前缺失的全目标上下文。

**B21 保持 OPEN，历史失败因果保持 UNKNOWN。** 新 full-context 运行即使通过，也不能单凭一次通过给旧失败编造根因。这里没有产品路径修复。原 PTY 的 2 秒、5 秒控制、drain/child 退出/FD 断言及所有用例没有变化；成功时 libtest 可能仍捕获每会话 counters，不能假定通过日志必然展示这些 counters。

## 机械保留的原任务语义

`build_candidate.py` 从固定原 `.github/workflows/bazel.yml` 读取 test job，逐字提取三组 Bash 参数数组，并原样复制 prepare、cache-save、clean-worktree 的 YAML 数据。

- 机器仍为 `macos-15-intel` / `x86_64-apple-darwin`，environment 为 `bazel`，外层仍为 120 分钟。
- job id 使用原 `test`，因此原 `bazel-${{ github.job }}` cache scope 为 `bazel-test`。prepare action、cache 命中/保存策略和 clean-worktree action 均保留。
- 原 targets 完整保留：`//...`、`-//third_party/v8:all`、`-//codex-rs/v8-poc:v8-poc-unit-tests`。
- 原 wrapper、`--print-failed-action-summary`、`--print-failed-test-logs`、`--test_tag_filters=-argument-comment-lint`、`--test_verbose_timeout_warnings` 均保留。
- 没有设置 `--flaky_test_attempts`。固定 Bazel 9.3.0 的默认策略是普通测试一次、显式 flaky 规则最多三次；原 `defs.bzl` 对分片测试的 flaky 标记原样保留。收件必须保留首次失败和其后的所有实际 attempts。
- 原 `.bazelrc` 的 macOS jobs=128、loading_phase_threads=4、local_test_jobs=2 和 TestRunner 策略没有变。原 wrapper 在有 key 与无 key 情况下的配置选择也没有改；实际执行策略仍须以后用真实 BEP/compact 判断。
- wrapper 只调用一次；没有单 case 重跑、过滤、`nocapture`、`runs_per_test`、测试线程或测试超时覆写。

新增 Bazel 参数严格只有三项：

| 参数 | 作用与限制 |
|---|---|
| `--nocache_test_results` | 要求实际测试执行；不改变原编译缓存、远程信任或重试策略。若真实 BEP 仍报告 cached test result，证据完整性失败。 |
| `--build_event_json_file=...` | 增加本地 JSONL 证据。按固定实现，它是一个额外观察输出，可能有输出/等待开销；不声称零开销，也不改变测试预算。 |
| `--nobuild_event_json_file_path_conversion` | 固定 9.3.0 实现仅将 JSON transport 的 uploader 换成本地 file URI converter；BES uploader 在后续独立创建，executor/cache/retry 参数不变。 |

另有一处明确的身份替换：原 `--build_metadata=COMMIT_SHA=${GITHUB_SHA}` 改为实际 checkout 的 source HEAD `${TESTED_SHA}`。PR event merge SHA 单独记录，绝不把它说成实际 checkout。

依据：[固定原 bazel.yml](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed/.github/workflows/bazel.yml)、[原 wrapper](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed/.github/scripts/run-bazel-ci.sh)、[Bazel 9.3.0 ExecutionOptions](https://github.com/bazelbuild/bazel/blob/9.3.0/src/main/java/com/google/devtools/build/lib/exec/ExecutionOptions.java)、[BuildEventServiceModule](https://github.com/bazelbuild/bazel/blob/9.3.0/src/main/java/com/google/devtools/build/lib/buildeventservice/BuildEventServiceModule.java)。原文和完整 GET 均在 `source/`、`source-GET/`、`primary/`。

## 源码与原平台门

workflow 仍只由当前诊断路径的普通 `pull_request` 事件触发，保留同仓库和固定分支 guard，不新增 dispatch、schedule、rerun 或 cancel。`cancel-in-progress=false`，权限只有 contents:read。

运行时要求 HEAD 等于 PR source SHA，所有直接 parent 恰为 cc；cc 的 parent 恰为 main67，两个原树 SHA 精确相等。比较 main67..HEAD 及 parent..HEAD 都只能得到该 workflow 路径。checkout depth=3，祖父使用 `HEAD~2`。运行前 tracked、staged、untracked 状态必须干净。

全 source HEAD 通过 `git archive` 留存，关闭外部 global attributes，拒绝额外 info/attributes，并逐个核对 10,583 个 archive member 的 Git blob 字节与 mode。固定仓库的两个 `.gitattributes` 原文没有 export-ignore/export-subst。最后保留 source HEAD/tree 与 worktree 状态，再运行 collector。

原平台由 `uname`、`sw_vers`、CPU brand 和 `RUNNER_ARCH` 留存/验证，要求 Darwin、x86_64、X64。先记录实际 zstd 路径/版本，避免测试完成后才发现 decoder 不存在。这些是证据前置检查，不是新增产品测试。

## 凭据与不透明载荷

固定 Bazel 9.3.0 的 command-line BEP 会含 wrapper 注入的原始 `remote_header`。原始 BEP 放在独立权限 0700 的 private 目录，处于两个上传根之外，**从不上传，也不记录其 secret-derived digest**。

持久 JSONL 明确命名为 **credential-sanitized / opaque-payload-omitted derived BEP**，不得称为原字节 BEP 或完整原 build-tool 日志。逐个 JSON key/string 替换实际 `BUILDBUDDY_API_KEY`；结构化、分离参数、字典 key，以及任意包含五类 header option 的非结构化 scalar 均覆盖。对带空格的 `Authorization=Bearer ...`，整 scalar 移除，不能用空白猜值边界。URI user-info 和所有 query 值保守移除；编码凭据出现在 URI path/fragment 时拒绝派生件。

`File.contents` 是 base64 不透明字节载荷。本 collector 只将它替换为明确的 omission marker，并移除该载荷原 digest；receipt 仅保存安全字段位置、计数和输入字节数。任何实际 attempt 没有可取得的原日志/XML URI，都不能因内嵌内容被“看过”而判完整。

receipt 不保留真实凭据、原载荷、原凭据字符串或其指纹。解析/净化失败不发布部分 JSONL；公开输出仅有固定错误种类。

依据：[CommandLineEvent](https://github.com/bazelbuild/bazel/blob/9.3.0/src/main/java/com/google/devtools/build/lib/runtime/CommandLineEvent.java)、[RemoteOptions](https://github.com/bazelbuild/bazel/blob/9.3.0/src/main/java/com/google/devtools/build/lib/remote/options/RemoteOptions.java)、[BEP proto](https://github.com/bazelbuild/bazel/blob/9.3.0/src/main/java/com/google/devtools/build/lib/buildeventstream/proto/build_event_stream.proto)。此处只据固定 9.3.0，不能用其他版本较新的自动 redaction 推断当前版本安全。

## 实际尝试、原件与缺失项

collector 只接受当前 checkout 的 `bazel-testlogs` 根（允许这一根 convenience symlink），其下不跟随其他链接。完整保留所有实际产生的 `test.log`、`test.xml` 和任意 run/shard 深度下的 `test_attempts/*.log/*.xml`。拷贝时检查文件身份/大小/mtime 稳定性，原字节、大小、SHA256 对账。含已配置 key 的原件不复制、不输出其 digest，路径有凭据也不回显。

每个实际 `TestResult` 以 label/configuration/run/shard/attempt 绑定，并核对连续 attempt 序号、重复、日志/XML URI、可用 digest/length、TestSummary.totalRunCount，以及 summary 的 passed/failed 日志。保留首个 FAILED 与后续 PASSED；不把后续通过覆盖初次失败。事件 child ID、finished、最终 lastMessage 和原 Bazel exit 也核对。

只有在授权本地根内、无认证/查询/片段、完整存在且字节匹配的 `file://` 可保留。bytestream、未知 scheme、越界/非本地主机、缺失、截断、摘要不符和不可本地取得的载荷都标 UNAVAILABLE，完整性失败；不下载远程 URI、不猜路径。排除原测试的 outputs/runfiles 和其他非 log/XML 文件，不声称它们被本收件器完整归档。

完整性结论只表示**所有实际产生/引用的 test-attempt log/XML 已对账**，不表示未执行或不兼容目标已执行，不是物理 case 全量资格。预期 PTY target 必须实际出现在 BEP；无 test result 或原 compact 缺失也不能通过。

依据：[StandaloneTestStrategy](https://github.com/bazelbuild/bazel/blob/9.3.0/src/main/java/com/google/devtools/build/lib/exec/StandaloneTestStrategy.java) 的失败尝试重命名，以及包内固定 proto 的 TestResultId / TestSummary 定义。

## 上传门与退出码

两上传根只有 public evidence 和原 `bazel-execution-logs`。collector 扫描全部公开路径/普通字节，并只读解压自身 source archive 和每个 `.zst`。已配置 key 的四层 percent 编码跨块也检查；旧缺陷的跨块反例已回归。

zstd 使用实际现成 CLI 的 `-q -d -c --no-pass-through -- <path>`，记录实际路径/版本，不安装 decoder、不改原 compact。每文件总解码限 60 秒；非阻塞读取后必须取得子进程 exit0。不存在 decoder、损坏/截断/无效帧、扫描失败或超时都令 `safe-for-upload=false`。只回收本 collector 自己创建的 Popen；不会触碰测试进程或其他运行。此时间界限属于证据检查，原测试 deadline 没有变化。

这个门检验本任务明确配置的 key 及上述 BEP 净化范围，不声称识别任意未知 secret。原压缩 bytes 不被改写，解压只用于隐私检查，不能据此推断 TestRunner 资格或编译缓存命中。

`GITHUB_OUTPUT` 先写 false，只有完整末端扫描后才能写 true。artifact action 的 `always()` 仍必须同时满足 safe-for-upload=true。不依赖 GitHub console mask 保护 artifact。隐私门失败时 console 只给固定安全 error code，无法上传的原件保持缺失，不能假装已取得。

原 wrapper 和外层 `tee` 的 PIPESTATUS 分开保存；测试步骤最终返回原 Bazel exit。collector exit 独立保存，证据完整也不能把非零原 exit 变绿。两个 Bash stub（原 exit0、7）已证明此行为；它们完全是本地假 wrapper，没有调用 Bazel。

## 可复核文件与复用接口

```sh
python3 -B verify_candidate.py .
```

需要 Python、PyYAML 和既有 zstd；verifier 只做源码/树/语法/合成数据验证。它验证 15 个固定仓库依赖的完整 GET、14 个固定 Bazel primary 原文、完整三棵树、原数组/动作数据、内嵌 collector 字节、Bash 语法、36 个必要合成场景以及两个假 wrapper exit。`static-final.stdout.json`、`fixtures-final.stdout.json` 是结果原件，stderr 均空。包内报告没有原生执行结论。

36 个场景由原先 31 个必要反例和独立审查发现后的 5 个回归组成。独立审查的旧快照/原反例和最终接受回执单独保留，不覆盖历史。

供其他独立目标复用的接口固定为：

```sh
python3 - RAW_BEP_PATH PUBLIC_EVIDENCE_DIR EXPECTED_TARGET ORIGINAL_EXECUTION_LOG_DIR
```

运行目录必须是实际 checkout。public 先有 `original-bazel-exit-code.txt`、`console-copy-exit-code.txt` 和 `console.log`；两个 exit 文件是十进制加换行。输出为 `attempt-retention-manifest.json`、`bep-redaction-receipt.json`、派生 JSONL 和 `artifact-privacy-gate.json`。复用只能使用同一已接受 collector 原字节，目标由参数传入；没有写死 B21 状态。源身份最后回执必须在 collector 前生成，之后只准写固定安全的 numeric exit / GitHub output 元数据。
