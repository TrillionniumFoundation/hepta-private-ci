# 固定共同源码整合与原失败保留

普通正向采用 0；完整 NoUpdate/回退 0；真正 daemon/Root 冷重启 0。

源码实际 Git 链：c6a61dfb + 62442068 → e83f7eb8（base 7832eef1）；加 c2494d6d → a57d78ae（base 5d6e2f24）；加 7f7b5946 → 1da47b9b（base 7832eef1）；单文件 Model fixture libc 修复 → 627dd30b；原 H just fmt → dd4b6c17。各真正 merge 的冲突处保留两侧新增内容，只合并重复的同一个测试导出；516 boundary IDs 和378条完整 protected records 没有按路径去重。

627dd30bd9523755c93e1ed8bbbf0b359dd7bea9 / b3b9db8009f1f29e25ceda00cbc8c09acebcca1c：完整326 source methods真实运行失败，unittest footer为 failures=27, errors=195（含subtests，涉及24个方法ID，不能用222当方法数）。16 Observer parser通过；caller self-test退出0。前后固定SHA/tree且clean。原742838B失败日志完整保留。没有为此候选运行完整 caller proof 或宣称native通过。

dd4b6c17344986a3a9379e372bf19d282f812a30 / 935622f0a83d2991d7630324db7022612d556df9：单父627，H formatter实际39文件，全部postimage字节数与SHA256和Git一致；fmt/diff/commit/push全部退出0，Python AST及Cargo manifest/lock不变。格式化不是源码闭包或原生测试通过。静态库存为6699 Rust文件、158 native cases/35 groups、326 source methods。

原4ceb 150-case请求在helper Cargo编译阶段失败：生产resident authority两处rustix未声明导致E0433，Cargo退出101，实际native测试数0。这里保留原helper manifest、完整stderr、原driver日志和两层result；修复c6a61保持真实UID/pidfd观察，使用已有libc，不增加依赖。c6a61单scope10项通过，原H格式检查未改源码；最近原准备result为native-running，尚无该150case终态。不能把不同SHA的结果转给dd4。

原4ceb full caller proof最近原result仍为running；这里的文件是一次原文件读取，不是实时进程状态或成功。原3d115 Proposal formatter最终result也在本包恢复并核对。captures保存实际工具读回包，各文件按返回byte count/SHA256核验；不是重新编造的日志或指标。

原Cargo JSONL在原host仍有文件身份：1020507B，SHA256 065425c1fad49ce1a6052e884c08bec7c1ccb668c35cd492ba275c656b666b99；本次尚未复制该完整JSONL字节，不能把清单当作已打包文件。

待完成：新read-only/HEAD闭包与旧S/C guard同步；E、Candidate/Model/Root同操作实际读回收敛；普通host迟绑定与实际原授权装配；同一最终源上的真实独立B及非空保留面板、采用/NoUpdate、新会话C和真正冷重启。既有fixture keys/metrics/Ineligible/工厂安装不计验收。
