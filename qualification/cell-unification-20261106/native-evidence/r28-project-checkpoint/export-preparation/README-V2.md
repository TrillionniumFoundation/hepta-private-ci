# r28 exporter v2：已闭合 controller 字段读回

当前应审阅的惰性文件为 `export-r28-closed-template-v2.py`：**33,598 B / SHA256 `4568d25b1d122e209ce59d9f1a4015e65ca77246f23b2ece4f86b07a6398d4d8`**。原 `6e3b27eb…` v1 及 `HANDOFF-MANIFEST.json` 全部原样保留，未执行。

唯一变更位于 controller 分块校验：`process_read.size` 是读取时的总输出流长度；分块长度必须等于 `next_offset - offset`，同时原 `size >= next_offset`。text/hex 相等、分块 offsets 连续与最终 terminal 的 `seen == stored == 总字节数` 仍严格保留。`v1-to-v2.patch` 为700 B，整文件逆变换精确恢复 v1。

`derive_and_verify_v2.py` 仅读取五份已闭合本地 controller JSON、做 AST 与字节比较，没有 import/运行 exporter，没有 native、Rust、探针或格式化动作。实际 stdout 分块为2995、2730、2584 B，连续终点2995、5725、8309；stderr为0 B。终态 seen/stored 与该总数完全一致，详见 `V2-CONTROLLER-READBACK.json`。

v2 继续保留 `FROZEN=False` 与三组 `None`。它不改变此前 README 中的 source195、原26闭合输入、31 apply 原件及 source50/source51 血缘保存范围。原 r28 Rust 返回值与计数没有写成 exporter 常量。

当前完整准备目录的新增封存清单是 `HANDOFF-V2.json`；旧HANDOFF只代表其原12文件历史快照。之后的 actual pin 绑定和 `FROZEN` 翻转由 native/root 独立审核，新脚本不得覆盖这两份惰性原文。
