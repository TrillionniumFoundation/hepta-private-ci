#!/usr/bin/env python3
"""Reviewer-owned byte/schema checks. Does not import or execute project code."""
import difflib
import hashlib
import json
import re
from pathlib import Path

D = Path('/tmp/hepta-36fa-root-task-cli-loader-proposal-v1/inputs-layer-v1')
C = Path('/tmp/hepta-36fa-root-product-composition-v4')
O = Path('/tmp/hepta-36fa-root-generation-input-loader-independent-review-v1')
I = Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1/SOURCE.final.inventory.exact_recovered.json')
P = 'codex-rs/hepta-agentd/src/'
R = Path('/tmp/hepta-36fa-root-task-loader-references-v1')
R2 = Path('/tmp/hepta-36fa-root-task-cli-loader-proposal-v1/references')

def pin(b):
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}

def read(p):
    p=Path(p)
    a=p.stat()
    b=p.read_bytes()
    z=p.stat()
    assert (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns,z.st_ctime_ns),str(p)
    assert len(b)==a.st_size,str(p)
    return b

def unique(pairs):
    d={}
    for k,v in pairs:
        assert k not in d,('duplicate JSON key',k)
        d[k]=v
    return d

def js(p):
    return json.loads(read(p),object_pairs_hook=unique)

def exact(p,expected):
    b=read(p)
    assert pin(b)==expected,{'path':str(p),'actual':pin(b),'expected':expected}
    return b

def block(s,start):
    """Balanced braces for these fixed, manually read declaration/literal blocks.
    No claim of a general Rust parser. Their quoted strings contain no braces.
    """
    p=s.index('{',start)
    n=1
    q=p+1
    while n:
        n += (s[q]=='{')-(s[q]=='}')
        q+=1
    return s[p+1:q-1],p,q

def declared_fields(s,name):
    matches=list(re.finditer(r'\bstruct\s+'+re.escape(name)+r'\s*\{',s))
    assert len(matches)==1,(name,len(matches))
    b,_,_=block(s,matches[0].start())
    fields=re.findall(r'^\s*(?:pub(?:\([^)]*\))?\s+)?([A-Za-z_]\w*)\s*:',b,re.M)
    assert len(fields)==len(set(fields)),name
    return fields

def literal_fields(s,name):
    matches=list(re.finditer(r'\b'+re.escape(name)+r'\s*\{',s))
    # The fixed receipt factory also names this type immediately before its
    # function body. Exclude that return-type occurrence, not a record literal.
    matches=[m for m in matches if '->' not in s[s.rfind('\n',0,m.start())+1:m.start()]]
    assert len(matches)==1,(name,len(matches))
    b,_,_=block(s,matches[0].start())
    depth=0
    found=[]
    for line in b.splitlines():
        if depth==0:
            m=re.match(r'\s*([A-Za-z_]\w*)\s*(?::|,\s*$)',line)
            if m:
                found.append(m.group(1))
        depth+=line.count('{')-line.count('}')
    assert len(found)==len(set(found)),name
    return found

def witness(s,needle):
    at=s.index(needle)
    return {'text':needle,'line':s[:at].count('\n')+1}

def ordered(s,needles):
    out=[]
    at=0
    for needle in needles:
        k=s.index(needle,at)
        out.append({'text':needle,'line':s[:k].count('\n')+1})
        at=k+len(needle)
    return out

