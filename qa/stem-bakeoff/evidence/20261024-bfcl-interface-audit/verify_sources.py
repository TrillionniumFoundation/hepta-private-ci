"""Verify pinned source bytes and statically list methods; never import upstream."""
import ast,json,hashlib
from pathlib import Path
P=Path(__file__).resolve().parent;out={};verified=[]
for r in json.loads((P/'extra-source-manifest.json').read_text()):
 f=P/'input'/Path(r['path']).name;b=f.read_bytes()
 assert len(b)==r['bytes']
 assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==r['git_blob_sha']
 out[f.name]=[n.name for n in ast.walk(ast.parse(b)) if isinstance(n,ast.FunctionDef)]
 verified.append(r|{'sha256':hashlib.sha256(b).hexdigest()})
(P/'source-methods.json').write_text(json.dumps(out,indent=2));(P/'verified-source-manifest.json').write_text(json.dumps(verified,indent=2))
print('Verified three original source files via byte hash and AST only.')
