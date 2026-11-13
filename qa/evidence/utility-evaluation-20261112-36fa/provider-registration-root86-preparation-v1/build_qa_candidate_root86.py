#!/usr/bin/env python3
"""Prepare exact QA constants/scopes and preserved attacks without running QA."""
from pathlib import Path
import ast, copy, hashlib, importlib.util, json, pprint, re, sys, tomllib, types
sys.dont_write_bytecode = True
R = Path(__file__).resolve().parent
OUT = R / "candidate-registration-root86-final"
VIEW = R / "view-root86"
QA = "qa/b4-no-bypass/"
AGENT = "codex-rs/hepta-agentd/src/"

def pin(data):
    return {"bytes":len(data), "sha256":hashlib.sha256(data).hexdigest(),
            "git_blob":hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}

def save(path, value):
    target = OUT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value, indent=2) + "\n"
    with target.open("x") as f: f.write(text)
    return pin(text.encode())

spec = importlib.util.spec_from_file_location("qa_preparation_original_predicates", R / "before/scripts/verify_hepta_callers.py")
PROOF = importlib.util.module_from_spec(spec); sys.modules[spec.name] = PROOF; spec.loader.exec_module(PROOF)
original_scope_text = (R / "before" / QA / "test_evaluated_published_read_source_closure.py").read_text()
pure = [n for n in ast.parse(original_scope_text).body if isinstance(n, ast.FunctionDef) and n.name.startswith("ordinary_")]
ns = {"PROOF":PROOF, "re":re}
exec(compile(ast.Module(body=pure, type_ignores=[]), "original_scope_definitions_only", "exec"), ns)
SCOPES = types.SimpleNamespace(**ns)
template = (R / "provider_qa.template.py").read_text()
new_pure = [n for n in ast.parse(template).body if isinstance(n, ast.FunctionDef)]
qa_ns = {"PROOF":PROOF, "SCOPES":SCOPES, "re":re, "hashlib":hashlib}
exec(compile(ast.Module(body=new_pure, type_ignores=[]), "provider_pure_scope_definitions_only", "exec"), qa_ns)
active_source, actual_scope = qa_ns["active_source"], qa_ns["actual_scope"]

old = tomllib.loads((R / "before/CALLERS.toml").read_text())
new = tomllib.loads((OUT / "CALLERS.toml").read_text())
old_by_id = {b["id"]:b for b in old["boundary"]}
new_by_id = {b["id"]:b for b in new["boundary"]}
inputs = json.loads((R / "SOURCE_VIEW_ROOT86_INPUTS.json").read_text())
source = {row["path"]:(VIEW / row["path"]).read_text() for row in inputs["rows"]
          if row["path"].startswith(AGENT) and row["path"].endswith(".rs")
          and not PROOF._is_ignored(row["path"], tuple(old["ignored_path_fragments"]))}
functions = json.loads((OUT / "SOURCE_SCOPE_INPUTS.json").read_text())["functions"]
mounts = json.loads((OUT / "SOURCE_SCOPE_INPUTS.json").read_text())["mounts"]

scopes = {}
for path, raw in source.items():
    if path.endswith("/lib.rs"):
        continue
    code, literals = active_source(raw)
    selectors = []
    for found in re.finditer(r"(?m)^[ \t]*(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?(struct|enum|trait)\s+(\w+)\b", code):
        start = found.start()
        while code[start].isspace(): start += 1
        if SCOPES.ordinary_depth_at(code,start) == (0,0,0):
            selectors.append({"kind":"root_type","item_kind":found.group(1),"name":found.group(2)})
    containers = SCOPES.ordinary_root_containers(PROOF,code)
    for item in containers:
        if item["header"].startswith("trait ") or re.match(r"pub(?:\([^)]*\))? trait ",item["header"]):
            continue
        selector = {"kind":"root_container","header":item["header"]}
        matches = [c for c in containers if c["header"] == item["header"]]
        if len(matches) > 1:
            names = re.findall(r"\bfn\s+(\w+)\s*(?=[(<])", code[item["opening"]+1:item["end"]-1])
            anchors = [name for name in names if sum(bool(re.search(r"\bfn\s+"+re.escape(name)+r"\s*(?=[(<])",code[c["opening"]+1:c["end"]-1])) for c in matches)==1]
            assert anchors,(path,item["header"])
            selector["anchor"] = anchors[0]
        selectors.append(selector)
    for item in functions[path]:
        if item["owner"] is None:
            selectors.append({"kind":"root_function","name":item["name"]})
    for found in re.finditer(r"(?m)^[ \t]*(?:pub(?:\([^)]*\))?\s+)?(const|type)\s+(\w+)\b",code):
        start=found.start()
        while code[start].isspace():start+=1
        if SCOPES.ordinary_depth_at(code,start)==(0,0,0):
            selectors.append({"kind":"root_named_item","item_kind":found.group(1),"name":found.group(2)})
    guards=[];spans=set()
    for selector in selectors:
        start,end=actual_scope(code,selector)
        assert (start,end) not in spans,(path,selector)
        spans.add((start,end))
        guards.append({"selector":selector,
                       "masked_sha256":hashlib.sha256(code[start:end].encode()).hexdigest(),
                       "literal_source_sha256":hashlib.sha256(literals[start:end].encode()).hexdigest()})
    scopes[path]=guards

