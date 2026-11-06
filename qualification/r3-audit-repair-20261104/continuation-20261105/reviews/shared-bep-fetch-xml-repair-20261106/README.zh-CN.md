# B21 / B23 共享 BEP 收件修复候选

## 结论与身份

本候选修复两项已经由真实作业暴露的证据收集问题：允许 Bazel 的同一 Fetch ID 多次出现，同时逐条保留事件和 payload；为原单次 Bazel 命令增加仅匹配测试日志/XML 的远程输出下载规则。测试结果重复、缺失 XML、原测试失败、复制失败、隐私检查失败仍然失败。

这是一份**证据收集候选**。静态检查和离线回放不等于新的原生执行，也不补造旧作业缺失的 XML。B21 的掉接收端超时仍然是真实产品失败，根因需要另外处理。

| 对象 | 原版本 | 本候选实际 blob | 候选完整树 |
| --- | --- | --- | --- |
| 共享 collector | 00dc37697adde6154a347963ab19e8a6edebac07 | ee1b82877fbd55a2e3838d768014715617e05ea0 | 随各工作流机械嵌入 |
| B21 工作流 | fb5881fa310d3548cd604d2827fe9c29aa1b3873 | 17ff1640c21876a08396db6a40f131a26870fe84 | 45858bc96c0edbc366ec77991646b15971129975 |
| B23 工作流 | d4b87c924a1dcc795e05aec1dd4e31854dcff687 | 993d7a76a4fc6c2924e45c7ef403cecd6d108d1f | 9a6fd02aa18b2421f6aaec8a5db6ecf82b710c89 |

三份 postimage 均已通过无引用的 create_tree(content) 物化，并按上述 SHA 完整 fetch_blob，与本地全部 UTF-8 字节一致。candidate-postimages.actual.json 和 source-registration/ 保留实际原件。本包没有更新 ref，也没有发起、重跑或取消工作流。

B21 基于已发布 source ebd31e2b3e38ff72cedaa7b57bee60c1c102da27 / tree 46fca3e684217066c260dc10d0dc319a33e0a93c。其实际事件 merge 01167418c3cf2970b156bc23be911b58ced49691 同树，工作流实际 checkout source HEAD，二者不能混写。

B23 基于已发布 source e63ed76c5d8ded046f97caffbdbe2883140e6032 / tree a6831e2607e718f1343b788e5b8062a171d50a71。该作业实际 checkout merge b3bc3dcf5684568dd03f3667ecd2307b8577a0a6，同树，parents 为固定 67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed 与 source e63ed。authority/ 保留这四个已存在 commit 的完整 GET。

每个候选相对其实际父树只有本工作流一片叶子改变；从完整树移除该诊断工作流后，10,582 个原叶子与 3982ba56dc5a3f1da0c1de7ea57992f88125c359 完整一致。新树是本地重算的预期值，不是已经发布的 ref/merge 身份。

## 原生失败证据与两个独立原因

本包从根代理已经下载的官方 ZIP 原字节中逐成员校对并复制所需原件，没有再次网络下载或执行测试。

| 原作业 | 实际 testResult | 原错误 | 新解析器回放 |
| --- | --- | --- | --- |
| B21 run 42154464909 / job 127685180579 | 499 attempts，原 Bazel exit 3 | 1 个重复 Fetch ID；131 份 XML 未保留 | Fetch 作为重复元数据完整保留；131 XML 仍缺，complete=false |
| B23 run 42155150876 / job 127687422035 | 8 attempts，均 PASSED、noncached、strategy=remote；原 Bazel exit 0 | 2 个重复 Fetch ID；8 份 XML 未保留 | Fetch 作为重复元数据完整保留；8 XML 仍缺，complete=false |

B21 官方 ZIP：77,899,258 字节，SHA256 9a1e9cce3ca46b7b6176f84dd6b064588c93d217d3c3ed8e3a525d96b5fdabb4；B23 官方 ZIP：782,208 字节，SHA256 43bdccc192f96f95aebf3e7642df04ae0055f5c61970a27a8b03e05a6a9c91e3。完整 ZIP 由根的终态证据包保全；本候选仅附与回归相关、逐 ZIP 成员相等的原始子集。real-inputs/source-map.json 列出每个复制成员的原 ZIP 路径、字节数、Git blob 和 SHA256。

两个原 derived BEP 共 7,394 + 1,924 条事件，原已采日志/XML 共 867 + 8 个文件。回放时只在内存中把 file URI 的旧 runner 根目录映射到本包 all-testlogs 目录，恢复这些 URI 后完整事件对象与原件相等；原 JSONL 文件从未改写，875 个实际文件全部按原 inventory 的字节数和 SHA256 核实。该映射只为复核收件器，不是第二次原生执行。

