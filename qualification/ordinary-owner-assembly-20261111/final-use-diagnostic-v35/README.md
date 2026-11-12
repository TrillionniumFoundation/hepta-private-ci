# V35：原 retained FinalUse 拒绝诊断

本候选从实际受测 V34 `d9737937eaccccf2ed2f1f79444ddec6c10d0eea` 的原始源码形成，只包含六个 Rust 路径的十一项精确诊断增量。它增加原错误分支标签，保持原锁、slot、失败状态、错误类型和授权语义。诊断在原状态 guard 释放后输出，嵌套 scope 只合并首个拒绝，debug 每进程最多 64 条；release 无诊断状态和输出。

本候选不包含 future until 构造器或同会话 phase。当前 CALLERS `d9478557509a1e70b7b32b02b86cfd2aa2babbd5` 的 504 boundary / 366 protected 原字节，以及 allowlist 原字节均保持；该版本尚无 Frontier 单独保护表，不能误植未来分支的累计表。现有三个受影响保护表的真实代码顺序已做静态投影，原检查器尚未执行。

V34 原结果为普通 1950/1950、Root 16/17、QA 236/236、清理 9/9，整体仍失败。唯一失败在 Initial 首次 Publish 的 retained FinalUse 校验，内部叶因未知，本轮未到 Recover。V35 用于获取原拒绝叶因，不声称修复。它必须运行自己的原始七包/精确 Root17/完整 caller 入口，不能继承旧 PASS；500 ms 仍从原 request_started_ns 计算。

普通完整链、正向采用链、NoUpdate/rollback 链仍为 0/0/0；独立 C 与真实 daemon+Root OS 重启均未验收。本源仍只用于 Draft 工作，不合并 main。
