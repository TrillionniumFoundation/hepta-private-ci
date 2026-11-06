## 为什么需要这个诊断

当前整合源 `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed` 的三个 signal 用例受 Linux cfg 限定。B23 需要原完整 AppServer 目标在 GNU leg 的原生执行证据，其他平台的通过不能替代这部分资格。

## 本 PR 的改变

仅新增 `.github/workflows/hepta-b23-linux-app-server-original-gate.yml`，在 Ubuntu 24.04 / x86_64-unknown-linux-gnu 上执行原 `//codex-rs/app-server:app-server-unit-tests` 完整目标。保留原 8 shards、120 分钟、wrapper、prepare/cache/Bazel 环境、默认线程和重试；没有 case filter，也没有修改原 10,582 产品 blob。

运行前后校验实际 PR merge checkout：base 必须是 `fix/r3-original-product-contracts-20261104` 的 `67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed`，merge parents 必须匹配 base 与 event head。剔除唯一新增工作流后，完整 Git 树必须恢复 `3982ba56dc5a3f1da0c1de7ea57992f88125c359`，并额外核对 14 个原始来源 pin。

三项取证参数关闭测试结果缓存、写出上传目录之外的原始 JSON BEP，并在 JSON 中保留 local URI；不改 BES 或执行策略。收件器保留全部产生的 test attempts 与原 compact logs，对派生 BEP 做凭据净化；两个 artifact 上传均要求实际隐私门通过。压缩日志会解码检查，原压缩字节不改写。原 Bazel、tee、收件器和上传结果分别保留，最终门不会把原失败变成成功。

## 已完成的验证

工作流 blob 为 `d4b87c924a1dcc795e05aec1dd4e31854dcff687`，60,049 字节，已实际创建并完整回读。嵌入的收件器逐字节等于已独审的 `00dc37697adde6154a347963ab19e8a6edebac07`，包括末尾 LF。

已完成 YAML 解析、7 段 Bash 语法和 3 段 Python 编译、6 个原步骤语义比较、实际祖先树重算、唯一叶正反 patch、14 原源身份，以及受控 Bash stand-in 的三种退出链。独立最终源码审阅 `8c68dc2cca5bcff0eb99614eca5e39809dd616de` 接受本候选，未发现源码阻断。

原生结果尚未产生；这些静态检查和 stand-in 不构成产品测试通过。B23 独立接受仍为待核验，诊断目标通过也不会自动把全部 main required jobs 记为通过。
