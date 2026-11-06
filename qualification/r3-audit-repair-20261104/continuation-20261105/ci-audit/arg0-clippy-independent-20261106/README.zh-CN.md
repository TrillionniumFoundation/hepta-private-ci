# arg0 两处 clippy 修复：完整源码独审与实际发布包

独审仅接受两个测试/fixture 文件的错误传播改动：Refuse 分支的 expect_err 改为 let Err / bail，OwnedChild 等待中的 as_mut().expect 改为 ok_or_else / ?。两个意外状态仍为失败，原 panic 改为 Result 错误；所有其它字节、原三测试、物理断言、spawn 参数、环境、10 秒等待、poll 与 Drop 不变。

固定基线为 67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed / tree3982ba56dc5a3f1da0c1de7ea57992f88125c359。完整10,582叶/1,571目录重建后仅2叶变化，10,580叶不变，候选树 e60df9b57046df73cc1af53d8773cff48eafd311。两实际新blob为6fbb88e17c1da7d9533efe6f40eae77e60c3b085和1947350263edd252723d88c8179f8fe7a3a018aa；fresh full GET与候选原字节相等。正反 git apply 与精确两替换逆向证明完整通过。

正式独审实际对象 f77d29800fa1f5fd9e84bb327da092015c3a5013 已由根采用。PR #4923 为Draft，实际head3c9e2bba4e7e84616509d6320a9ae013a274532c、parent67、merge65e1ec7164063b139db291562dd6093c3008b403，同e60树、parents[67,3c9]。publication目录保留根16组完整工具回执与独立发布核验。PR created 与fullGET正文全等；根回执未单独保留 intended body 参数，故不冒称独立比对了未保存的参数。

本包完整保留8件作者冻结源码/完整树/验证材料、固定基线树、独立full GET、源审、正反patch、发布原件、初期工具读取假设失败及更正。两个便携验证器都只做源与API身份核对，不执行Rust/cargo/真实fixture。

恢复后执行 `python3 verify_independent.py --root <恢复的root目录>` 和 `python3 publication/verify_publication.py --root <恢复的root目录>`。原验证输出分别3,535 B与2,116 B；异地重放全字节一致。源审不授予GNU clippy、fmt、Linux fixture或其它CI通过资格，自动CI结果由根另行保存，不混入本静态发布包。
