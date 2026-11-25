# 最后代码与科学 payload 的仓库门

本记录实际检查 head `f2cefb7643dad2adc726b62c5c7bf0c48791dc3b`，比较基线为 main 的精确提交 `732e934ba496d90fbe042b8d41d479ef901643e5`。代码冻结 head 为 `37198eefdcc1b83d163e0441cb651e1377e6cd87`；检查前已核对全仓 400 个 `.py` blob，二者完全相同。新增的 multihost 汇总已包含在被检查 head 中。

## 实际结果

从隔离 worktree 的 `codex-rs` 执行官方 `just fmt`，退出码 0，stderr 为空。输出明确为 `No changed files need formatting. Use --all for a full repository check.`。这是干净已提交工作树上的 scoped no-op；默认 Python 分派也不覆盖 qualification，不能据此宣称研究 Python 已按 Ruff 排版或全 Rust 格式通过。

官方 blob checker 实际执行：

```bash
python3 scripts/check_blob_size.py \
  --base 732e934ba496d90fbe042b8d41d479ef901643e5 \
  --head f2cefb7643dad2adc726b62c5c7bf0c48791dc3b \
  --max-bytes 512000 \
  --allowlist .github/blob-size-allowlist.txt
```

该命令退出码 0，stderr 为空；检查 130 个新增或修改文件，全部位于本次研究目录，最大 blob 为 499,512 字节，没有违规项或 allowlist 例外。allowlist 与 main 完全相同。该门只检查记录中的 base→head 差异，不声称整个 Git 历史都满足大小限制。

143 个物化文件在两门前后整体 SHA256 相同，没有文件发生改变；`git diff --check HEAD` 返回 0，工作树保持干净。没有重跑科学实验，也没有修改任何源码、候选权重或科学数据。

## 收据与传输恢复

启动调用的 MCP 响应超时，未返回 runtime job ID。没有因这个响应丢失而重新启动。随后从预先确定的结果位置只读取回已经完成的 `GATE_RESULT.json` 与四份原始 subprocess 日志；每份日志的原生读取 SHA256 和大小均与 gate manifest 一致。

因此这里保留的是实际官方子命令退出码和版本绑定的结果文件证据。没有另行取得 native supervisor 的终态；不能把 MCP 超时隐去，也不把它误记为门失败。

- `GATE_RESULT.json`：精确 heads、官方脚本 blob IDs、命令、退出码、计时、400 个 Python blob 的身份核对和物化文件不变性。
- `FORMAT_STDOUT.txt`、`FORMAT_STDERR.txt`：实际 formatter 输出。
- `BLOB_STDOUT.txt`、`BLOB_STDERR.txt`：实际 130 个 changed blobs 的逐项结果。
- `READBACK_RECEIPT.json`：本次传输响应丢失的恢复说明、原文件 SHA256/大小及日志汇总。

后续提交本目录收据属于纯证据增量，不会自动改变这里已经记录的 checked_head。
