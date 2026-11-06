# Skills marker 夹具 V2：修正空 TOML 表插入

上一版负控真实执行了原 1 例，但在 `host_roots_tests.rs:425:11` 以 `index not found` 失败（0.008 秒），尚未到原 roots 断言。它不是有效因果负控。原 bundle 为 `92b497559c315c0cc48db5a8d7f3de89470a2158`；raw、JUnit、逐例 review、因果拒绝和 finally 恢复五件原件均已重新核对 bytes/SHA。runner 已恢复旧正向树 `1125d197cf798176bea6dcc2c0b0c499eb22cf44` 并停止，没有执行正向 9 例、migration 或 V8。

根因在夹具：`empty_config()` 返回空表；V1 的正向与负控都用索引赋值写不存在的 `project_root_markers`。V2 两版均改为 `as_table_mut().expect("empty config table").insert(...)`，插入的键及非空 marker 数组完全相同。原 production 文件未改。

V1 已冻结在 `v1-frozen/`。V2 正向 blob 为 `ffae69d365402929787f9029a15f02d9c328149b`；负控为 `0af7f9a6be0f1e6795bd5f7ab9006d0c8ce24a88`。两版仍仅差真实 outer marker 的创建；原 roots 完整断言逐字保留，位置分别为正向 443:5、负控 446:5。所有其他原定义和预算不变。

从当前真实旧正向源开始，先应用 `v1-positive-to-v2-negative.patch`；原 1 例必须在 446:5 显示实际有序 left 为 owned outer 与 cwd 两路径、expected right 仍只有 cwd，并且 outer 来自 `<` 新增行。准备失败、超时、零选中或其他错误都无资格。随后使用 `v2-negative-to-v2-positive.patch` 精确恢复新正向，只有有效负控后才执行原 9 例。已有 finally 的 source/index/lock/untracked guard 与无效后停止规则继续保留。

七种 patch 路线已在云端隔离副本实际 git apply/check，逐字到达对应 postimage；这只是静态重建。V2 尚未 fmt、编译、native 执行，没有新 PASS；本轮没有修改共享 native 源、index、target 或 refs。
