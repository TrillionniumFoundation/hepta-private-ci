from pathlib import Path
import sqlite3,hashlib,struct,re,json,tempfile
R=Path(__file__).parent;C=R/'current';root=C/'codex-rs/hepta-memory';s=(root/'src/cognitive_store.rs').read_text()
objects=re.findall(r'\(\s*"([^"]+)",\s*"([^"]+)"\s*,?\s*\)',s[s.index('const REQUIRED_SCHEMA_OBJECTS'):s.index('const REQUIRED_SCHEMA_ORACLE_SHA256')])
expected=re.search(r'const REQUIRED_SCHEMA_ORACLE_SHA256: &str =\s*"([a-f0-9]+)"',s)[1]
def oracle(c):
 h=hashlib.sha256()
 def frame(b):h.update(struct.pack('>Q',len(b)));h.update(b)
 frame(b'hepta:cognitive:required-schema-oracle:v1');frame(struct.pack('>Q',len(objects)))
 for name,typ in sorted(objects):
  row=c.execute('select type,sql from sqlite_master where name=?',(name,)).fetchone()
  if not row or row[0]!=typ:return None
  for part in [name,typ,row[1]]:frame(part.encode())
 return h.hexdigest()
def snapshot(c):return c.execute('select rowid,* from cognitive_operation_destination_terminal order by rowid').fetchall()
def rejected(c,sql,args):
 old=snapshot(c)
 try:c.execute(sql,args)
 except sqlite3.IntegrityError:pass
 else:raise AssertionError('expected refusal: '+sql)
 assert snapshot(c)==old
for rowid in [1, -1, -2, 0, 9223372036854775807]:
 path=Path(tempfile.mkdtemp())/'proof.sqlite';c=sqlite3.connect(path,isolation_level=None)
 for p in sorted(root.joinpath('migrations').glob('*.sql')):
  if not p.name.startswith('0017'):c.executescript(p.read_text())
 c.execute('pragma recursive_triggers=off')
 row=('dest','original','a'*64,'applied','proof',1)
 c.execute('insert into cognitive_operation_destination_terminal(rowid,destination_id,operation_id,semantic_sha256,disposition,evidence,recorded_at_unix_ms) values(?,?,?,?,?,?,?)',(rowid,*row))
 before=snapshot(c);c.executescript((root/'migrations/0017_kernel_operation_destination_terminal_insert_guard.sql').read_text());assert snapshot(c)==before;assert oracle(c)==expected
 rejected(c,'insert or replace into cognitive_operation_destination_terminal values(?,?,?,?,?,?)',row)
 rejected(c,'insert or replace into cognitive_operation_destination_terminal values(?,?,?,?,?,?)',row[:3]+('not_applied','changed',2))
 rejected(c,'insert or replace into cognitive_operation_destination_terminal(rowid,destination_id,operation_id,semantic_sha256,disposition,evidence,recorded_at_unix_ms) values(?,?,?,?,?,?,?)',(rowid,'dest','different','b'*64,'not_applied','rowid bypass',3))
 rejected(c,"update cognitive_operation_destination_terminal set disposition='not_applied'",())
 rejected(c,'delete from cognitive_operation_destination_terminal',())
 insert='insert into cognitive_operation_destination_terminal values(?,?,?,?,?,?)';fresh=('dest','fresh','c'*64,'applied','new proof',4)
 if rowid==-1:rejected(c,insert,fresh) # documented fail-closed manual-rowid edge
 else:
  c.execute(insert,fresh)
  if rowid == -2:
   # SQLite first allocates -1 after a negative-only legacy store. The next
   # ordinary insert conservatively refuses, preserving all existing proofs.
   rejected(c,insert,('dest','after-negative','d'*64,'applied','later proof',5))
 assert c.execute('pragma integrity_check').fetchone()==('ok',);assert not c.execute('pragma foreign_key_check').fetchall()
 c.close();c=sqlite3.connect(path,isolation_level=None);assert oracle(c)==expected
 c.execute('drop trigger cognitive_operation_destination_terminal_no_replace');c.close();c=sqlite3.connect(path,isolation_level=None);assert oracle(c) is None
 c.execute('create trigger cognitive_operation_destination_terminal_no_replace before insert on cognitive_operation_destination_terminal begin select 1; end');c.close();c=sqlite3.connect(path,isolation_level=None);assert oracle(c)!=expected;c.close()
print('PASS: actual16->17 schema upgrade, seeded ±rowid proofs preserved; exact/changed/rowid REPLACE blocked with recursive_triggers OFF; UPDATE/DELETE blocked; supported normal insert; integrity/FK; dropped/modified trigger rejected on reopened SQLite schema')
print('Documented: legacy/manual negative rowids preserve evidence but can reach the -1 sentinel and conservatively reject later automatic-rowid inserts; standard owner never assigns rowid.')
print('Schema oracle',expected,'objects',len(objects),'SQLite',sqlite3.sqlite_version)
