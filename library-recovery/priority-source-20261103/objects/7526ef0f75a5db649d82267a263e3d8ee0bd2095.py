"""Derive the current public #996 schema oracle without changing inventory or SQL."""
import hashlib,json,re,sqlite3,subprocess,sys
from pathlib import Path
REPO=Path('/workspace/shared/operations-host-fairness')
REF='b5b31f82d9ef7f3717df4a88d486a434b18cc9d6'
SOURCE='codex-rs/hepta-memory/src/cognitive_store.rs'
MIGRATIONS='codex-rs/hepta-memory/migrations'
def git(*args):return subprocess.check_output(['git',*args],cwd=REPO)
def source(ref):return git('show',f'{ref}:{SOURCE}').decode()
def inventory(text):
    block=text.split('const REQUIRED_SCHEMA_OBJECTS:',1)[1].split('];',1)[0]
    pairs=re.findall(r'\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,?\s*\)',block)
    assert len(pairs)==len(set(name for name,_ in pairs))
    residue=re.sub(r'\(\s*"[^"]+"\s*,\s*"[^"]+"\s*,?\s*\)','',block)
    assert not re.search(r'"',residue),residue
    return pairs

def expected(text):return re.search(r'const REQUIRED_SCHEMA_ORACLE_SHA256: &str =\s*"([0-9a-f]{64})"',text).group(1)
def database(ref):
    db=sqlite3.connect(':memory:')
    files=git('ls-tree','-r','--name-only',ref,MIGRATIONS).decode().splitlines()
    hashes={}
    for name in sorted(files):
        data=git('show',f'{ref}:{name}');hashes[name]=hashlib.sha256(data).hexdigest();db.executescript(data.decode())
    return db,hashes

def derive(db,pairs):
    records=[]
    for name,kind in sorted(pairs):
        row=db.execute('SELECT type,sql FROM sqlite_schema WHERE name=?',(name,)).fetchone()
        if row is None or row[0]!=kind or not row[1]:raise ValueError(name)
        records.append((name,*row))
    h=hashlib.sha256()
    def part(data):h.update(len(data).to_bytes(8,'big'));h.update(data)
    part(b'hepta:cognitive:required-schema-oracle:v1');part(len(records).to_bytes(8,'big'))
    for record in records:
        for field in record:part(field.encode())
    return h.hexdigest(),records

oldref=git('rev-parse','0b145f42b0^').decode().strip()
oldsrc=source(oldref);newsrc=source(REF)
oldpairs=inventory(oldsrc);newpairs=inventory(newsrc)
old,oldhashes=database(oldref);new,newhashes=database(REF)
old_digest,oldrecords=derive(old,oldpairs);new_digest,newrecords=derive(new,newpairs)
assert old_digest==expected(oldsrc),'framing/history control failed'
added=set(newpairs)-set(oldpairs)
assert len(added)==4 and not(set(oldpairs)-set(newpairs))
assert all(name.startswith('cognitive_operation_destination_terminal') for name,_ in added)
assert oldhashes.items()<=newhashes.items(),'previous migration bytes changed'
assert dict((n,(k,s)) for n,k,s in oldrecords).items()<=dict((n,(k,s)) for n,k,s in newrecords).items(),'existing required schema changed'
assert new_digest!=expected(newsrc),'baseline failure unexpectedly absent'
# Real SQL constraints on the four intended newly inventoried definitions.
def insert(disposition='applied',semantic='a'*64,evidence='proof',time=1,operation='positive'):
    new.execute('INSERT INTO cognitive_operation_destination_terminal VALUES (?,?,?,?,?,?)',('destination',operation,semantic,disposition,evidence,time))
insert()
for kwargs in ({},{'disposition':'ack_only','operation':'bad1'},{'semantic':'z'*64,'operation':'bad2'},{'evidence':'','operation':'bad3'},{'evidence':'x'*4097,'operation':'bad4'},{'time':0,'operation':'bad5'}):
    try:insert(**kwargs)
    except sqlite3.IntegrityError:pass
    else:raise AssertionError(('invalid proof accepted',kwargs))
for statement in ("UPDATE cognitive_operation_destination_terminal SET evidence='changed'",'DELETE FROM cognitive_operation_destination_terminal'):
    try:new.execute(statement)
    except sqlite3.IntegrityError:pass
    else:raise AssertionError('immutability trigger missing')
# Missing or behaviorally weakened definitions still fail the unchanged guard.
negative=[]
for name,kind in sorted(added):
    db,_=database(REF);db.execute(f'DROP {kind} {name}')
    try:derive(db,newpairs)
    except ValueError:negative.append('missing:'+name)
    else:raise AssertionError('missing object accepted')
for name in ['cognitive_operation_destination_terminal_no_update','cognitive_operation_destination_terminal_no_delete','cognitive_local_events_no_delete']:
    db,_=database(REF);db.execute(f'DROP TRIGGER {name}')
    action='UPDATE' if name.endswith('no_update') else 'DELETE'
    table='cognitive_local_events' if name.startswith('cognitive_local_events') else 'cognitive_operation_destination_terminal'
    db.execute(f'CREATE TRIGGER {name} BEFORE {action} ON {table} BEGIN SELECT 1; END')
    changed,_=derive(db,newpairs);assert changed!=new_digest;negative.append('modified:'+name)
result={'baseline':REF,'sqlite_version':sqlite3.sqlite_version,'prior_ref':oldref,'prior_objects':len(oldpairs),'prior_expected':expected(oldsrc),'prior_derived':old_digest,'current_objects':len(newpairs),'current_expected':expected(newsrc),'current_derived':new_digest,'added_objects':sorted(added),'preserved_prior_migration_hashes':oldhashes,'current_migration_hashes':newhashes,'negative_controls':negative,'constraint_controls_passed':8,'scope':'Expected-digest correction only. No migration, schema-inventory, trigger, verifier or qualification-policy change.'}
print(json.dumps(result,indent=2))
