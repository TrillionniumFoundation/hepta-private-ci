# Source17两个普通自动CI切点：可恢复交付

完整归档保留21成员，包含早切9原件、根后切目录全部5原件及离线验证材料。两个head列表各自完整18条，不能合并为36条：早切10:29:19Z为12Q/3pending/2skip/1API-success，后切10:31:19Z为11Q/3pending/2skip/1API-success/1running。blocking 42201989815在10:30:14Z和10:32:44Z均0 jobs；whole_candidate_qualified=false，未从API成功推断case/平台/整候选通过。实际job checkout未由日志确认，不转授旧840。

`python3 restore_verify.py --root <此交付目录> --output <不存在的新目录>`

验证完整分片、XZ/CRC64归档、21成员字节/Git/SHA256并运行离线verify_packet.py，期望4,658 B stdout ab2d3d18b4ad6344f7fc33dd7c41d0db952881c4逐字相等。只解析已固定文件，不运行原生/网络/CI/B16，不写ref。根原保存transport错误也完整保留，不当作native失败。

registry schema为hepta-evidence-packet-actual-registry-v1；files[]给出path/mode/type/sha/bytes/sha256。tree-elements.actual.json是可直接交Git create_tree的tree_elements数组，包含全部payload、登记回执和registry自身；registry-self.actual.json保存registry实际创建与完整GET回执，不自我递归加入。完整XZ自身Git为计算身份，实际登记使用ASCII分片。