def emit(name,obj):
    b=(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    with (O/name).open('xb') as f:
        f.write(b)
    return pin(b)

expected_packet={'bytes':287484,'sha256':'7f4d2087943efc969eda7ca540d21e51c52418db5ecfe81a8be77a9362d98d4b','git_blob':'e78f0413a20e306c1064c51eb8e53e76d597fd93'}
exact(D/'SOURCE_PACKET.json',expected_packet)
packet=js(D/'SOURCE_PACKET.json')
manifest=js(D/'MANIFEST.json')
assert packet['base_commit']=='b6084394a4a38ab495c16eaba09e879f04a96f8e'
assert packet['format']=='full-before-after-utf8-v1'
assert packet['state']=='LOCAL_FROZEN_UNCOMPILED_PROPOSAL_NO_H_NO_SOURCE_GIT'
assert len(packet['entries'])==8
assert manifest['source_packet']==expected_packet
for key,name in [('mount_splices','MOUNT_SPLICES.json'),('preparation_alignment','BASE_ALIGNMENT.json'),('review','REVIEW.json'),('source_delta','SOURCE_DELTA.patch'),('source_references','SOURCE_REFERENCES.json'),('static_byte_review','STATIC_BYTE_REVIEW.json')]:
    exact(D/name,manifest[key])

inv_raw=read(I)
assert pin(inv_raw)=={'bytes':5631947,'sha256':'de044334afed8b804f2a997f8b8e8d16e6e1c596d2a5b3400c40f350229b054e','git_blob':'457adb9bf9ba3a844e9dfa149be49460bb306998'}
inv=json.loads(inv_raw,object_pairs_hook=unique)
baseline={r['path']:r for r in inv['files']}
assert len(baseline)==15243
composition=js(C/'PREQUALIFICATION_COMPOSITION_REVIEW.json')
assert pin(read(C/'PREQUALIFICATION_COMPOSITION_REVIEW.json'))['git_blob']=='eab2a34d1bd7abbaab81d5c1e06177269a14efd4'
current={r['path']:r for r in composition['files']}
assert len(current)==93
ms={r['path']:r for r in manifest['files']}
es={r['path']:r for r in packet['entries']}
assert len(es)==8 and set(ms)==set(es)
splices=js(D/'MOUNT_SPLICES.json')
assert len(splices)==4
sp={r['path']:r for r in splices}
proof_files=[]
patch=[]
texts={}
for e in packet['entries']:
    p=e['path']
    assert p.startswith(P) and p.endswith('.rs')
    assert e['before']==ms[p]['before'] and e['after']==ms[p]['after']
    after=e['after_utf8'].encode()
    assert pin(after)==e['after'] and read(D/'after'/p)==after
    texts[p]=e['after_utf8']
    if e['before'] is None:
        assert e['before_utf8'] is None and p not in sp
        assert p not in baseline and p not in current and not (C/'after'/p).exists()
        before=b''
        item={'path':p,'before':None,'after':e['after'],'new_against_b608_and_v4':True}
    else:
        before=e['before_utf8'].encode()
        assert pin(before)==e['before']
        assert read(D/'before'/p)==before==read(C/'after'/p)
        assert current[p]['after']==e['before']
        s=sp[p]
        assert s['before']==e['before'] and s['inverse_exact'] is True
        assert before.decode().replace(s['old'],s['new'],1)==e['after_utf8']
        assert e['after_utf8'].count(s['new'])==1
        assert e['after_utf8'].replace(s['new'],s['old'],1)==e['before_utf8']
        item={'path':p,'before':e['before'],'after':e['after'],'exact_v4_preimage':True,
              'forward_first_occurrence_and_full_inverse_equal':True,
              'old_anchor_occurrences':e['before_utf8'].count(s['old']),
              'new_anchor_occurrences':e['after_utf8'].count(s['new'])}
    proof_files.append(item)
    patch.extend(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='a/'+p if e['before'] else '/dev/null',tofile='b/'+p))
assert sum(r['before'] is None for r in proof_files)==4
assert ''.join(patch).encode()==read(D/'SOURCE_DELTA.patch')

refs=js(D/'SOURCE_REFERENCES.json')
assert len(refs)==29
reference_proof=[]
for r in refs:
    want={k:r[k] for k in ('bytes','sha256','git_blob')}
    exact(r['local'],want)
    original=baseline[r['path']]
    assert want=={'bytes':original['bytes'],'sha256':original['sha256'],'git_blob':original['working_blob']}
    assert original['index_blob']==original['working_blob'] and original['matches_index'] is True
    reference_proof.append({'path':r['path'],'local':r['local'],'pin':want,'all_bytes_match_b608_inventory':True,
                            'meaning':'content validation, not a claim that every line was semantically audited'})
