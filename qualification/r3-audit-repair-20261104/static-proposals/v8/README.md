# V8 sandbox 默认特性独审

结论：接受仅在 codex-v8-poc 的 Cargo.toml 增加 `default = ["sandbox"]`。原 unsafe linked-library probe、完整 equality assertion 和全部 6 个原测试保持不动。后像为 `a34a1306f1082b3347543749cbfd9a05eee7cb91`，补丁为 `1552877bb076eab752f2b1a5444591375365026f`，1 行新增。

已独立读取并重算原 full-run 中 V8 的完整 656 字节失败块：source tree `f8251e1d14fa8524ab469281296cd4cf708f173c`，原用例 `tests::sandbox_feature_matches_linked_v8` 在 0.004 秒以 linked `true` / local cfg `false` 失败。没有把其他 17 个原 full-workspace 非通过项归为同因。

固定源证明 code-mode-runtime 显式启用了同一个 v8 150.4.0 的 sandbox；Cargo 的普通依赖特性合并不会反向启用 v8-poc 的同名本地 feature。因此正常联合编译应让本地默认 feature 明确启用原 forwarding edge。这也与已有 Bazel 的 sandbox 设置一致。

上游固定版本的 V8 module 仅在内部测试暴露这个不稳定 FFI probe；binding 模块私有，build script 没有向依赖者导出 sandbox 配置合同。不能用实际 probe 值同时生成 expected，也不能仅保留 true 分支来消除原 off-state 断言。更广义的依赖编译配置 API 属于另一个上游改动，不是当前一行修复的前提。

必须如实保留边界：单独使用 `--no-default-features -p codex-v8-poc` 可对其独立实际图验证 off-state；同一 invocation 若再选择硬启 sandbox 的 code-mode-runtime，仍会 local false / linked true，本补丁不声称该组合满足原合同。不得拿一个强制 sandbox 的外部 archive 冒充 off-state 原库。

本地只执行了隔离 git apply --check、实际 apply 和 TOML 对比，证明唯一语义变化是默认启用 sandbox。未跑 Cargo、Bazel 或原生测试。下一门槛包括原 just bazel-lock-update / check 的真实两个锁结果、原 6 例和正常 whole-workspace 门；锁改变或不改变均按实际记录。
