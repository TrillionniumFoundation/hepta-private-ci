# 直接以 c12 为父提交的格式候选

候选 [fe38676f](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/fe38676fae170002fcdce90b36dc949fac3ff671) 的唯一父提交是 [c12ee03f](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/c12ee03f3185d5a13949faca54f066dfd634e509)。其完整 Git 树 `7afec5e8ba43a101b4a4c1cf4f76a7a9af5384bf` 等于逐阶段资格候选 97a379c5 的完整 Git 树。比较的 18 个路径列在 `product-diff.json`，已有 16 个文件保持 100644，两份新增文件也是 100644。

| 用途 | 路径和数量 | 采用依据 |
| --- | --- | --- |
| 归档物与真实构建者的格式路由 | `scripts/format.py`、`scripts/hepta_retained_rust.py`、`scripts/format_provenance/retained_rust.json`，3 份 | 按确切文件和 SHA 核验 37 个保留原件，7 个真实维护输入从现有构建者读取 edition。 |
| 格式回归与物理测试环境 | `scripts/test_hepta_format_scope.py`、`scripts/tests/test_format_starlark.py`，2 份 | 保留已有测试，检查篡改、缺失、别名及期望的预格式化差异。独立 Starlark 测试目录需要携带路由依赖。 |
| 真 HCSN 构建夹具 | `qualification/hcsn_training/native_fixture.rs`，1 份 | 移动两个独立 import 及原 payload 篡改拒绝断言换行。当前三 CPU 后端在旧/新版分别运行签名桥并得到相同模型/时钟摘要。 |
| 原本已经选中的普通 Rust 源 | 12 份，见上一级 `maintained-12/sources.json` | 直接受检的源码后像。4,175 个普通输入的 formatter 参数及 cwd 原样，其余 4,163 个原检查通过。软件注册和产品接线的既有缺口另存。 |

在包含两个原提交对象的 checkout 运行 `python3 verify_write_scope.py /absolute/path/to/hepta-private-ci`。它读取两端四个相同 Git 对象，用仓库原测试夹具执行真正的 daemon 后像检查器。每端原来的正反测试各一项，另有 12 次逐路径及一次全批控制。11 个候选源码单独作为 daemon 写后像仍拒绝，仅原有 hepta-agentd 目录中的 1 项仍许可。12 项一并提交的模拟后像亦被拒，两个版本的判定逐项一致。

原始 daemon 工作流、写后像守门、Cargo 注册、生产权限和科学证据均不在这 18 个路径中。候选本身只包含上表的源和回归测试。宿主工作流位于单独的[诊断提交](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/de2ed0f54ab478b90ad512300a15774a4f5317d0)。在准确 c12 上需要这套格式维护时，可在独立分支 fast-forward 到 fe38676f；每个源前像和整个 Git 树都可在采用前独立核验。

`product.patch` 是该单父提交的纯 Git diff，80,299 字节，SHA-256 为 `2c355d21735f3999fa34c9e34cc307cdf1c81948eacb876334400ff39bdbc586`。用临时 Git index 在 c12 树上运行 `git apply --cached --check product.patch` 并实际应用，得到与 fe38676f 完全相同的根树。核验器所用精简本地对象库仅保有此次读取的 blob，计算覆盖整仓的根树使用了 Git 的 `write-tree --missing-ok`，所有子树与根哈希仍与官方原提交一致。完整 checkout 可直接用 `git write-tree` 复核。

[本次独立原固定基址宿主作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45149359568/job/137606520425) 已通过。完整读检查用时 157.906 秒，完整写入口用时 159.889 秒，二者均退出 0，两次 Git 全部状态均为空。37 个历史物和 7 个真构建者共 88 次原命令调用均通过，4,175 个普通 Rust 文件保持原命令与目录，41+3 项原/新增测试通过。

`python3 verify_direct.py` 从 35,745 字节 GitHub 原件复算 18 行 Git 对象/模式、源/父/固定基址、4,219 源清单、88 次调用、两条入口的时钟/退出值及两次洁净状态。原件 SHA-256 为 `fd2e0e3d8ffd070534f19041cce1f045b0d357735d6389439d2cb90612b96970`。
