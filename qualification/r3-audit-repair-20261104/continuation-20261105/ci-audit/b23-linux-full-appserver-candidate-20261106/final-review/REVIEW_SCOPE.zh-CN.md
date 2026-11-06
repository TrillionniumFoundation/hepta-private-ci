# B23 完整 Linux AppServer 工作流候选：最终组装静态审阅

本候选仅新增 `.github/workflows/hepta-b23-linux-app-server-original-gate.yml`。基线为 `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed`、树 `3982ba56dc5a3f1da0c1de7ea57992f88125c359`，实际 base ref 为 `fix/r3-original-product-contracts-20261104`，预定诊断 head ref 为 `codex/b23-linux-app-server-original-gate-20261106`。根负责创建 ref 和 Draft PR，本包没有创建 ref、PR、运行、重跑或取消。

## 保留的执行合同

执行原 `//codex-rs/app-server:app-server-unit-tests` 完整目标，沿用原 GNU leg 的 Ubuntu 24.04 / x86_64-unknown-linux-gnu、120 分钟、prepare/cache/Bazel 环境和原 wrapper。BUILD 与 defs.bzl 的 8 shards 保留，默认线程、原 flaky retry、测试内部预算不改，没有 case filter。原 10,582 产品 blob 叶子一字未改，工作流运行前后会由实际 merge checkout 全树校验；剔除本工作流必须完整还原基线树，实际 merge parents 必须为 `[67cc5c..., event.head.sha]`，14 个明确源 pin 也同时检查。

仅增加已批准的三项取证参数 `--nocache_test_results`、上传目录外的 `--build_event_json_file`、`--nobuild_event_json_file_path_conversion`。最后一项仅使 JSON BEP 路径保留 local URI，不修改 BES 或执行策略。本包不声称该 GNU job 的 TestRunner 必然本机执行；实际执行证据必须以后续原生 compact log 判定。

## 最终组装相对已审 v2 的差异

工作流只有两个修改块：占位 collector 替换为实际 `00dc37697adde6154a347963ab19e8a6edebac07` 的完整 34,905 字节；source-before 后增加 zstd 路径及版本预检。逆替换后二进制全文等于已审 v2 模板。原 source guard 字节未变。接受的 collector 由本代理完整 Git GET 取回并与 b20 的本地文件比对，嵌入代码连末尾 LF 全文相等。

收件器要求全部 produced attempts 与 compact logs，保留原件摘要、原退出码、sanitized BEP 派生及净化回执。raw BEP 在两个上传根之外。两个上传动作都要求实际 `safe-for-upload == 'true'`。所有 source 记录和 decoder 预检记录都在末端隐私检查之前写入，之后不再向这两个公开根写入可变内容。压缩日志由已审 collector 解码并检查，原始压缩字节不改写；缺 decoder、损坏/不完整 frame 或凭据泄漏均不能通过上传门。collector 退出状态不取代原 Bazel/tee 退出状态。

## 实际完成的验证及界限

已实际完成 YAML 解析、七段 Bash 语法、三段 Python 编译、六个原步骤语义相等、三层真实 Git tree 重算、唯一叶增加/逆向还原、污染叶拒绝、正反 git apply、14 原源身份，以及三个离线 Bash stand-in 的退出链。三个受控结果为 `(原命令0, tee0)→最终0`、`(3,0)→1`、`(0,1)→1`。stand-in 没有执行 Bazel 或产品测试，也没有模拟 GitHub source guard 资格。

历史组件 v1 曾错误要求 literal base ref main；独审后 v2 已修正为真实整合分支。本包保留历史差异，不抹去该错误。最终本地 verifier 只把原收据中的绝对 source 路径映射到包内相同 `source/` 后缀，以允许异机离线重放；原收据和 source 字节不改。

旧 B23 `f03ce31c7e39759148577633dad9b36b4e0b3669` 摘要记录了历史 5 例的 negative 2P/3F 和 fixed 5P；旧 status/XML 原件未恢复，不把摘要升格成已回收 raw，也不在此重做旧负控。候选本身没有原生结果，B23 独立接受仍为 PENDING；未来即使本诊断目标通过，也不自动代表所有 main required jobs 已通过。
