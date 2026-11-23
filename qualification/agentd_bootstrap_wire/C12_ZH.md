# c12 的单产品文件移植核对

43e5 到 c12 多出两个提交。独立读取两套 Git 树，在四层逐条核对模式、种类和对象 SHA，并用 Git 的规范排序和原始编码重算八个树标识。根节点有 69 条，codex-rs 有 169 条，hepta-agentd 有 40 条，src 有 1,581 条。两棵完整目录树只有一个文件发生变化。[两提交完整比较](https://github.com/TrillionniumFoundation/hepta-private-ci/compare/43e5da1bb81369e4e999adfa8558f5ccb5460eb6...c12ee03f3185d5a13949faca54f066dfd634e509)

| 项目 | 原始物件或结果 |
|---|---|
| 唯一不同文件 | authority_host_learning_resident_transport_tests.rs，12f37a10 → a5e77fc7，属于 resident transport 测试 |
| bootstrap 前像 | 两树均为 270d025b44c5d3f5aed8d3438b7fc6f34ff9dab8 |
| 已单独资格的 bootstrap 后像 | 054075188a68c0b6673c5779108be6556358d6c6 |
| Rust 依赖锁 | 两树的 codex-rs/Cargo.lock 均为 6671b2890140116dde58a29299ad0e29401eb90a |
| 源级保护检查 | 完整 qa/b4-no-bypass 树为 235e8478f00f27f48bd713cbfdd437469f3ad21a。含 166 个条目，其中 160 个 test_*.py |
| 三个测试观察点 | 三份 fixture 的原始 Git blob 均相同。实际重新应用同一观察器后，输出逐字匹配已运行的两个原生作业 |
| c12 上只采用该产品 blob 的预期整树 | e6b66b5eba81dd4b5e41e544ef57326f032e0a5a |

c12-bound-inputs.json 列出 36 条相同物件，包括三个观察器输入、生产 codec、原 V1 与 post-A 生产路径、两个原普通用例、UID0 parent、依赖锁、CALLERS 与保护检查。具名的六个相关原检查覆盖 physical preparation、publication V2、original publication route、post-A publication、post-A original files 和 first publication acceptance。所有其他仓库路径由完整树差异证明覆盖。六类原编码解码条件与错误返回另由原 source closure 和精确源变换单独校验。[原产品资格与 3 个 ZIP](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/aa54069e076c4e0010157e63c0933b29b15e5be7/qualification/agentd_bootstrap_wire)

`python3 c12_verify.py .` 使用压缩的原 Git 树目录，不需要仓库写入，即可复算全部树标识与移植后的预期根树。观察器可用 `python3 verify_observer_overlay.py . /path/to/c12 /path/to/diagnostic/qualification/bootstrap-wire-proof` 复算。这里完成源码/测试夹具的移植核对。原生、严格编译的直接证据属于 43e5 与 2b75。两份 ELF 的数据来自已归档的固定作业。c12 所含 resident 测试差异会影响整个测试 ELF 的来源标识，即使 bootstrap 及其所有观察点字节相同。V2 此次仅有完整的内存 wire 样本，完整实际 post-A 权限链需单独执行。
