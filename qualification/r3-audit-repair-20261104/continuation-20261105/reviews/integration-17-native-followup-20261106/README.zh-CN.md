# Source17：一次后续CI观察与原Windows业务库原生资格

## 当前结论

固定head为17c6b903a5d5d470b72035f95bb6e087291d7e04，tree25020dc30888fa3ffa6f6e8d1073d91edded1756，actual merge26cfdcaa70cbd2daecd165137e3b84d2ad1a7284同树，merge父序63652be与17。10:43:30 UTC的一次完整API切点：blocking42201989815仍0 jobs；Supervisor42201989809完整2 jobs均in_progress。10:43:51 UTC取得已完成ordinary business consumers42201989580的完整2 jobs和完整2 artifacts。未重复轮询、未调度/重跑/取消CI，未查私有容量。

## 两个实际checkout分开接受

base-merge job127839242912实际执行26cf（父序636、17），source-head job127839243318实际执行17（父840），两者tree25020相同。完整console/MCP原件、source.json、固定workflow source guard、actual commit/ref/PR/merge共同绑定。两官方ZIP分别3,604,185 B与3,609,526 B，API官方摘要、完整CRC和全部各10成员散列均相等。Windows原console分别保留1,755与1,751个CR。

每个checkout跑原完整hepta-intelligence、hepta-bao-adapter、hepta-codex-adapter库目标，分别78/19/21个Rust用例通过，0失败、0忽略、0过滤；每边118个用例，不是236个不同用例。原4/8/3个必需控制，包括unavailable-storage拒绝控制，都在完整raw test.log出现PASS。每个XML只有1个Bazel包装case，不将3个XML包装case替代118个Rust用例。BUILD保留既有qualification/test dependency replacements，范围为这些原库unit targets，不授予外部producer或真实服务集成接受。

两compact都完整解析64,893条记录，合计129,786条，各包含3个产品tw.exe TestRunner和3个xml.exe生成助手。全部产品实际local、cache_hit=false、exit0、timeout300000ms；XML助手不是重试。逐目标核实际XML助手自己的输入test.log与原件SHA/size完全相等、自己的输出XML与原件SHA/size完全相等；没有把另一个checkout的日志当成本次执行。9个记录输入散列各自精确等于固定Git源LF字节逐LF变CRLF后的散列，记录字节关系，不猜Git配置。13个固定源/完整GET及完整10,804叶Merkle均可离线复核。

原workflow仍120分钟、原prepare-bazel-ci、原run-bazel-ci.sh、原MSVC平台与完整3目标；实际命令无filter，--nocache_test_results及--flaky_test_attempts=1保持。不是对项目原required全链的通过声明；whole_candidate_qualified=false，未新增blocker闭合，也未由此接受B11严格外删、未完成的Supervisor或其它平台。

## 可恢复核验

`python3 verify_packet.py --root <恢复目录>`

只解析固定原文件并用zstd只读解压+Bazel9.3固定proto解析，不执行Rust/Cargo/Bazel/native。最终verification-03实际exit0、空stderr、44,951 B stdout；Git a7825a0ebb2cc330a13df03a4cf83348a65ffb05，SHA25687571d6eff183438d28eec08763634319f1fa79eff322e4756682e1174270abe。保留两次本地verifier开发失败及当时源码：一次未归一化Windows JSON的CRLF，一次未归一化protobuf计数JSON键类型。仅修验证表达式，所有原件未改；这些不是原生产品失败。

40件原件由ORIGINALS-FREEZE锁定。为减少重复传输，完整官方ZIP保留；展开ZIP的20成员由ZIP与逐成员manifest恢复，不重复装入。大input-relationships派生可从完整compact重新生成；已保完整解码器、proto、projection脚本和小投影。最终归档另含开发历史、验证stdout/stderr/执行回执、SUMMARY/README与完整FREEZE。临时artifact下载URL不保留。旧840包和17较早两个切点包永久保持原字节。

## 传输恢复

`python3 restore_verify.py --root <交付目录> --output <不存在的新目录>` 验证全部分片、归档、56成员身份并实际重放上述离线核验，stdout必须与冻结44,951 B原件相等。实际Git对象与每次create/fullGET由registry及登记回执记录；完整XZ仅计算Git身份，实际登记的是ASCII分片。