extra=[
('/tmp/hepta-36fa-root-product-e3-proposal-v1/references/codex-rs/hepta-agentd/src/authority_host_config.rs','codex-rs/hepta-agentd/src/authority_host_config.rs','24c49866fdd994f8bc2c1b9fdc40342149525bca'),
('/tmp/hepta-36fa-root-product-e1-proposal-v1/references/codex-rs/hepta-contracts/src/final_use_retained.rs','codex-rs/hepta-contracts/src/final_use_retained.rs','7657ebef9ff22db3265484867fbc8b9d622ca531'),
(str(R2/'codex-rs/hepta-contracts/src/authority_trust.rs'),'codex-rs/hepta-contracts/src/authority_trust.rs','043ffd75a20c42935959a98d37f40e3d7229c407'),
]
for local,p,g in extra:
    raw=read(local); got=pin(raw);b=baseline[p]
    assert got['git_blob']==g
    assert got=={'bytes':b['bytes'],'sha256':b['sha256'],'git_blob':b['working_blob']}
    reference_proof.append({'path':p,'local':local,'pin':got,'all_bytes_match_b608_inventory':True})

types=texts[P+'authority_host_generation_input_types.rs']
dataflow=[]
for dto,original,rel in [
('SignerFile','TrustedArtifactSignerV1','owner_host.rs'),
('OwnerTrustFile','ArtifactOwnerTrustV1','owner_host.rs'),
('WriterLeaseFile','SignedArtifactWriterLeaseV1','owner_host.rs'),
('WitnessFile','RegistryHeadWitnessV1','closure_v2.rs'),
('CurrentHeadFile','SignedCurrentArtifactHeadV1','owner_host.rs'),
('WithdrawalSnapshotFile','DatasetWithdrawalSnapshotReceiptV1','durable_snapshots.rs'),
('SelectorFile','TrustedArtifactSelectorV1','selection.rs'),
('SelectionTrustFile','ArtifactSelectionTrustV1','selection.rs'),
('SelectionRecordFile','SignedArtifactSelectionV1','selection.rs'),
]:
    path=R/'codex-rs/hepta-learning-artifacts/src'/rel
    source=read(path).decode()
    a=declared_fields(types,dto);b=declared_fields(source,original);c=literal_fields(types,original)
    assert a==b==c,(dto,a,b,c)
    dataflow.append({'dto':dto,'original_type':original,'fields':a,'count':len(a),
                     'source_path':str(path),'source_pin':pin(source.encode()),
                     'complete_declared_and_construction_field_lists_equal':True})
structs=re.findall(r'(?:pub\(super\)\s+)?struct\s+(\w+)\s*\{',types)
assert len(structs)==14
for name in structs:
    m=re.search(r'#\[derive\(Deserialize\)\]\n#\[serde\(deny_unknown_fields\)\]\n(?:pub\(super\)\s+)?struct\s+'+name+r'\s*\{',types)
    assert m,name
assert '#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]\npub(super) enum OperationFile' in types
assert '#[serde(rename_all = "snake_case")]\npub(super) enum ConsumerTrustModel {\n    SingleCurrentIssuer,\n    CurrentIssuerKeyRing,\n}' in types
value_checks=[witness(types,x) for x in [
'signature: signature(self.signature)?,','bytes.try_into().map_err(|_: Vec<u8>| invalid("original signature must contain 64 bytes"))',
'if self.artifact_kind != "model"','artifact_kind: ArtifactKind::Model,',
'predecessor_id: self.predecessor_id.map(StableId::new).transpose().map_err(invalid)?,',
'writer_signers: self.writer_signers.into_iter().map(SignerFile::original).collect::<Result<_, _>>()?,',
'head_signers: self.head_signers.into_iter().map(SignerFile::original).collect::<Result<_, _>>()?,',
'pub(super) required_external_frontier: FinalUseFrontier,','pub(super) configuration: CellGenerationConfigV2,',
]]
assert types.count('signature: signature(self.signature)?,')==3