attacks={k:[]for k in ("sealed_clones","original_identity","local_budget","readiness","version_current","root_handoff","root_service","shared_seals")}
def add(group,file,function,*markers):
    path=AGENT+file
    code,_=active_source(source[path])
    span=SCOPES.ordinary_select_scope(PROOF,code,{"kind":"unique_function","name":function})
    for marker in markers:
        pattern=r"\s*".join(re.escape(token)for token in re.findall(r"\w+|[^\w\s]",marker))
        if marker[0].isalnum()or marker[0]=="_":pattern=r"(?<!\w)"+pattern
        if marker[-1].isalnum()or marker[-1]=="_":pattern+=r"(?!\w)"
        assert re.search(pattern,code[span["start"]:span["end"]]),(group,path,function,marker)
        attacks[group].append({"path":path,"function":function,"marker":marker})

for file in ("circuit_learning_local_read.rs","circuit_selection_local_predecessor.rs"):
    add("sealed_clones",file,"clone","Arc::clone(&self.original)")
add("original_identity","circuit_retained_version_local_read.rs","require_original_shared_readbacks",
    "self.version.state.try_lock()","!std::ptr::eq(held_trainer, given_trainer)","!std::ptr::eq(held_evaluator, given_evaluator)",
    "PublicationAccess::Readback","RetainedVersionFinalUseOutcomeV1::Published")
add("original_identity","circuit_selection_local_predecessor.rs","require_original_shared_predecessors",
    "!std::ptr::eq(original_t, current_t)","!std::ptr::eq(original_e, current_e)")
add("original_identity","circuit_learning_local_read.rs","require_original_local_shared_readbacks",
    "OriginalVersionLocalReadBindingV1::require_original_shared_readbacks(")
add("local_budget","circuit_learning_local_read.rs","read_original",
    ".take()","!(1..=128).contains(&slot.next_request_id)","request_id.checked_add(1)",
    ".min(self.original.original.original_end())","tokio::time::timeout_at(","response.require_request(&request)?",
    "self.require_original_window()?","Instant::now() >= deadline","*destination = Some(slot)")
add("local_budget","circuit_selection_local_predecessor.rs","read_original_selection",
    ".take()","!(1..=128).contains(&slot.next_request_id)",".min(self.original.end)",
    "OriginalCircuitSelectionLocalReadbackV1::require_original_selection(self, &value)?", "Instant::now() >= deadline","*restore = Some(slot)")
add("local_budget","circuit_retained_version_local_read.rs","open_original_evaluated_local_read",
    "Duration::from_millis(500)","Duration::from_secs(300)",".try_acquire_owned()", "Instant::now() >= admission_end")
add("readiness","circuit_completion_readiness_local.rs","bind_original_evaluated_local_read",
    "OriginalCircuitLearningReadClientV1::require_original_local_evaluated_next_use(","scope != material.scope",
    "initial.snapshot() != &material.initial","&original_dataset != dataset.snapshot()",
    "OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(","channel: Mutex::new(None)","local: Some(local)")
add("readiness","circuit_learning_local_read.rs","read_completion_readiness",
    "self.original.context.mode()? != wire::Mode::NextUse","LocalReadOperation::CompletionReadiness")
