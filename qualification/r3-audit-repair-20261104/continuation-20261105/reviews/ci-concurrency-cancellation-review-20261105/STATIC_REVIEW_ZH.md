# 固定 0e139 并发组取消核查

**结论：没有发现可证明的仓库配置自取消；实际取消原因仍未确定。**

已逐 Git blob 核对 93 份完整 workflow，解析全部 21 个 reusable job 调用。没有 job 级 concurrency，也没有 concurrency-group 输入或 with 传值。blocking-ci 只调用一次 Bazel，caller 不带 matrix；Bazel 内部四个 matrix 均为 fail-fast: false。

PR #4797 下，父组为 `blocking-ci-fix/r3-original-product-contracts-20261104`，callee 组为 `concurrency-group::blocking-ci::pr-4797`，两者不同。GitHub 官方规则明确 callee 的 github.workflow 使用 caller 名；已按 blocking-ci 计算，没有误用 Bazel 名。其余七个 blocking 子工作流无 workflow/job 级并发组。独立 V8、UI、Objective 组也不与这两组相同。

此结果仅排除上述固定调用图中的同组自取消解释。现有配置仍允许另一个同组 run 取消旧 run；head/base 不变不能排除这种情况。保存的 API 查询只覆盖单一 head，不能穷尽其他 head、同名分支 PR、手动操作或服务端取消，也不能从错开的结束时点推断 actor。原取消与失败记录完整保留，不关闭任何 CI 门禁。

本次没有修改工作流或源码，没有 dispatch、rerun、cancel、ref 变更或原生执行。完整来源、93 文件身份、调用图和现存 snapshot 29 窗口见 static-review.json 与 fixed-workflow-projection.json。
