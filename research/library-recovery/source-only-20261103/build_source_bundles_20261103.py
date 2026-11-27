from pathlib import Path, PurePosixPath
import zipfile, tarfile, io, gzip, json, hashlib, re, os

OUT=Path('/mnt/data/source-only-recovery-20261103');OUT.mkdir(parents=True,exist_ok=True)
BASE=Path('/mnt/data/priority-more-originals')
ARCHIVES={
  'hcsn-r2':'HCSN_Next_Blockers_R2_20261101_source_evidence.zip',
  'hcsn-addressed':'HCSN_Addressed_Followup_20261101_source_evidence.zip',
  'hcsn-v9':'HCSN_V9_20261101_source_evidence.zip',
  'razr-r12':'RAZR_SLIDE_R12_reviewable_delivery.zip',
}
CODE_EXT={'.py','.rs','.c','.h','.cpp','.hpp','.cc','.sh','.toml','.yml','.yaml','.tex','.bib','.cls','.bst','.cfg','.mk','.md','.txt'}
CONFIG_RX=re.compile(r'(manifest|source[_-]?identity|input[_-]?manifest|external[_-]?depend|reproduc|configuration|environment|contract|build[_-]?receipt|provenance|requirements|source[_-]?index|run[_-]?config|artifact[_-]?index)',re.I)
EXCLUDE_PARTS={'__pycache__','.git','node_modules','target','build','.venv','venv'}
SECRET_RX=[re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),re.compile(r'\bghp_[a-zA-Z0-9]{30,}\b'),re.compile(r'\bgithub_pat_[a-zA-Z0-9_]{30,}\b'),re.compile(r'\bAKIA[A-Z0-9]{16}\b'),re.compile(r'\bsk-proj-[a-zA-Z0-9_-]{20,}\b')]
for slug,fn in ARCHIVES.items():
 path=BASE/fn
 original_hash=hashlib.sha256(path.read_bytes()).hexdigest()
 included=[]; omitted=[]; flagged=[]; paths=set()
 with zipfile.ZipFile(path) as z:
  for f in sorted((f for f in z.infolist() if not f.is_dir()),key=lambda f:f.filename):
   p=PurePosixPath(f.filename)
   if p.is_absolute() or '..' in p.parts or '\\' in f.filename or not p.parts:
    flagged.append({'path':f.filename,'reason':'unsafe path'});continue
   ext=p.suffix.lower();lower=f.filename.lower()
   if any(x in EXCLUDE_PARTS for x in p.parts):continue
   if re.search(r'(?i)(secret|private[_-]?key|credentials|\.env|token[_-]?value)',str(p)):
    flagged.append({'path':f.filename,'reason':'potential secret filename'});continue
   if f.file_size>500_000: continue
   is_code=ext in CODE_EXT
   is_meta=ext=='.json' and bool(CONFIG_RX.search(str(p))) and not re.search(r'/((?:results?|receipt[s]?|history_results|inputs/av_features|originals|outputs|workspaces?|cache|metrics|events|tracks|logs)/)',lower)
   if not (is_code or is_meta): continue
   if lower.startswith('upstream_') and f.file_size>100_000: continue
   data=z.read(f)
   try:body=data.decode('utf-8')
   except UnicodeDecodeError:flagged.append({'path':f.filename,'reason':'not UTF8'});continue
   if any(rx.search(body) for rx in SECRET_RX):flagged.append({'path':f.filename,'reason':'potential credential pattern'});continue
   if str(p) in paths:flagged.append({'path':f.filename,'reason':'duplicate normalized path'});continue
   paths.add(str(p))
   included.append((str(p),data,hashlib.sha256(data).hexdigest(), 'source' if is_code else 'manifest'))
 manifest={'schema':'hepta.source-only.bundle.v1','source_archive':fn,'source_archive_bytes':path.stat().st_size,'source_archive_sha256':original_hash,'scope':'code, documentation, build, selected configuration and reproducibility metadata only; no raw datasets, checkpoints, logs, traces, CAD or experiments outputs','selection_rule':'documented in build_source_bundles_20261103.py','selected_count':len(included),'selected_bytes':sum(len(t[1]) for t in included),'members':[{'path':x[0],'bytes':len(x[1]),'sha256':x[2],'classification':x[3]} for x in included], 'excluded_suspected_secrets':flagged, 'independent_replay_proven':False}
 readme=f'''# {slug}: source-only recovery\n\nOriginal Library artifact: `{fn}`\n\nOriginal ZIP SHA-256: `{original_hash}`\n\nSource-only bundle includes {len(included)} candidate code, docs and selected configuration files. It does NOT contain raw evidence datasets/checkpoints/logs and cannot, by itself, prove the full experiments can be independently replayed.\n\n## Verify\n\nRun `sha256sum {slug}-source-only.tar.gz` and compare with `bundle_sha256` in the sidecar JSON. Then extract into a new empty directory: `tar -xzf {slug}-source-only.tar.gz -C <empty-dir>` and verify each file against `SOURCE_MANIFEST.json`.\n\n## Scope\n\nHistorical results must not be claimed reproducible solely because source is recovered. Dependencies, asset acquisition, random seeds and environment requirements are described in the preserved scripts/READMEs where available. Files flagged as possible secrets were excluded pending manual inspection.\n'''
 manifest_bytes=(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
 readme_bytes=readme.encode()
 items=[(x[0],x[1]) for x in included]+[('SOURCE_MANIFEST.json',manifest_bytes),('README_SOURCE_ONLY.md',readme_bytes)]
 buf=io.BytesIO()
 with gzip.GzipFile(filename='',mode='wb',fileobj=buf,mtime=0,compresslevel=9) as gz:
  with tarfile.open(fileobj=gz,mode='w|',format=tarfile.PAX_FORMAT) as tar:
   for name,data in sorted(items,key=lambda x:x[0]):
    ti=tarfile.TarInfo(name);ti.size=len(data);ti.mtime=0;ti.mode=0o644;ti.uid=ti.gid=0;ti.uname=ti.gname='';tar.addfile(ti,io.BytesIO(data))
 blob=buf.getvalue()
 (OUT/f'{slug}-source-only.tar.gz').write_bytes(blob)
 manifest['bundle_sha256']=hashlib.sha256(blob).hexdigest()
 manifest['bundle_bytes']=len(blob)
 (OUT/f'{slug}-SOURCE_INDEX.json').write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
 import base64
 (OUT/f'{slug}-source-only.tar.gz.b64.txt').write_text(base64.b64encode(blob).decode()+'\n')
 print(json.dumps({'slug':slug,'source_count':len(included),'source_bytes':manifest['selected_bytes'],'bundle_bytes':len(blob),'bundle_sha256':manifest['bundle_sha256'],'orig_sha256':original_hash,'flagged':len(flagged),'flagged_examples':flagged[:5]},ensure_ascii=False))
