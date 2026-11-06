# PR 4936：ac18 格式验收与 aaf 首次自动 CI 切点

本包固定截至 2026-11-06 09:30:05 UTC 已实际取回的原件；没有重新执行、手动触发或取消任何 CI。它追加到既有失败与排队历史，不覆盖先前证据。

## 当前能接受的范围

ac18 源 `ac18b623c7a6cb953b4660979e9b620fe7176bb2`、树 `c3e9ddc1799f470ac7c80e117ee953a7232847e0` 的原自动 repo-checks 作业 **127809329291** 成功。完整日志实际 checkout 为 PR merge `c9baaf38b95da145fb4f9d371b8d134169d313cc`，与 ac18 同树，parents 为 `[63652be658ebed8d3052eb789b951793384fd5e4, ac18b623…]`。原 `just fmt-check`、Prettier 和 clean-worktree 步骤均成功。作业时间为 09:12:52–09:15:24 UTC。完整 122,199 B decoded log 与原 MCP 内容逐字相等。

这为先前按原 Rustfmt 输出作的两文件、三块空白修正提供了适用源上的原 CI 验收；它不是 Rust 产品测试通过，也不证明未缓存执行。旧 2d/a0cb 格式失败保持原来的失败归属。后继 aaf 的三个新 Python/workflow 文件不继承 ac18 的格式资格。

同一 run **42186354218** 的完整 scope 作业 **127802986289** 明确使用 base636 与 source ac18，原 JSON 包含 **1,561 个唯一路径**，`full_repo=true`、`native=true`。该作业最后 checkout 是 source HEAD ac18；它与 repo-check 的 merge checkout 分开记录。原规则因此跳过 scoped 作业，并选择 fast `rust-ci.yml`。该 reusable 并不运行整个 Cargo nextest；不能把 full_repo 字面名称当作全量 Cargo suite 的执行证据。

本包的第八次 blocking 切点是完整 29 jobs：**6 success、16 queued、4 in_progress、3 skipped**。这是当时窗口，未宣称是该 run 的最终终态。第六、七切分别保留此前排队到 Codespell 成功的原 API。

ac18 的 cargo-deny **127809329246** 在完整 API 中是 success，`Run cargo-deny` 与 clean-worktree 两步也成功。本次第一次取完整日志返回工具层 `Transport closed`，已原字节保留且未重试；没有拿到该 stdout，不能声称已全文审读 cargo-deny 输出或绑定其中实际 checkout，也不能把传输错误当作原 CI 失败。

## 新后继只保首次排队事实

正常发布的 arg0 fixture 后继为 `aaf86881da0b3a7651b4a6a56be49515b9aa9f2e`，树 `66552bda88637403f4f1d72a5be8592e07a8a308`，唯一 parent ac18。实际 merge `8ca7a5b30bf6abfaf3ad7bb538d00f505d0847f8` 同树，parents 为 `[63652be…, aaf86881…]`。根原 commit/ref/PR/merge 发布回执均保留并核对。

首次 head 查询完整 18 runs、18 唯一 ID，全部 `pull_request`、attempt 1、head aaf：**12 queued、4 pending、2 skipped**。其 blocking run 为 **42195225682**，当时 pending。此包不包含 aaf 的测试或格式通过资格；随后观察必须另存新切点。

## 原件与复验

`ORIGINALS-MANIFEST.json` 绑定 22 原件：三个旧 head jobs 切点、新 head 首次 runs 列表、两完整 job log 及其 MCP、一次实际工具错误、两条源发布链，以及 ac18 全树和两份路由源码。完整 10,802 叶与所有目录 Merkle 等于实际 c3e9；路由源码叶哈希相符。

`verify_ci.py --root <本目录>` 只读取本包，校验全部 bytes/Git blob/SHA256、API total/唯一 ID/源/run、两个实际 checkout、scope JSON、格式步骤、两条 parent/tree/PR/ref 链及保留界限。最终实际 exit 0，空 stderr，stdout 3,416 B，保存在 `verification-02.stdout.json`。首次本地 verifier 未兼容第六/七切原包装的 `raw` 字段，因 KeyError 停止；旧脚本与空 stdout、完整 traceback 均保留。仅修本地解包，不改任何 API、源码或 CI 状态。

本包没有 blocker 状态迁移；没有把 queued、skipped、旧源通过或工具失败转换为产品接受。