这些 JSONL 已由上一版 collector 生成，是 credential-sanitized / opaque-payload-omitted 派生件，不是原始 BEP 字节。原缺件、原退出码、实际执行策略和全部已有测试观察均保持原结论。

## 为什么 Fetch ID 可以重复

固定 Bazel 9.3.0 的 [FetchEvent.java](https://github.com/bazelbuild/bazel/blob/9.3.0/src/main/java/com/google/devtools/build/lib/buildeventstream/FetchEvent.java) 每次生成下载事件；[BuildEventIdUtil.java](https://github.com/bazelbuild/bazel/blob/9.3.0/src/main/java/com/google/devtools/build/lib/buildeventstream/BuildEventIdUtil.java) 的 fetchId 只有 URL 与 downloader，没有 occurrence 字段，也没有 success 值。因此同一资源被多次获取时，不同事件可以拥有相同 ID。

实际观察到的重复（事件序号从 0 开始）：

- B21：1562 重复 234，crates.io/config.json、GRPC。
- B23：1387 重复 1368，rustc-1.95.0 GNU 压缩包、GRPC；1802 重复 28，crates.io/config.json、GRPC。

新的例外仅适用于 ID 恰为 fetch、Fetch payload 为对象且事件没有混入其他 payload 的情况。每次重复记录 first_event、event、id、原先和当前 payload，以及是否相等。完整派生 BEP 的每条事件仍保留原顺序。不同 success/payload 不会被去重或覆盖；Fetch success 也不作为测试通过条件。

TestResult / TestSummary / 其他 ID 的重复仍产生 duplicate_event_id。原 attempt 连号检查、summary 去重与实际次数核对、缓存检查、finished/lastMessage/原退出码核对、每 attempt 的 log/XML 要求均保持。

## XML 物化参数与边界

两个原流程的 .bazelrc 使用 common:ci --remote_download_minimal。此前的 --nobuild_event_json_file_path_conversion 只改变 JSON 文件 URI 序列化方式，不负责把远程输出写入本地。因此可产生指向本地路径的 XML URI，但该路径尚无可供收件器读取的实际文件。

本候选仅在原参数数组增加一个独立参数：

    --remote_download_regex=^bazel-out/[^/]+/testlogs/.*/(test\.(log|xml)|test_attempts/attempt_[1-9][0-9]*\.(log|xml))$

shell 中整体单引号引用，反斜杠和括号不被展开。其余原 Bazel 参数、原 target、默认 retries/threads、并发、runner、120 分钟外层预算、产品断言和 2/5 秒控制均不变。原已批准的 nocache_test_results、私有 build_event_json_file 和关闭 JSON URI conversion 三个取证参数保留。

固定 9.3.0 的完整原源码与 GET 回执在 primary/：

- [CommonRemoteOptions.java](https://github.com/bazelbuild/bazel/blob/9.3.0/src/main/java/com/google/devtools/build/lib/remote/options/CommonRemoteOptions.java) 将 remote_download_regex 标为 AFFECTS_OUTPUTS，可重复累加，独立于 remote_download_outputs。
- [RemoteModule.java](https://github.com/bazelbuild/bazel/blob/9.3.0/src/main/java/com/google/devtools/build/lib/remote/RemoteModule.java) 只把这些正则编译为下载路径 predicate，交给 RemoteOutputChecker。
- [RegexPatternOption.java](https://github.com/bazelbuild/bazel/blob/9.3.0/src/main/java/com/google/devtools/common/options/RegexPatternOption.java) 明确 matcher 匹配完整输入字符串；[RemoteOutputChecker.java](https://github.com/bazelbuild/bazel/blob/9.3.0/src/main/java/com/google/devtools/build/lib/remote/RemoteOutputChecker.java) 对 execPath 调用此 predicate，在 MINIMAL 下仍可选择匹配输出。
- [RemoteExecutionService.java](https://github.com/bazelbuild/bazel/blob/9.3.0/src/main/java/com/google/devtools/build/lib/remote/RemoteExecutionService.java) 对匹配的真实输出调用下载并等待完成；stdout/stderr 本来就会下载。这与两个原包“log 存在、部分 XML 不在本地”的观察一致。
- [StandaloneTestStrategy.java](https://github.com/bazelbuild/bazel/blob/9.3.0/src/main/java/com/google/devtools/build/lib/exec/StandaloneTestStrategy.java) 的原 XML generator spawn 将 action.getTestXml() 声明为输出；旧失败 attempt 的原日志/XML 通过原 renameOutputs 保存到 test_attempts/attempt_N。
- [TestRunnerAction.java](https://github.com/bazelbuild/bazel/blob/9.3.0/src/main/java/com/google/devtools/build/lib/analysis/test/TestRunnerAction.java) 提供原测试 XML 路径和输出映射；本候选不修改该实现。

本规则匹配两个原 BEP 中全部 998 + 16 个实际 log/XML execPath，包括 shard 与 retry 文件；不会选择一般 binary、cache_status、输出 ZIP 或 testlogs 外路径。它可能增加真实证据下载 I/O，不是完全没有运行时成本。下载成功仍需下一次原生记录确认；该参数不会把一个本来没有生成的 XML 变出来。

RemoteOutputChecker 的显式 skipDownload / in-memory output，以及 RemoteExecutionService 的 BazelOutputService 分支是上游已有例外。本候选没有引入这些配置，也不绕过它们；如果未来仍无实际文件，收件器继续 fail-closed。对未知/远程 URI 不下载、不猜测替代路径，不使用合成 XML，不把缺 XML 从完整性合同中删除。

## 工作流与来源绑定

B21 继续完整原 Intel targets：

    //... -//third_party/v8:all -//codex-rs/v8-poc:v8-poc-unit-tests

保持 macos-15-intel / x86_64-apple-darwin、原 wrapper/tag filters/default retries/parallelism、120 分钟、原源码归档和 before/after clean。由于候选是在 ebd31 后续提交，必须将 source parent guard 改为 ebd31 → cc6585 → 67cc5，同时校对 46fca3 → eaded1 → 3982 三代树，fetch-depth 从 3 变为 4。该变更仅使来源检查与新的直接父提交对应。

B23 保持 ubuntu-24.04 / x86_64-unknown-linux-gnu、完整 //codex-rs/app-server:app-server-unit-tests、原 8 shards/default threads/retries、原 wrapper/目标预算。其 merge checkout、全部 14 个 source pins、完整原树投影、source before/after、失败退出链和上传门控保持原字节。该 source guard 无需更新为一个新的硬编码 head。

两个工作流仍由原普通 PR 事件启动，没有 workflow_dispatch，没有 rerun/cancel 行为。全量原命令的失败状态优先保留；collector 失败不能使测试变绿。根在独立审阅后决定是否普通 source publication，本候选自身没有提交或触发动作。

## 隐私与回归

源码 AST 与逐函数字节检查证明，除了 reconcile 与 collect 的重复 Fetch 元数据装配以及 schema 名称，原全部其他 18 个函数/类体保持原字节，包括：

- SecretPolicy、Sanitizer、完整 BEP 净化。
- 本地日志边界、稳定复制、URI/file/digest/length 核对。
- 原 zstd 完整帧/退出码/有界 owned 子进程清理。
- 两个上传目录的文件名和内容扫描、safe-for-upload 门。
- 原 main 的退出与隐私状态发布。

离线结果：

- 原 36 个 fake controls 全部通过；stdout 与旧冻结结果逐字节相等。
- 9 个新增控制：三个实际 Fetch 重复事件对、同 ID 不同 payload 均保留、缺 XML 仍失败、TestSummary/TestResult/其他 ID 重复仍失败、混入其他 payload 的 Fetch 不获例外。
- 原独审两份不改字节的隐私反例、8 个 zstd 帧控制、缺 decoder，共 11 个 gate 控制通过；5 类包含空格的未知 Bearer header 控制继续通过。
- 真实 B21/B23 完整 BEP 回放保持 507 个 attempt 和所有 summaries；旧 139 个缺 XML 仍为唯一剩余完整性错误。
- 两个 workflow 的 shell 块通过 bash -n；完整树与机械生成/patch 均可重放。

没有运行真实 Bazel、cargo、Rust 测试或新的 native。静态接受不能提前宣称远程下载已经发生，也不能关闭 B21 产品失败。

## 复核入口

在本目录执行：

    python3 verify_candidate.py --replay

预期 exit 0，stdout 与 static-final.stdout.json 完全相等，stderr 为空。依赖仅已有 Python/PyYAML/bash/zstd；不安装或下载新工具。

- verify_candidate.py：完整源码/正反机械重建、实际父 source/merge、10,582 原叶子投影、两完整树、原参数和所有 Bash 语法、固定 primary 全 GET、实际三 postimage 全 GET。
- verify_regressions.py：原 36、9 新边界、完整真实 BEP 与原已采文件、原隐私反例回放。
- build_candidate.py：从 preimage/ 机械生成三个源码及全部 patch，只应在独立临时目录运行。
- collector.patch、b21.patch、b23.patch：完整差异。
- static-01.* 保留静态验证器首次 Merkle 目录排序错误；该问题已在验证器修复，没有改动候选源码。static-02.* 是修复后的通过原件，static-final.* 另加入三 postimage 的实际 GET 核对和完整离线重放。
- real-inputs/、privacy-originals/ 与 source-registration/：不改写的原始证据与实际对象回执。
- freeze-manifest.json：本候选冻结数据文件清单；后续独审和实际登记回执独立追加，避免改写冻结原件。