loader=texts[P+'authority_host_generation_input_loader.rs']
ordered_calls=ordered(loader,[
'require_before(end)?;',
'let value: GenerationDeploymentFile = read_root_json(deployment)?;',
'files::require_descriptors(&original_files, purpose)?;',
'files::require_artifact_directory(original_state, &value.artifacts.state_directory)?;',
'files::require_existing_consumer(original_state, &value.consumer.state_directory)?;',
'let root = Arc::clone(self.resident_store_root.as_ref()',
'if self.root_registry.is_none()',
'let trust = value.artifacts.trust.original()?;',
'ArtifactSelectionVerifierV1::new(value.selection.trust.original()?, &trust)',
'let required_current_head = value.artifacts.required_current_head.original()?;',
'let withdrawal_registry = read_dataset_withdrawal_snapshot(',
'let artifacts = LearningArtifactOwnerService::open(',
'required_current_head: Some(required_current_head),',
'let selected = AgentdSelectedGenerationV1::load(',
'let key = self.issuer.trust_key()?;',
'let head = self.issuer.revocations()?;',
'if owner_id != key.key_id',
'signed.grant.signer_id != owner_id',
'HostAuthorityFrontierStore::<FinalUseFrontier>::open(',
'frontier.load(&owner_id).map_err(invalid)? != value.consumer.required_external_frontier',
'let final_use = match value.consumer.trust_model',
'FinalUseAuthority::open_state_dir_with_trust(',
'FinalUseAuthority::open_state_dir_with_issuer_keys(',
'if final_use.current_external_frontier().map_err(invalid)? != value.consumer.required_external_frontier',
'|| final_use.revocation_head().map_err(invalid)? != head',
'|| self.issuer.revocations()? != head',
'CellGenerationOwnerBindingV1::new(&configuration, value.target.maximum_records)',
'let witness = FileAnchorWitnessStore::open(',
'scope_digest: Digest32::from_array(binding.digest().map_err(invalid)?),',
'objective_digest: Digest32::from_array(configuration.task_digest),',
'Generation::new(configuration.initial.generation).map_err(invalid)?,',
'let target = AgentdGenerationUpdateTargetV1',
'let artifacts = Arc::new(Mutex::new(artifacts));',
'let final_use = Arc::new(final_use);',
'require_before(end)?;',
'Ok(match value.operation',
])
file_checks=texts[P+'authority_host_generation_input_files.rs']
file_witnesses=[witness(file_checks,x) for x in [
'(&files.registry_snapshot, Access::ReadOnly),','(&files.selected_payload, Access::ReadOnly),',
'(&files.withdrawal_snapshot, Access::ReadOnly),','(&files.target_journal, Access::ReadWrite),','(&files.target_witness, Access::ReadWrite),',
'flags & libc::O_ACCMODE != expected','flags & libc::O_APPEND != 0','!identities.insert((metadata.dev(), metadata.ino()))',
'matches!(purpose, LoadPurpose::Recover)','files.target_journal.metadata()?.len() == 0 || files.target_witness.metadata()?.len() < 112',
'for name in ["writer", "transactions", "payloads", "registries", "witnesses", "heads"]',
'open_private(&artifact.join("writer/owner.lock"))?',
'open_private(&consumer.join("authority.lock"))?','open_private(&consumer.join("authority.claims"))?',
'open_private(&consumer.join("authority.json"))?',
'before.len() == 0 || before.len() > 8 * 1024 * 1024',
'header.by_ref().take(8 * 1024 * 1024 + 1).read_to_end(&mut bytes)?;',
'before.dev() != after.dev() || before.ino() != after.ino()',
'before.mtime_nsec() != after.mtime_nsec() || before.ctime() != after.ctime()',
'before.ctime_nsec() != after.ctime_nsec()',
'value.get("schema").and_then(serde_json::Value::as_u64) != Some(3)',
'!state.is_absolute() || !path.is_absolute() || path == state || !path.starts_with(state)',
'path.components().any(|part| !matches!(part, Component::RootDir | Component::Normal(_)))',
'RootAuthorityDirectory::open(path).map_err(invalid)?;',
'.custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK).open(path)?;',
'!metadata.is_file() || metadata.uid() != 0',
'metadata.mode() & 0o777 != 0o600 || metadata.nlink() != 1',
]]
session=texts[P+'authority_host_session_generation_input_loader.rs']
session_flows=[]
for name,purpose,call,phase in [
('prepare_original_initial_generation_from_files','Fresh','let operation = HostAuthorityService::bind_original_initial_operation(&self.service, &inputs, end)?;','phase: InitialHostPhase::Fresh(inputs)'),
('recover_original_initial_generation_from_files','Recover','let (operation, custody) = HostAuthorityService::recover_original_initial_operation(&self.service, inputs, end)?;','phase: InitialHostPhase::Ready(custody)'),
]:
    at=session.index('pub fn '+name+'(')
    body,_,_=block(session,at)
    assert body.count('let end = Instant::now() + Duration::from_millis(self.config.timeout_ms);')==1
    assert body.count('require_original_session(&self, end)?;')==2
    flow=ordered(body,[
    'let end = Instant::now() + Duration::from_millis(self.config.timeout_ms);',
    'require_original_session(&self, end)?;',
    'let OriginalLoadedGeneration::'+purpose+'(inputs) = HostAuthorityService::load_original_initial_generation_inputs(',
    '&self.service, &self.config.state_dir, deployment, files, OriginalGenerationLoadPurpose::'+purpose+', end,',
    call,'require_original_session(&self, end)?;',phase])
    assert 'session: self' in body
    assert 'end,' in body
    session_flows.append({'function':name,'single_end':True,'session_consumed_and_retained':True,'exact_variant_no_fallback':True,'ordered_source_anchors_relative_to_body':flow})