add("version_current","circuit_retained_version_next_use_readback.rs","original_evaluated_next_use_response",
    "self.read_original(&state)?","before != after","after.publication().is_none()",
    "cut.require_fresh(","selection.original_receipt_predecessors(","RetainedVersionFinalUseOutcomeV1::Published")
add("version_current","circuit_retained_version_local_read.rs","respond",
    "Instant::now() >= self.end","!(1..=128).contains(&request_id)","OriginalVersionLocalReadOperationV1::CompletionReadiness")
add("root_handoff","root_candidate_stage_handoff.rs","send_root_candidate_stage_handoff",
    "require_root()?","super::root_pair(","super::require_root_pin(","require_process(&recipient)?",
    "sockets.insert(wire::socket_identity(","now.checked_add(lifetime_ns)")
add("root_handoff","root_candidate_stage_handoff.rs","receive_root_candidate_stage_handoff",
    "super::require_root_pin(&sender, root.pid as u32)?","validate_packet(&packet, profile.binding())?")
add("root_handoff","root_candidate_stage_handoff.rs","into_original_streams",
    "validate_packet(&self.packet, profile.binding())?","check_lifetime(&self.sender)","minimum.checked_sub(now)","require_timing(")
add("root_handoff","root_candidate_stage_handoff_wire.rs","receive",
    "libc::MSG_CMSG_CLOEXEC","libc::MSG_TRUNC | libc::MSG_CTRUNC")
add("root_service","authority_host_learning_candidate_service.rs","into_candidate_service",
    "ResidentRootAuthorityV3::perform(","ResidentRootAuthorityV3::readonly(&self.owner.authority)",
    "OriginalCellQ24CandidateStageOwnersV1::recover_original_streams(","OriginalCellQ24CandidateStageOwnersV1::from_original_streams(",
    "OriginalCellQ24CandidateStageOwnersV1::restrict_original_handoff_deadline(")
add("root_service","authority_host_learning_candidate_service.rs","run",
    "cancellation.clone().drop_guard()","tokio::join!(run, server)","root_cancellation.cancelled()",
    "shutdown.0.shutdown(Shutdown::Both)","work.await")
for file, authenticate in (("cell_q24_training_shared_readback.rs", "wire::authenticate_receipt("),
                           ("neuron_cell_evaluation_shared_readback.rs", "wire::authenticate_completed(")):
    add("shared_seals",file,"seal_original_completed_readback","original != expected","channel.peer.check_peer_lifetime()?",
        authenticate,"&authenticated != original","channel.execution_requested = true","Ok(Arc::new(self))")

