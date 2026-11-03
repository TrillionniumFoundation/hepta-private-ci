from pathlib import Path
import hashlib,json,shutil,subprocess,sqlite3,tempfile
R=Path(__file__).parent
checked = set()
for name in ['source_manifest.json','docs_source_manifest.json','protocol_sources_manifest.json','lane_a_inputs_manifest.json']:
 if not (R/name).exists():continue
 manifest=json.loads((R/name).read_text())
 for f in manifest['files']:
  b=(R/'base'/f['path']).read_bytes()
  assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==f['blob']
  checked.add(f['path'])
A=R/'apply-check'
if A.exists():shutil.rmtree(A)
shutil.copytree(R/'base',A,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
for p in sorted((R/'patches').glob('*.patch')):
 subprocess.run(['git','apply','--check',str(p)],cwd=A,check=True)
 subprocess.run(['git','apply',str(p)],cwd=A,check=True)
for p in (R/'current').rglob('*'):
 if p.is_file() and '__pycache__' not in p.parts:assert p.read_bytes()==(A/p.relative_to(R/'current')).read_bytes(),p
# Deterministic WAL schedule, old false-conflict and repaired snapshot.
p=Path(tempfile.mkdtemp())/'proof.sqlite';a=sqlite3.connect(p,isolation_level=None);b=sqlite3.connect(p,isolation_level=None)
a.execute('pragma journal_mode=wal');a.execute('create table source(id text primary key,content text)')
assert a.execute("select count(*) from source where id='old' and content='exact'").fetchone()[0]==0
b.execute("insert into source values('old','exact')")
assert a.execute("select count(*) from source where id='old'").fetchone()[0]==1
a.execute('begin');assert a.execute("select count(*) from source where id='new' and content='exact'").fetchone()[0]==0
b.execute("insert into source values('new','exact')")
assert a.execute("select count(*) from source where id='new'").fetchone()[0]==0
a.execute('commit');assert a.execute("select count(*) from source where id='new'").fetchone()[0]==1
c=sqlite3.connect(':memory:');c.execute('create table o(id text)');c.executemany('insert into o values(?)',[('A',),('B',),('C',)])
q='select id from o order by case when ? is null or id > ? then 0 else 1 end,id limit 3';cursor=None
for i in range(3):
 attempted=[]
 for row in c.execute(q,(cursor,cursor)).fetchall():
  cursor=row[0];attempted.append(cursor)
  if cursor=='A':break
 if i:assert attempted==['B','C','A']
print(f'PASS:{len(checked)} exact source blobs, sequential apply, byte-equal source, SQLite snapshot schedule and poisoned-prefix cursor')
print('Native Rust compile/tests/rustfmt/Clippy NOT RUN')
