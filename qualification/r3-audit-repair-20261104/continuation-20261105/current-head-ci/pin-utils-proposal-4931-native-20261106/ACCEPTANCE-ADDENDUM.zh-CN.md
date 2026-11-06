# 实际双锁产品输入的正式独立接受

原始产物、产品映射和所有旧中断检查点保持原字节。本增量补上正式独立接受：

- 独立 REVIEW 实际 blob：6e4b893e481623a1c56520b05550438e502131a9，18,824 B，SHA256 42da66745d44159d3b8236f37efbdb548736fc476241280a6c872a2f51c56707。
- 决定：ACCEPT_ACTUAL_DUAL_LOCK_AND_223_PRODUCT_POSTIMAGES_FOR_INTEGRATION。
- 产品实际 tree：c7b9fb4e029dc38034a7dfce10a646ccde3e0bf6；原基线 67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed / 3982ba56dc5a3f1da0c1de7ea57992f88125c359。
- 产品源 registry 实际 blob：5cf849cc78dd2d706aa30f5b20868f941e96b90d；223 个路径、219 个不同 blob 全部完整读回相等。

独立验证器分别完成 393 项产品图与来源校验、570 项实际 API/日志和作者隔离回放校验、903 项实际 Git 对象登记校验。完整 Cargo 字典与唯一允许变换严格相等，其他包连依赖数组顺序保持；193 个 workspace metadata 项完整 JSON 相等；MODULE 只出现精确的 5 个旧 fact 删除和 4 个新 path fact，其他全部字段保持；所有 220 个 vendor 字节和模式均由固定官方 archive 与 14 个精确变换重建，并保留 76 个既有 aws-config 维护叶。

核心封存包含 280 个成员（20,227,904 B），保留完整原 ZIP 的 41 个成员；独立增量包含 51 个成员（865,455 B）。两者都有无损分片、逐件身份及隔离恢复入口。

先运行 restore_packet.py --packet <本目录> --destination <新核心目录>，再运行 restore_independent.py --packet <本目录> --native <新核心目录>/root --destination <新独审目录>。两次均只运行本地 Python 标准库与 Git index/hash/apply；不重新执行 Cargo/Bazel 或产品测试。独审增量的 REVIEW.json、全部原始回执和三验证器可单独在恢复目录检查。

原实际 PR #4931 作业的成功范围是生成提案、完整双锁守卫和未修改的 cargo-deny 命令。本次接受允许主审构造包含这 223 个产品路径的整合候选；不同组合树的编译、测试、平台合同和 B02/B15 闭合仍必须由其自己的实际 CI 证明。本包没有创建 commit/ref/PR，没有手写锁，也没有改写旧 NOT_PRODUCT_ACCEPTED 检查点。
