# Source 50 原始候选准备快照

本组保存针对 source49/r23 八个失败用例的四组候选及三项 CI owner selector 增补。9 个路径已通过完整补丁正反和独立静态审查；本快照未创建 source50 commit，也未授予原生测试资格。

`stage50-provisional-input.tar.gz` 是冻结的应用输入，`reviewed-candidate-inputs.tar.gz` 包含原件、补丁、完整候选、独立审查、真实 Git 克隆探针及最终 fix 范围准备；`INPUT-INDEX.json` 给出每件原始字节的身份。77 行迁移用例前置只向子进程配置 Git URL rewrite 和 file transport，本组没有声称 Git 配置完全不变。

既有 dev dependency 的平台范围改变要求实际运行 `just bazel-lock-update`。真实锁文件产物必须进入最终源码身份，再执行受影响四包严格 lint／完整测试及 193 默认成员的完整 workspace。所有门通过后才执行最终 scoped fix 和 fmt，其后不再跑本地测试。

七个角色是功能职责，HNMF 七类是记忆组织分类；科学结论仍为 **HOLD**，权限仍为 **DENY_ALL**。
