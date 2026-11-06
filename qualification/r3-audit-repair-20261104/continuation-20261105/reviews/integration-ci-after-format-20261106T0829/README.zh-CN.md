# #4936 格式后继的首个有界 CI 增量

本包只接受完整 API 收件、身份绑定和状态计数，不授予新提交原生通过资格。

新 head `ac18b623c7a6cb953b4660979e9b620fe7176bb2` 的首次列表包含全部 18 个唯一 pull_request run，均为 attempt 1。08:18:13 UTC 之前取得的状态为 12 queued、4 pending、2 skipped；pending 与 queued 分列。blocking run `42186354218` 的 08:23:03 和 08:29:43 两次完整 jobs 响应均为 total_count=0。这里的时间是调用完成之后取得的上界，不是各 API 请求同时发生的时间。

旧 head `2d1137b1ba39fab0e6a28bac8decc114dfa0138c` 的 blocking run `42180997764` 在 08:23:03 之前取得完整 36-job 列表：8 success、21 cancelled、1 failure、4 skipped、2 queued。唯一失败是 `repo-checks / build-test` 的格式检查；其完整日志、三处原生 formatter 差异、两个最小后继 postimage 已在独立旧格式包中固定，registry 为 `9c783f6a6b9a83b4d6e0128b2d5b5fc09684112a`。本包不覆盖它。

旧 cargo-deny job `127779715991` 的 API 表明原 cargo-deny 步骤和 clean-worktree 步骤成功，运行窗口 08:02:06–08:02:51。完整日志连续两次收件均返回工具 `Transport closed`；两份完整错误原件均保留。没有取得该日志的完整 stdout、实际 checkout 行、缓存或逐项警告证据，故这里只记录 API 成功，不把另一 run 的日志替代本 run。工具传输错误不会把该 native job 改记失败，其底层原因未知。

旧 GNU Clippy job `127779716340` 为 cancelled 且 steps 为空；API 的 started_at 不作为真实编译启动证明。cancelled 与 skipped 均不算通过。API 没有证明取消的操作者或因果关系，本包不据时间相邻推断。旧提交的任何成功均不转授新 ac18。

原件是 MCP 完整返回对象的 JSON 序列化，不是 HTTP wire capture。所有 6 个原件有独立 bytes/Git/SHA256；`verify_packet.py` 完整解析 API，总数与唯一 ID 相等，核全部 head/run/attempt、精确 URL、失败步骤和两次原工具错误。第一版本地 verifier 把带 `filter=latest` 的两个原始 URL 误写成不带参数的字面量，因此本地重放失败；初版脚本及完整 stdout/stderr/exit 原样保存。第二版只纠正这两个 URL 绑定，未改任何 API 或 native 结果，离线重放 exit 0、stderr 0。

未启动、重跑或取消任何 CI，未查询私有容量，未改产品源码或 refs。本包不额外关闭 blocker。新 ac18 的后续切点、终态与日志另行追加，不改本包。