assert loader.count('Instant::now()')==1 and 'Instant::now() >= end' in loader
assert session.count('Instant::now()')==2
assert 'unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0' in loader
assert 'self.issuer.sign' not in loader and 'new_issuer' not in loader
assert 'FinalUseFrontier::for_initial_head' not in loader
assert 'FinalUseAuthority::open_state_dir(' not in loader
assert 'HostAuthorityFrontierStore::<FinalUseFrontier>::initialize' not in loader
assert 'update_revocations' not in loader
assert 'RootHostInitialGenerationFilesV1' in texts[P+'lib.rs']
assert '#[cfg(target_os = "linux")]\npub use authority_host_service::RootHostInitialGenerationFilesV1;' in texts[P+'lib.rs']

proof={'format':'independent-fixed-source-byte-and-contract-review-v1',
'state':'STATIC_SOURCE_ONLY_NOT_COMPILED_OR_EXECUTED',
'source_packet':expected_packet,'manifest':pin(read(D/'MANIFEST.json')),
'basis':{'v4_composition_review':pin(read(C/'PREQUALIFICATION_COMPOSITION_REVIEW.json')),'canonical_inventory':pin(inv_raw)},
'files':proof_files,'exact_patch':pin(read(D/'SOURCE_DELTA.patch')),
'references':reference_proof,
'record_mapping':dataflow,'record_mapping_field_count':sum(r['count'] for r in dataflow),
'local_dto_structs_with_deny_unknown_fields':structs,
'closed_tagged_operation_enum':True,'closed_two_value_trust_enum':True,
'value_conversion_anchors':value_checks,'ordered_original_factory_calls':ordered_calls,
'descriptor_and_existing_state_anchors':file_witnesses,'session_flows':session_flows,
'unchanged_old_source':'All four modified parent files are exact insertion-only first-occurrence splices, full forward and inverse equality; original bodies remain byte-for-byte.',
'scope_limitations':['Python parsed source text and JSON data only; no Rust compiler, formatter, Cargo, QA, collector, H or owner constructor executed.',
'Ordered textual anchors supplement full manual code reading; they are not a Rust AST/type-check proof or a runtime result.',
'Reference byte binding to b608 does not mean every referenced module was semantically reviewed in full.',
'Root file/path checks do not establish a cross-owner atomic transaction or physical cancellation guarantee.',
'Fresh witness initialization and original recovery/store factory effects are not ruled out by these prechecks; a failure is not evidence of unchanged files.'],
'H_calls':0,'project_code_executed':False,'source_ref_or_source_worktree_modified':False,'qualification':False,
'git_storage_claim':'These output pins are locally computed only; this script does not upload to Git.'}
result=emit('BYTE_AND_CONTRACT_PROOF.json',proof)
print(json.dumps({'status':'PASS_STATIC_BYTE_AND_SCHEMA_ONLY','proof':result,'files':len(proof_files),'field_mappings':len(dataflow),'field_count':proof['record_mapping_field_count'],'references':len(reference_proof),'H_calls':0,'project_code_executed':False},sort_keys=True))
