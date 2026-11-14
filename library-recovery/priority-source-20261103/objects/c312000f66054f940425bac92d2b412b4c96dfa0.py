from pathlib import Path
import sqlite3,re,hashlib,struct,difflib,json
R=Path(__file__).parent;C=R/'current';B=R/'base'
sql='''-- Preserve migration 0016 and existing terminal evidence. SQLite REPLACE
-- bypasses DELETE triggers when recursive_triggers is OFF. Guard both logical
-- identity and the implicit rowid conflict target before replacement begins.
-- Official writers never assign rowid. A legacy explicit rowid=-1 causes
-- automatic-rowid inserts to fail closed because SQLite uses -1 before assign.
CREATE TRIGGER cognitive_operation_destination_terminal_no_replace
BEFORE INSERT ON cognitive_operation_destination_terminal
WHEN EXISTS (
    SELECT 1 FROM cognitive_operation_destination_terminal
    WHERE (destination_id = NEW.destination_id AND operation_id = NEW.operation_id)
       OR rowid = NEW.rowid
)
BEGIN
    SELECT RAISE(ABORT, 'operation destination terminal proof is immutable');
END;
'''
mp='codex-rs/hepta-memory/migrations/0017_kernel_operation_destination_terminal_insert_guard.sql'
p='codex-rs/hepta-memory/src/cognitive_store.rs'
t='codex-rs/hepta-memory/src/production_cognitive_source_target_tests.rs'
n='codex-rs/hepta-memory/src/production_destination_proof_storage_tests.rs'
before={mp:'',p:(C/p).read_text(),t:(C/t).read_text(),n:''};(C/mp).write_text(sql)
s=before[p];name='cognitive_operation_destination_terminal_no_replace'
objects=re.findall(r'\(\s*"([^"]+)",\s*"([^"]+)"\s*,?\s*\)',s[s.index('const REQUIRED_SCHEMA_OBJECTS'):s.index('const REQUIRED_SCHEMA_ORACLE_SHA256')])
c=sqlite3.connect(':memory:')
for m in sorted((C/'codex-rs/hepta-memory/migrations').glob('*.sql')):c.executescript(m.read_text())
def digest(items):
 h=hashlib.sha256()
 def frame(x):h.update(struct.pack('>Q',len(x)));h.update(x)
 frame(b'hepta:cognitive:required-schema-oracle:v1');frame(struct.pack('>Q',len(items)))
 for nm,typ in sorted(items):
  actual,definition=c.execute('select type,sql from sqlite_master where name=?',(nm,)).fetchone();assert actual==typ
  for x in [nm,typ,definition]:frame(x.encode())
 return h.hexdigest()
old=digest(objects);historical=digest([x for x in objects if not x[0].startswith('cognitive_operation_destination_terminal')]);assert historical=='046f23bab5d4c779735c762159c79e61cfe3a6a8a35e18ff8ec4f40e5c4e2be2'
assert old=='2d85becf3c319bd9816dabf00219ee2a5c61892cb2d1a20cb176ff201f416ca5'
expected=re.search(r'const REQUIRED_SCHEMA_ORACLE_SHA256: &str =\s*"([a-f0-9]+)"',s)[1];assert expected=='f76aecab2b3d5a969ca1ac58b6543b64549a437d49ab7c6eeb7d246dd6ab1a66'
new=digest(objects+[(name,'trigger')]);s=s.replace('    ("cognitive_operation_destination_terminal", "table"),','    ("cognitive_operation_destination_terminal", "table"),\n    (\n        "'+name+'",\n        "trigger",\n    ),');s=s.replace(expected,new);(C/p).write_text(s)
(C/t).write_text(before[t].replace('use super::*;\n','use super::*;\n\n#[path = "production_destination_proof_storage_tests.rs"]\nmod proof_storage_tests;\n',1));(C/n).write_text((R/'proof_tests.txt').read_text())
text=''
for path,oldtext in before.items():text+=''.join(difflib.unified_diff(oldtext.splitlines(True),(C/path).read_text().splitlines(True),fromfile='a/'+path if oldtext else '/dev/null',tofile='b/'+path))
(R/'patches/04-proof-immutability.patch').write_text(text)
(R/'oracle_evidence.json').write_text(json.dumps({'ref':'b5b31f82d9ef7f3717df4a88d486a434b18cc9d6','historical128':historical,'baseline132_actual':old,'baseline132_declared':expected,'repaired133':new},indent=2)+'\n')
print('Repaired complete schema oracle:',new)
