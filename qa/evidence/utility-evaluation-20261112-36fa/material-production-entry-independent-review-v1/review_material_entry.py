from pathlib import Path
import hashlib, json, re, tomllib

OUT = Path('/tmp/hepta-36fa-material-production-entry-independent-review-v1')
INV = Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1/SOURCE.final.inventory.exact_recovered.json')
REF = Path('/tmp/hepta-36fa-root-product-e3-proposal-v1/references')
TASKREF = Path('/tmp/hepta-36fa-root-task-loader-references-v1')
V6 = Path('/tmp/hepta-36fa-root-product-composition-v6/after')
SRC = 'codex-rs/hepta-agentd/src/'
LEDGER = 'codex-rs/hepta-learning-ledger/src/'

def pin(b):
    return {'bytes':len(b), 'sha256':hashlib.sha256(b).hexdigest(), 'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}

def put(name, obj):
    b=(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    with (OUT/name).open('xb') as f: f.write(b)
    return {'path':str(OUT/name), **pin(b)}

inventory=json.loads(INV.read_bytes())
rows={r['path']:r for r in inventory['files']}
assert inventory['source']['head']=='b6084394a4a38ab495c16eaba09e879f04a96f8e'
paths={
 'cargo':(REF/'codex-rs/hepta-agentd/Cargo.toml','codex-rs/hepta-agentd/Cargo.toml'),
 'main':(OUT/'references/main.rs',SRC+'main.rs'),
 'browser':(OUT/'references/browser.rs',SRC+'bin/hepta-agentd-browser.rs'),
 'authority_host':(REF/(SRC+'bin/hepta-authority-host.rs'),SRC+'bin/hepta-authority-host.rs'),
 'native_owner_bin':(OUT/'references/native_owner_bin.rs',SRC+'bin/hepta-g2-native-owner.rs'),
 'native_owner_entry':(OUT/'references/native_owner_entry.rs',SRC+'native_g2_entry/owner.rs'),
 'durable':(OUT/'references/durable.rs',LEDGER+'durable.rs'),
 'production':(REF/(LEDGER+'production.rs'),LEDGER+'production.rs'),
 'trust':(REF/(LEDGER+'trust_distribution.rs'),LEDGER+'trust_distribution.rs'),
 'ledger_witness':(Path('/tmp/hepta-36fa-coordinator-final-candidate-graph-v1/overlay')/(LEDGER+'witness.rs'),LEDGER+'witness.rs'),
 'owner':(REF/(SRC+'cell_q24_material_receipt_owner.rs'),SRC+'cell_q24_material_receipt_owner.rs'),
 'binding':(REF/(SRC+'cell_q24_material_receipt_binding.rs'),SRC+'cell_q24_material_receipt_binding.rs'),
 'neuron_witness':(TASKREF/'codex-rs/hepta-neuron/src/witness.rs','codex-rs/hepta-neuron/src/witness.rs'),
}
sources={};texts={}
for role,(local,repo) in paths.items():
    b=local.read_bytes(); p=pin(b); r=rows[repo]
    assert (p['bytes'],p['sha256'],p['git_blob'])==(r['bytes'],r['sha256'],r['working_blob']),(role,p,r)
    sources[role]={'local_path':str(local),'repository_path':repo,**p,'matches_b608_complete_inventory':True}
    texts[role]=b.decode()

git_reads=[]
for role in ['durable','native_owner_bin','native_owner_entry','main','browser']:
    path=OUT/'references'/f'{role}.GET.original.json'; raw=path.read_bytes(); sdk=json.loads(raw)
    assert sdk.get('isError') is False
    assert sdk['structuredContent']['content'].encode()==paths[role][0].read_bytes()
    git_reads.append({'role':role,'original_sdk':str(path),'original_sdk_pin':pin(raw),'content_pin':sources[role],'actual_complete_Git_GET':True,'created_by_this_reviewer':False})

cargo=tomllib.loads(texts['cargo'])
bins=cargo['bin'];assert len(bins)==4
assert {(x['name'],x['path']) for x in bins}=={
 ('codex-hepta-agentd','src/main.rs'),('hepta-agentd-browser','src/bin/hepta-agentd-browser.rs'),
 ('hepta-authority-host','src/bin/hepta-authority-host.rs'),('hepta-g2-native-owner','src/bin/hepta-g2-native-owner.rs')}
entry_roles=['main','browser','authority_host','native_owner_entry']
entry_tokens={x:{needle:texts[x].count(needle) for needle in ['OriginalCellQ24MaterialReceiptOwnersV1','OriginalCellQ24MaterialCommandOwnerV1','LedgerWriter','activate_learning_trust','into_original_root_source_command_owner']} for x in entry_roles}
assert all(n==0 for r in entry_tokens.values() for n in r.values())

def excerpt(role,start,end):
    lines=texts[role].splitlines(keepends=True)
    b=''.join(lines[start-1:end]).encode()
    return {'role':role,'line_start':start,'line_end':end,'utf8':b.decode(),**pin(b)}

headers=[]
for role,names in {'durable':['create','recover'],'ledger_witness':['create','recover','frontier'],'production':['from_durable','from_segmented','freeze_dataset'],'trust':['activate_learning_trust'],'owner':['create','recover','into_evidence_readback_owner','into_command_owner'],'neuron_witness':['open']}.items():
    s=texts[role]
    for name in names:
        ms=list(re.finditer(r'^\s*pub (?:const )?fn '+re.escape(name)+r'(?:<|\()',s,re.M))
        assert len(ms)==1,(role,name,len(ms))
        st=ms[0].start(); en=s.index('{',ms[0].end())
        headers.append({'role':role,'receiver_or_module':{'durable':'DurableLedger','ledger_witness':'LedgerWitnessStore','production':'LedgerWriter','trust':'trust_distribution','owner':'OriginalCellQ24MaterialReceiptOwnersV1<EW,DW>','neuron_witness':'FileAnchorWitnessStore'}[role], 'method':name,'start_line':s.count('\n',0,st)+1,'signature':s[st:en].strip(), 'source':sources[role]})
for name in ['dataset_freeze_signing_payload_v2','freeze_dataset_from_ledger']:
    s=texts['production'];m=re.search(r'^pub fn '+name+r'\(',s,re.M);assert m
    en=s.index('{',m.end());headers.append({'role':'production','receiver_or_module':'production','method':name,'start_line':s.count('\n',0,m.start())+1,'signature':s[m.start():en].strip(),'source':sources['production']})

wrapper_path=V6/(SRC+'cell_q24_material_root_source.rs')
wrapper=wrapper_path.read_bytes()
assert b'OriginalCellQ24MaterialReceiptOwnersV1::into_command_owner(' in wrapper
assert b'from_original_material_root_stream(' in wrapper
wrapper_info={'path':str(wrapper_path),'repository_path':SRC+'cell_q24_material_root_source.rs',**pin(wrapper),'state':'frozen E2 Material22 source, not b608; complete source manually read; library-only'}

proof={'format':'hepta-material-production-entry-static-proof-v1','state':'STATIC_ONLY_NOT_EXECUTED','canonical_inventory':{'path':str(INV),**pin(INV.read_bytes())},'canonical_source':inventory['source'],'sources':sources,'actual_readonly_git_gets':git_reads,'cargo_explicit_bins':bins,'finite_entry_token_crosscheck':entry_tokens,'exact_constructor_signatures':headers,'frozen_E2_bridge':wrapper_info,'excerpts':[excerpt('owner',59,97),excerpt('binding',68,142),excerpt('binding',194,213),excerpt('production',685,701),excerpt('production',873,918),excerpt('trust',107,181),excerpt('neuron_witness',79,104)],'limits':['Token crosscheck is supporting evidence after reading the named entries, not an exhaustive Rust call-graph proof.','No whole-repository scan, project collector, test, Rust compiler, owner constructor, or H tool was run.','No source object/tree/commit/ref written.','New reference SDK wrappers are complete serialized tool responses; Git content GETs succeeded. Report and reviewer files have only computed local blob identities until Root archives them.']}
proof_pin=put('BYTE_AND_API_PROOF.json',proof)
review={
 'format':'hepta-material-production-entry-independent-review-v1','state':'STATIC_INTERFACE_FINDINGS_NOT_EXECUTED','proof':proof_pin,
 'conclusion':'The four explicit b608 Agentd executable entry points do not assemble the original Material pair, ActivatedTrust, LedgerWriter, or Material service. The examined frozen E2 extension adds a library bridge consuming a real pair; it does not supply a normal Material CLI/startup loader. A separate typed nonRoot loader is an actual integration gap, not an existing facility or a test-fixture substitute.',
 'entry_scope':[
  {'entry':'codex-hepta-agentd','finding':'Original Agentd production startup receives Config/writer and selected process bootstrap descriptors, then runs Agentd. No Material pair/ledger/owner construction in this entry.'},
  {'entry':'hepta-agentd-browser','finding':'Standalone Browser/Servo caller consumes explicit FinalUse authority; unrelated to Material owner construction.'},
  {'entry':'hepta-authority-host','finding':'Root initialization/registration/session/native/text/notes/learning handoff CLI. Root ownership is not an independent nonRoot Material service; no pair/ledger factory call here.'},
  {'entry':'hepta-g2-native-owner','finding':'Actual native G2 entry, not assumed to be a test. Its owner path receives original Root writer handoff after UID 60001 drop and constructs AgentdG2NativeOperationHost, then serves Observe/Prepare/Dispatch/Retire/Current/Reconcile. It supplies no Q24 Material pair/ledger/activated-trust loader.'}],
 'minimal_existing_chain':[
  'Authorize and pre-hold the actual ledger file, its separately retained witness, both containing-directory handles, binding and limits. For existing history use witness recover/frontier and an independently justified LedgerRecovery acknowledgment, then DurableLedger::recover. Both recovery paths may sync/truncate incomplete tails; they are real recovery operations, not read-only or automatically authorized by this report.',
  'Obtain a genuinely pretrusted LearningTrustRootV1 and full signed distribution. activate_learning_trust verifies the original root signature, domain, validity and generation; ActivatedLearningTrustV1 cannot be replaced by a bare signer list or untrusted child-selected root. Persisted rotation provenance must remain independent.',
  'Consume the backend, witness and ActivatedLearningTrustV1 through LedgerWriter::from_durable (or separately reviewed segmented equivalent). It syncs the directory handles and checks original binding/witness/frontier consistency. Do not reopen the same live writer through a second loader.',
  'Load the actual complete freeze plan and Evaluator SignedLearningEvidenceV1. dataset_freeze_signing_payload_v2 derives its head/frontiers/cuts/full source-record digest list from the actual ledger snapshot; LedgerWriter::freeze_dataset verifies that exact payload through its ActivatedTrust verifier and derives the original receipt. A snapshot codec, caller receipt, or digest alone grants nothing.',
  'Load complete OriginalCellQ24MaterialReceiptConfigV1: original initial snapshot, scope, dataset rule, freeze plan/evidence, both TrustedLearningSignerV1 bindings, verifier, and max signature lifetime. The two real SigningKey values must match those exact configured signer public keys and original Experience/Dataset owner IDs.',
  'Supply distinct existing Experience/Dataset journal files and original witness objects to Material owners create or recover according to explicit lifecycle purpose. Fresh creation is not atomic; partial initialization must remain visible. Recover refuses missing owners and remains Recovered, so it does not regain Fresh command execution authority.',
  'For the frozen E2 Root Source path, consume the actual pair through into_original_root_source_command_owner(stream, actual Root peer/pidfd, nonce, identity, original Arc<Mutex<LedgerWriter>>, original loaded model, timeout,lifetime). It constructs only the Source transport and delegates to the original into_command_owner. Four original command connection permits, signer/ledger/freeze binding and original readback checks remain in the old owner.'
 ],
 'loader_risks_and_reuse':[
  'FileAnchorWitnessStore::open(File,JournalScope,Generation,max_records) initializes a zero-length file. A Recover startup must reject missing/empty state before this call; the method name does not establish a read-only or recover-only guarantee.',
  'Material validate_config validates signer keys and freeze role/domain/window and commits full freeze signature bytes to journal binding. Cryptographic freeze reauthentication against current ledger is subsequently performed by verify_freeze and LedgerWriter::freeze_dataset on original owner operations. Do not overclaim the constructor alone verifies the full freeze payload.',
  'Existing e78f and 77b05 loader file/DTO helpers are private and require Root UID 0, 0600, regular/nlink/access-role/distinct FD checks. They are not a public nonRoot Material loader. Reusing their bounded decoding design requires a separately explicit Material process/FD ownership contract and must not loosen those original Root checks.',
  'No observed production CLI supplies the two Material signing keys, authorized file handles, independent ledger witness/trust-root history, or authentic Evaluator freeze. The new fourth layer must consume actual deployment custody for these inputs; qualification fixtures and fabricated receipts are not substitutes.',
  'The selected scope is four explicit Cargo bins and their named dispatch paths, the fixed Material factories and the frozen E2 bridge. It is not proof of every transitive call in the repository or of a deployed service state.'
 ],
 'execution':{'H_calls':0,'project_code_executed':False,'Rust_compiled':False,'tests_run':False,'source_or_registry_modified':False,'new_source_objects_or_refs':False},
 'archive_status':'Computed local report identities; five new original source blobs were actually full-GET, no Git create by this reviewer.'}
review_pin=put('REVIEW.json',review)
files=[]
for p in sorted(OUT.rglob('*')):
    if p.is_file(): files.append({'path':str(p),'relative_path':str(p.relative_to(OUT)),**pin(p.read_bytes()),'computed_content_identity_only':True})
index=put('CLOSED_FILE_INDEX.json',{'format':'hepta-local-static-review-closed-index-v1','entries':files,'source_refs_are_existing_objects':True,'report_git_upload_not_claimed':True})
print(json.dumps({'review':review_pin,'proof':proof_pin,'index':index,'payload_count':len(files),'all_files_under_512000':all(x['bytes']<=512000 for x in files)},indent=2))