checked={key:new[key]for key in("boundary","privileged_inventory","authority","source_roots","ignored_path_fragments")}
contract={"format":"provider-local-read-source-contract-v1","root_source_map":"3f7d40d4933669da33d2aef3491efb431c5771ae",
          "boundary_count":len(new['boundary']),"complete_boundary_sha256":hashlib.sha256(json.dumps(checked,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
          "new_boundaries":new['boundary'][len(old['boundary']):],"scopes":scopes,
          "module_shapes":{path:qa_ns['module_shape'](*active_source(source[path]))for path in scopes},
          "mounts":{p:[{k:v for k,v in m.items()if k in('parent','child','path_literal','module_name')}for m in ms]for p,ms in mounts.items()if ms},
          "exports":[line for line in source[AGENT+'lib.rs'].splitlines()if line.startswith('pub use ')and any(n in line for n in(
              'RootResidentCandidateInputsV1','RootResidentCandidateServiceV1','receive_root_candidate_stage_handoff','send_root_candidate_stage_handoff',
              'OriginalCircuitSelectionLocalReadbackV1','OriginalCircuitPublishedLocalReadV1'))],
          "attacks":attacks,
          "protocol_items":[[AGENT+'root_candidate_stage_handoff.rs',{'kind':'root_named_item','item_kind':'const','name':n}]for n in('PURPOSE','ROLES')],
          "decoy_functions":[[AGENT+'circuit_learning_local_read.rs','read_original'],[AGENT+'circuit_retained_version_local_read.rs','require_original_shared_readbacks'],
                             [AGENT+'root_candidate_stage_handoff.rs','validate_packet']]}
qa_ns['CONTRACT']=contract
# Only actual construction/location functions are called. No unittest class is
# loaded or test method invoked, and no source-index gate is executed.
for path in contract['scopes']:qa_ns['require_scopes'](path,source[path])
contract_text=json.dumps(contract,indent=2)+'\n'
contract_sha=hashlib.sha256(contract_text.encode()).hexdigest()
contract_load=('CONTRACT_PATH = ROOT / "qa/b4-no-bypass/PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json"\n'
               'CONTRACT_BYTES = CONTRACT_PATH.read_bytes()\n'
               'if hashlib.sha256(CONTRACT_BYTES).hexdigest() != '+repr(contract_sha)+':\n'
               '    raise PROOF.VerificationFailure("exact reviewed provider source contract required")\n'
               'CONTRACT = json.loads(CONTRACT_BYTES)')
new_qa=template.replace('# GENERATED_CONTRACT\nCONTRACT = None','# Exact prepared data; final formatting must be frozen again.\n'+contract_load)
ast.parse(new_qa)
new_qa_path=QA+'test_resident_provider_local_read_source_closure.py'
save(new_qa_path,new_qa)
save(QA+'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json',contract_text)

# Exact old literal dictionaries are updated by boundary identity, never by a
# substring replacement. Partial ADMITTED subsets remain unchanged.
def node_offsets(text,node):
    lines=text.splitlines(keepends=True);prefix=[0]
    for line in lines:prefix.append(prefix[-1]+len(line))
    return prefix[node.lineno-1]+node.col_offset,prefix[node.end_lineno-1]+node.end_col_offset

def static_value(node, names):
    if isinstance(node,ast.Name):return names[node.id]
    if isinstance(node,ast.BinOp)and isinstance(node.op,ast.Add):return static_value(node.left,names)+static_value(node.right,names)
    if isinstance(node,(ast.Tuple,ast.List)):
        values=[static_value(n,names)for n in node.elts]
        return tuple(values)if isinstance(node,ast.Tuple)else values
    if isinstance(node,ast.Dict):return {static_value(k,names):static_value(v,names)for k,v in zip(node.keys,node.values)}
    return ast.literal_eval(node)

qa_changes=[]; old_methods={}; new_methods={}; boundary_constants=[]; scope_updates=[]
for file in sorted((R/'before'/QA).glob('*.py')):
    relative=QA+file.name
    canonical=file.read_text()
    before=(VIEW/relative).read_text()if(VIEW/relative).exists()else canonical
    text=before; tree=ast.parse(text); edits=[]; names={}
    for node in tree.body:
        if isinstance(node,ast.Assign)and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            try:names[node.targets[0].id]=static_value(node.value,names)
            except(Exception):pass
    for node in ast.walk(tree):
        if not isinstance(node,ast.Dict):continue
        for key,value in zip(node.keys,node.values):
            if not isinstance(key,ast.Constant)or key.value not in old_by_id:continue
            identity=key.value
            if old_by_id[identity]['product_callers']==new_by_id[identity]['product_callers']:continue
            try:actual=static_value(value,names)
            except(Exception):continue
            if not isinstance(actual,(list,tuple))or list(actual)!=old_by_id[identity]['product_callers']:continue
            replacement=list(new_by_id[identity]['product_callers'])
            if isinstance(actual,tuple):replacement=tuple(replacement)
            start,end=node_offsets(text,value);edits.append((start,end,pprint.pformat(replacement,width=100,sort_dicts=False)))
            boundary_constants.append({'path':relative,'boundary':identity,'before':list(actual),'after':list(replacement)})
    if file.name=='test_evaluated_published_read_source_closure.py':
        assignments={n.targets[0].id:n for n in tree.body if isinstance(n,ast.Assign)and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)}
        old_scopes=copy.deepcopy(names['ORDINARY_SCOPE_GUARDS'])
        for path,guards in old_scopes.items():
            if path not in source:continue
            code,_=active_source(source[path])
            for guard in guards:
                span=SCOPES.ordinary_select_scope(PROOF,code,guard['selector'])
                observed=hashlib.sha256(code[span['start']:span['end']].encode()).hexdigest()
                if observed!=guard['masked_sha256']:
                    scope_updates.append({'path':path,'selector':guard['selector'],'before':guard['masked_sha256'],'after':observed})
                    guard['masked_sha256']=observed
        updates={'ORDINARY_SCOPE_GUARDS':old_scopes,'ORDINARY_COMPLETE_BOUNDARY_SHA256':contract['complete_boundary_sha256'],
                 'ORDINARY_NEW_BOUNDARIES':new['boundary'][541:569]}
        for name,value in updates.items():
            node=assignments[name].value;start,end=node_offsets(text,node)
            # Discard nested old-key edits if this whole constant is replaced.
            edits=[e for e in edits if not(start<=e[0]and e[1]<=end)]
            edits.append((start,end,pprint.pformat(value,width=100,sort_dicts=False)))
    for start,end,value in sorted(edits,reverse=True):text=text[:start]+value+text[end:]
    if file.name=='test_evaluated_published_read_source_closure.py':
        assert text.count('self.assertEqual(len(boundaries), 569)')==1
        text=text.replace('self.assertEqual(len(boundaries), 569)',f'self.assertEqual(len(boundaries), {len(new["boundary"])})')
        assert text.count('self.manifest["boundary"][-28:]')==1
        text=text.replace('self.manifest["boundary"][-28:]','self.manifest["boundary"][541:569]')
        text=text.replace('# Actual post-format root scopes supplement the original verifier\'s generic', '# Exact prepared root scopes supplement the original verifier\'s generic')
    if file.name=='test_evaluated_next_use_source_closure.py':
        a='"let selector: &LearningIterationEvidenceClientV1 = source.selector();"';b='"let selection = match source.selector()"'
        c='".readback(source.snapshot(), prior(&self.config, LearningIterationStageV1::Selection)?,)"'
        d='"LearningIterationEvidenceClientV1::readback(\\n                    selector, source.snapshot(), prior(&self.config, LearningIterationStageV1::Selection)?,\\n                )"'
        assert text.count(a)==text.count(c)==1
        text=text.replace(a,b).replace(c,d)
    if file.name=='test_original_next_use_command_source_closure.py':
        a='"selector: &self.selector"';b='"selector: OriginalSelector::remote(&self.selector)?"'
        assert text.count(a)==1;text=text.replace(a,b)
    ast.parse(text)
    def methods(value):
        return {(c.name,n.name):ast.get_source_segment(value,n)for c in ast.parse(value).body if isinstance(c,ast.ClassDef)
                for n in c.body if isinstance(n,ast.FunctionDef)and n.name.startswith('test_')}
    bm,am=methods(before),methods(text)
    assert bm.keys()==am.keys(),relative
    for key in bm:
        old_methods[(relative,*key)]=bm[key];new_methods[(relative,*key)]=am[key]
    if text!=before or before!=canonical:
        save(relative,text)
        qa_changes.append({'path':relative,'canonical_before':pin(canonical.encode()),'prepared_input':pin(before.encode()),'after':pin(text.encode()),
                           'original_methods':len(bm),'changed_methods':[list(k)for k in bm if bm[k]!=am[k]],
                           'new_or_removed_methods':[]})
save('OLD_QA_PRESERVATION_REVIEW.json',{'status':'STATIC_ONLY_NOT_EXECUTED','captured_original_files':63,
     'old_method_count':len(old_methods),'old_methods_unchanged':sum(old_methods[k]==new_methods[k]for k in old_methods),
     'changed_methods':[{'path':k[0],'class':k[1],'method':k[2],'before':old_methods[k],'after':new_methods[k]}for k in old_methods if old_methods[k]!=new_methods[k]],
     'new_methods_in_old_files':0,'deleted_methods':0,'files':qa_changes,'boundary_constant_updates':boundary_constants,'scope_hash_updates':scope_updates})
save('QA_CONSTRUCTION_REVIEW.json',{'status':'PREPARED_UNFORMATTED_NOT_QUALIFIED','new_qa_path':new_qa_path,'new_methods':len([n for n in ast.walk(ast.parse(new_qa))if isinstance(n,ast.FunctionDef)and n.name.startswith('test_')]),
     'scope_paths':len(scopes),'scope_count':sum(map(len,scopes.values())),'attack_occurrence_specs':sum(map(len,attacks.values())),
     'all_scope_paths_forced_by_default_method':True,'original_scanner_modified':False,'original_ignore_modified':False,
     'full_source_collector_is_preserved_in_prepared_test':True,'qa_methods_executed':0,'full_source_scans':0,'rust_executions':0})
print((OUT/'QA_CONSTRUCTION_REVIEW.json').read_text())
