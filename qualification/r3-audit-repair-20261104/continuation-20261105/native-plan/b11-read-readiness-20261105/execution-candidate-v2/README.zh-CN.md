# B11 read-readiness：V3 身份反事实后的 helper 执行接线

本包仍是未执行的静态候选，不更新任何分支或运行中的源。基线是 `0f6148ea3fbe9d1263354791d5cc63c7e66d4628`，树为 `f717a84a856413d87a3b718b0bcae3adbd16b643`。它把已审的 readiness 三源提案、三路 helper 执行接线和已审 V3 身份反事实脚本组成 7 路可审后像。完整合成补丁为 400 行新增、99 行删除；三个独立来源的补丁及历史版本都保留。

## 相对 V1 的唯一消费者变化

V1 已完整冻结并实际 create+GET，publication map 为 `b9bc0f02090abec911c1eb484d95f38d4ef90658`。V2 的 helper runner 只将 `CONTROL_BLOB` 从 `25def4386ea08bb72a7605cc113117f31fffcd1b` 更新为 `3680db31233e47ba7fad99f31a7019c4536288bb`。collector 与 workflow 后像逐字不变。V3 脚本九个非 main 函数、原负控命令/判据/finally 和 entry/restored/terminal 接口均保持；新的 `positive_scopes` 不改变消费者的恢复门。

V3 会先保存原 whole target 的结果，再为四个原有阳性各执行一次独立 exact 范围，满足其原资格条件后才运行原身份反事实。该设计已由 CI 独审 `c4ff565c7d003890d6ad42420ec18e802053f467` 接受为静态候选，尚未取得本轮 Windows 实际执行资格。旧 0f native7 的 prerequisite 输出交织造成 `INVALID_NOT_RUN`，没有源修改、没有有效负控；该原件不被 V3 或本包回写为成功。

## helper 的实际门与范围

新增步骤位于身份反事实之后。它要求前一步成功，并验证实际终态为 `VALID_NEGATIVE_AND_EXACT_RESTORE`、物理负控合格、原始字节精确恢复、无错误或恢复错误。随后复用按固定 blob 加载的原 guard，要求完整干净 worktree、无暂存修改、完整 index 语义条目、原 ACL 源和测试、两个原工作树锁文件与前一 entry/restored 收据相等。readiness 三源、原 helper 入口/测试/Cargo/BUILD/defs、wrapper、collector、V3 脚本均须精确匹配固定内容且属于当前 HEAD。原工作树 CRLF 字节与 Git 的 LF 内容分别记录。

只有这些前提成立，才运行已有独立目标：

`//codex-rs/windows-sandbox-rs:codex-windows-sandbox-setup-bin-unit-tests`

此 target 由既有 bin-unit-tests 规则注册；新 Rust 模块由原源码 glob 纳入。它与原库 156 例是不同目标。命令保留原 MSVC/Bazel wrapper、平台、标签筛选和日志参数，不传 case filter，不增加 timeout；显式 `--nocache_test_results`、`--flaky_test_attempts=1` 保证没有缓存测试结果或重试资格。编译动作可复用原缓存，不能把这一点误称测试没有执行。原 incompatible-target skip 参数仍存在，但任何实际 skip、cached、FLAKY、缺失或歧义终态都会被新证据门拒绝。

新阶段保存完整 console、真实 argv/退出码/耗时、源前后与 final guard。原 collector 只新增 helper 一行到原 11 目标末尾，保存该调用实际可取得的 log/XML/attempts，缺失仍明确失败。它使用独立新目录，逐成员核长度/SHA、当前 HEAD/tree 和干净状态。原 upload 已覆盖该目录。此前 PTY 留存候选没有被合入。

成功要求每个实际编译出的 helper 用例均有唯一 `ok` 正文；10 个旧 source anchors 和新增 named-mutex 控制必须出现，不能把 anchors 当完整 roster 预设。原 Windows launcher 若分批执行，每批编译总数、实际逐名并集与 passed 总数共同证明覆盖，ignored/失败/重复/未覆盖均不合格。唯一外层 XML 也必须成功且无 skip/error/failure。所有命令前后 source/index/锁都保持，才可写 helper 限域成功。

原 whole-library 失败、原身份反事实失败和原 120 分钟 job budget 均不被覆盖。helper 失败会留下自己的非零状态；硬取消或 guard 失败不冒称完整成功收据。工作流 permissions、runner、环境及旧执行步骤原字节保留，只有必要路径触发、旧步骤 id 和新步骤加入。

## 尚未取得的资格

本包只做 Python 语法/YAML 解析、固定字节检查和隔离 Git 正反向应用，没有运行 runner、shell、Bazel、Cargo 或 Windows。静态合成执行顺序为 readiness patch → execution V1 → 一行消费者 pin delta → V3 counterfactual patch，7 个最终后像与直接应用完整合成补丁完全相等。

setup-bin 通过也不等于 Full 路径真实完整读授权、read SID、loader 或后代 custody 通过。原 readiness 仍保留相同根集、权限/token/write/deny/builtin-RX 跳过及缺根处理，仍继承父层 INFINITE/无本地 deadline，合法并发的 busy 可能显式失败。B11 隔离边界继续 OPEN。

后续沿用原脚本回归入口 `python3 -m unittest discover -s .github/scripts -p 'test_run_bazel*.py' -v`，以及本工作流的原库、V3 身份反事实和完整 helper 目标。此包没有新增重复业务测试，也没有用静态验证代替上述原 Windows 门。
