#!/usr/bin/env python3
"""Freeze exact diagnostic artifacts and API/log tool returns for offline inspection."""
from pathlib import Path
import base64, hashlib, json, shutil, zipfile

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'diagnostic-terminal-0410'
DST = ROOT / 'diagnostic-terminal-delivery'
DST.mkdir(exist_ok=True)

def ident(b):
    return dict(bytes=len(b), git_blob=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(), sha256=hashlib.sha256(b).hexdigest())

def write(name, value):
    (DST/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')

names = ['API-CUT.json', 'b21.artifacts.tool-return.original.json', 'b21.job.original.log',
    'b21.original.zip', 'b21_jobs.tool-return.original.json',
    'b23.artifacts.tool-return.original.json', 'b23.job.original.log', 'b23.original.zip',
    'b23_compact.original.zip', 'b23_jobs.tool-return.original.json',
    'main_blocking_jobs.tool-return.original.json', 'main_runs.tool-return.original.json']
assert {p.name for p in SRC.iterdir() if p.is_file()} == set(names)
nested=[]
for name in ['b21.original.zip','b23.original.zip','b23_compact.original.zip']:
    with zipfile.ZipFile(SRC/name) as z:
        assert z.testzip() is None
        entries=[]
        for info in z.infolist():
            assert not info.is_dir()
            path=Path(info.filename)
            assert not path.is_absolute() and '..' not in path.parts
            entries.append(dict(path=info.filename, crc32=info.CRC, **ident(z.read(info))))
        assert len({x['path'] for x in entries}) == len(entries)
        nested.append(dict(path=name, **ident((SRC/name).read_bytes()), members=entries))
write('nested-original-zip-manifest.json', {'schema':'exact-original-zip-member-identities-v1', 'archives':nested})
payload = [(n,SRC/n) for n in names] + [('nested-original-zip-manifest.json',DST/'nested-original-zip-manifest.json')]
manifest={'schema':'diagnostic-terminal-exact-payload-manifest-v1', 'files':[dict(path=n,**ident(p.read_bytes())) for n,p in payload]}
write('manifest.json',manifest)
with zipfile.ZipFile(DST/'snapshot.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for name,p in payload:
        info=zipfile.ZipInfo(name,(2026,11,6,4,10,0));info.external_attr=0o100644<<16
        info.compress_type=zipfile.ZIP_STORED if name.endswith('.zip') else zipfile.ZIP_DEFLATED
        z.writestr(info,p.read_bytes())
raw=(DST/'snapshot.zip').read_bytes();encoded=base64.b64encode(raw)
parts=[]
for offset in range(0,len(encoded),400000):
    name=f'snapshot.zip.b64.part{len(parts)+1:03d}'
    data=encoded[offset:offset+400000];(DST/name).write_bytes(data)
    parts.append(dict(path=name,**ident(data)))
write('archive.json',{'schema':'base64-parted-exact-zip-v1','archive':ident(raw),'parts':parts,'encoding':'base64','part_bytes_max':400000,'payload_manifest':ident((DST/'manifest.json').read_bytes())})
(DST/'README.zh-CN.md').write_text('''# B21 / B23 原始诊断终态证据

本包保留两次自动诊断作业的完整日志、四份 04:10 UTC API 返回、两份 artifact 元数据，以及三份下载原始 ZIP。API 返回是连接器实际返回；日志是连接器解码后的完整文本，不声称 HTTP 传输字节。原始 ZIP 按官方 artifact SHA-256、长度、逐成员 CRC 和完整字节验证，未重打包替代原 ZIP。

- B21：run 42154464909 / job 127685180579，原 full-context Bazel 失败，PTY 原 31 例为 30 通过 / 1 失败。失败发生于 portable backend 的 2 秒原期限，尚未进入后续 preserved-fds 迭代。原 collector 同样失败，保留 1 个 Fetch 重复事件与 131 个 XML 缺件。
- B23：run 42155150876 / job 127687422035，原 AppServer target 8 分片为 307 通过 / 0 失败 / 1 忽略，原 Bazel exit 0。完整诊断 job 仍为失败，原因是 collector 的 2 个 Fetch 重复事件与 8 个 XML 缺件。产品 scope 的独立关闭判定另见 B23 正式独立审阅；本包不会把收集失败改成成功。
- 主修复分支：这里只含 04:10 的 19-run 总表和 blocking run 的 36-job 返回；其余 18-run 完整 job 及 GNU 等六份 artifact 在独立 main92 证据包中。这里只作部分切面，不冒充独立完整 92-job census。

`python verify_packet.py` 将重构 transport ZIP，验证完整 manifest、全部三份原 ZIP 的成员与官方摘要，核对原始结果，并验证 B21 源码归档的全部 Git 叶和模式。可用 `--extract /目标目录` 写出原始 payload；其中三份原 ZIP 保持原字节。不会运行产品、网络、CI 或修补任何原始 XML。完整 derived BEP 保留原来的 credential-sanitized / opaque-payload-omitted 标识，不声称 raw BEP。

源身份：B21 ebd31e2b3e38ff72cedaa7b57bee60c1c102da27 / tree 46fca3e684217066c260dc10d0dc319a33e0a93c；B23 checkout b3bc3dcf5684568dd03f3667ecd2307b8577a0a6 / tree a6831e2607e718f1343b788e5b8062a171d50a71。两者剥除各自唯一诊断 workflow 后的 10,582 产品叶投影均为 3982ba56dc5a3f1da0c1de7ea57992f88125c359。

文件中的未物化 XML、原作业失败和 B21 原测试失败均完整保留。包的 offline 验证成功只证明证据运输与解读一致，不是新产品测试通过。
''')
print(json.dumps({'archive':ident(raw),'parts':len(parts),'nested_members':sum(len(x['members']) for x in nested),'payload_members':len(payload)},indent=2))
