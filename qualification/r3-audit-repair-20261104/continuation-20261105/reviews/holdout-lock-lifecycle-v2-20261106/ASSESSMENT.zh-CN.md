本页从冻结 README 派生，仅将包内相对链接改为恢复路径文字；原字节 README 完整保存在无损包中。

# B15 v2：仅修正新增测试的三处参数注释

v2 的源码改动严格限于独审 R1：在新增测试尾部的 `owner(store, None)` 和两处 `recover(..., None)` 中添加 `/*minimum*/`。共新增 36 字节。生产源码、全部断言、原 10,243 字节测试前缀、原目标与预算没有改变。

## 新旧身份

| 对象 | v1 | v2 |
| --- | --- | --- |
| 测试 blob | `2c451a3c110288ca06eb43724329c48c39bb8f1e` / 13,010 B | `c71e4a086dd33514d72bf7acb15d1c7e0f621636` / 13,046 B |
| 完整候选 tree | `7c18622c5c1b69826f7103dd2b2fec5bf572ae3a` | `605720504e547296dca1c78914fee5ed6d29844d` |
| 生产 blob | `603d36b01f6f8fe7472c72588e793f8ef169a08b` | 同一 blob，逐字节不变 |

新测试 blob 已实际物化并 fresh full GET 相等。新完整 tree 以旧候选 tree 为基底，只替换测试 leaf，实际 create 结果与完整 Merkle 投影相等；根的全部 53 项也已实际 GET 并重算 Git 对象。相对 v1，其他 10,581 个 leaf 完整保持；相对 main67，仍只有原两条产品/测试路径不同。

旧 registry `6b1f56cdb8a80535a916a7ed23e09d1bd5108824`、旧 freeze `b86d33c1f8f550decc9f15020142880dcf2f9bb7` 和旧作者目录均未改写。`v1/` 逐字节保留其全部 109 个作者成员，`v1-registration/` 保留旧 registry 及实际回执。新收据见 `old-to-new.identity.json`。

## 修正依据与资格

独审原件 `review-input/REVIEW.md` 的 Git blob 为 `103b7adedab463bc4b63fee4ccded5722644d1bf`，结论是 `REQUEST_NARROW_TEST_LINT_REVISION`。固定 main67 的 Bazel aspect 传入 `-Duncommented-anonymous-literal-argument`，三个调用对应的参数名都是 `minimum`。本包保留并按 main67 leaf 身份验证七份相关 lint/BUILD/格式配置源码。

核该独审 blob 的第一次 direct GET 曾返回 404；本地冻结原文为 8,096 B，Git/SHA256 与既有 identity 相等。随后用确切原文字节实际 `create_tree(content)` 物化，并完成 full GET equality。该过程与最初的 404 观察分别保存，没有把初次读取说成成功。

本次只证明三处源码注释满足这次独审要求。**未运行 Rust 编译、项目测试、argument-comment lint 或 rustfmt，未声称这些门通过。** 旧独审不能自动成为 v2 接受结论；v2 仍需按新身份复核。当前执行环境没有 Rust/格式化工具。本次没有重跑旧 Python/OS 机制实验，没有改变 ref、PR 或 CI。

原 Mac ARM 114P1F、实际 Busy 与预期 Rollback 的差异继续保留。原具体持锁者及调度时间线仍未知。旧受控 Linux/Python 机制结果仍只具有其原范围；没有将它们升级为 Rust 测试、原 Mac 验收或 B15 闭合。

## 离线验证

在本包根目录执行：

```sh
python verify_v2.py
```

验证器检查旧 freeze 的全部 108 数据文件和 freeze 本身、旧 registry full GET，并在完整复制的 `v1/` 上重放旧静态 verifier，要求原 2,776 字节 stdout 完全相等。随后验证：

- 三个注释是 v1→v2 的全部源码变化；移除它们后完整还原旧测试文件。
- 原测试前缀、全部断言、生产源码和 owner 的旧资格均保持。
- `v1-to-v2.patch` 与 `full.patch` 分别对旧候选和 main67 两条源文件正向应用，再反向应用，字节全部一致。
- 新 test 的实际 full GET、新完整树与实际根 GET、独审原文及固定 lint 源码身份相等。

最终 stdout 和执行信息保存在 `static-v2.*`。若需要额外重放旧完整 4,832 个 Rust 文件的调用搜索，可传 `--source-archive /path/to/source-head.tar.gz`；默认静态验证不重新执行 OS 机制实验或任何项目门。
