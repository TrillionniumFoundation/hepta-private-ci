# r29 正式附件的本地封组准备

本目录仅准备纯本地 reader。当前没有读取 r29 活动日志，没有执行 reader，没有创建 `native-evidence/r29-workspace-checkpoint/`。待 root 唯一下载完整实际 archive、完成安全解包并提供真实 pins 后，再绑定并执行。

固定源码为 source52 commit `1e0910becc37383e6d17ecf861ea844fd07d8862`、tree `211f15baff19095e8c98bcea2b0ed99ca2270ade`。原 r29 job 为 `1a1b1f83e4b-fc05-7bcd`；本目录不声明该 job 的终态。已知 195 个源码、193 个默认 workspace members 是输入范围，不是测试数量。

## 绑定要求

保留 `ASSEMBLY-INPUTS.template.json` 不变，另建实际 `ASSEMBLY-INPUTS.json`：

- `binding_state` 改为 `ACTUAL_CLOSED_ARCHIVE_BOUND`。
- `archive` 填真实 `bytes`、`sha256`、`git_blob`、`members`、`indexed_members`；没有预设成员总数或测试数。
- `closed_directory` 和 `unpacked_directory` 为真实本地目录。原 tar.gz 名称是 `checkpoint-r29-closed.tar.gz`。
- `root_readbacks` 与 `supplemental_originals` 是明确文件列表。每行包含 `path`、`destination`、`bytes`、`sha256`，可含 `git_blob`；所有文件在封组前逐字节核验。
- 补充原件的 `role` 至少包括 `gate_binding`、`gate_authorization`、`export_template`、`export_binding`、`export_authorization`、`export_custody`。仅采用真实闭合原件，不读取随后的活动状态。
- `export_original_job_id`、`export_terminal_destination`、`export_result_destination` 指向实际自然退出的 exporter。它的退出 0 仅证明归档成功。
- `actual_exporter_files` 指定补充附件中的 `template`、`bound`、`final`、`binding_values`、`root_approved` 相对 destination；reader 独立逆回三项实际绑定，并核 final 只有 `FROZEN` 翻转。

原件来源和待存路径都属于本地工作区，不启动 native、Git、Rust、Cargo metadata 或 formatter。root 负责二进制上传和 ledger，reader 不执行这些操作。

## 结果核验

reader 将核验整个 archive、INDEX、解出字节、195 份源码的 raw SHA/Git blob/Git mode、原双锁、全部 guards、controller 输出连续性，以及当前原 no-p `just test --locked --retries 0` 的 raw rc、receipt、resources 和自然外层终态。

完整 metadata 必须来自 r29 原调用，重新解析 193 个 member/default-member ID；不以旧 metadata 冒充本轮。测试计数动态读取原 `Starting`、`Summary` 与 Summary 前的唯一 binary/name 行，不与 r28 或更早结果相加。完整通过、完整失败和没有 nextest Starting 的情形分别记录；没有完整终态统计时，测试总数和终态计数保持 null，而观察到的行另列。

原 r28 的 26 件前置原件加外层 terminal 从本次 archive 按原 pins 保存并核验，Python32、四包 strict、1564 个四包 ID 都只作为前置资格，不计入本轮工作区总数。旧 r24/r26 失败原件保持历史身份。

只有全部本地核验通过后才写新正式目录。较大 UTF-8 附件可用 mtime=0 gzip，无损解压逐字节验证；同字节大件按来源映射去重。195 份完整源码与原双锁保留于原 archive，不复制第二棵源码树。

## 待实际 archive 后的调用

```text
python3 r29-formal-preparation/verify_and_assemble.py --inputs r29-formal-preparation/ASSEMBLY-INPUTS.json
```

最终可用 `--verify-only --output <正式目录>` 只复核已封附件。当前仅允许 AST 与静态检查，不能执行以上封组命令来试造缺失原件。
