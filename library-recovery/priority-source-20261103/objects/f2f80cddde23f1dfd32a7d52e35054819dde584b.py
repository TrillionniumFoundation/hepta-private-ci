from pathlib import Path
import difflib,hashlib,json,subprocess
r=Path(__file__).resolve().parent
meta=json.loads((r/'BASELINE.json').read_text())
for rec in meta['files']:
 for lane in ['cursor','transport']:
  base=r/(lane+'-base')/rec['path']
  if not base.exists():continue
  actual=subprocess.check_output(['git','hash-object',str(base)],text=True).strip()
  if actual != rec['sha']:
   b=base.read_bytes();assert b.endswith(b'\n\n');base.write_bytes(b[:-1])
  assert subprocess.check_output(['git','hash-object',str(base)],text=True).strip()==rec['sha'],(lane,rec)
for lane in ['cursor','transport']:
 base=r/(lane+'-base');candidate=r/(lane+'-candidate');out=''
 for p in sorted(candidate.rglob('*')):
  if not p.is_file():continue
  f=p.relative_to(candidate);old=base/f
  if old.exists() and old.read_bytes()==p.read_bytes():continue
  out+=''.join(difflib.unified_diff(old.read_text().splitlines(True) if old.exists() else [],p.read_text().splitlines(True),fromfile='a/'+f.as_posix() if old.exists() else '/dev/null',tofile='b/'+f.as_posix()))
 path=r/f'taskflow-new-{lane}.patch';path.write_text(out)
 print(path.name,hashlib.sha256(path.read_bytes()).hexdigest())
 subprocess.run(['git','apply','--check','--whitespace=error',str(path)],cwd=base,check=True)
 subprocess.run(['git','apply','--reverse','--check','--whitespace=error',str(path)],cwd=candidate,check=True)
 print('PASS forward/reverse/whitespace',lane)
