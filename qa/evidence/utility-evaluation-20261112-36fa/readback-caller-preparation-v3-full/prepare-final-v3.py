#!/usr/bin/env python3
"""Assemble audited original channel registration; no Rust or verifier mutation."""
import ast,difflib,hashlib,importlib.util,json,re,shutil,sys,tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SELECTION=Path("/tmp/hepta-selection-readback-v3-kd2szwua")
spec=importlib.util.spec_from_file_location("artifact_v3_original_verifier",ROOT/"validation-source/scripts/verify_hepta_callers.py")
PROOF=importlib.util.module_from_spec(spec);sys.modules[spec.name]=PROOF;spec.loader.exec_module(PROOF)
AGENT="codex-rs/hepta-agentd/src/"
ART="codex-rs/hepta-learning-artifacts/src/"
CLIENT=AGENT+"artifact_original_head_client.rs"
SERVICE=AGENT+"artifact_original_head_service.rs"
REGISTRY=AGENT+"artifact_original_registry_source.rs"
OWNER=AGENT+"artifact_original_head_owner.rs"
WIRE=AGENT+"artifact_original_head_wire.rs"
CONFIG=ART+"owner_head_source.rs"
DURABLE=ART+"owner_host_registry_durable.rs"
def identity(b):
 return {"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"git_blob_sha":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()}
def code(path):
 return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT/"source-inputs"/path).read_text()))
def item(path,marker):
 text=code(path);assert text.count(marker)==1,(path,marker)
 at=text.index(marker);end=PROOF._rust_item_end(text,at);assert end is not None
 return text[at:end+1]
def exact(path,name):
 marker="fn "+name+"("
 return {"function":marker,"sequence":split_exact(item(path,marker))}
def split_exact(text):
 # The original verifier requires at least two ordered markers. Split only
 # after the declaration keyword: the second marker retains the complete
 # function name/signature/body, so an inserted effect cannot hide in a gap.
 at=text.index(" ")+1
 return [text[:at],text[at:]]
def row(path,required,forbidden,functions,layout=(),extras=()):
 return {"path":path,"required":required,"forbidden":forbidden,
         "required_order":[split_exact(item(path,marker)) for marker in layout]+[split_exact(item(path,marker)) for marker in extras],
         "required_function_order":[exact(path,name) for name in functions]}
KEYLESS=[
 "SigningKey","Signer","SigningKey::generate","SigningKey::from_bytes","UnixStream::connect",
 "UnixListener","File::open","OpenOptions","HostAuthorityPeerChannel::from_stream",
 "LearningOwnerJournalV1::create(","LearningOwnerJournalV1::recover(","commit_once(",
 "OriginalArtifactPreparedPublicationV1 {","from_original_registry_durable(",
 "impl Clone for OriginalArtifactHeadConnectionV1","pub channel:","pub origin:",
 "pub fn bind(","pub(crate) fn bind(","pub fn exchange(","pub(crate) fn exchange(",
 "permit_all","if false",
]
rows=[
 row(CLIENT,[
   "pub struct OriginalArtifactHeadConnectionV1 {","enum Origin {",
   "pub async fn sign_original_registry(","pub async fn read_original_head(",
  ],KEYLESS,
  ["from_original_stream","recover_original_stream","bind","sign_original_registry","read_original_head","exchange"],
  ["enum Origin {","pub struct OriginalArtifactHeadConnectionV1 {"]),
 row(SERVICE,["OriginalArtifactHeadOwnerV1<W>","pub async fn serve_commands("],
  [
   "SigningKey","Signer","SigningKey::generate","SigningKey::from_bytes","File::open","OpenOptions",
   "UnixStream::connect","HostAuthorityPeerChannel::from_stream",
   "OriginalArtifactHeadOwnerV1::create(","OriginalArtifactHeadOwnerV1::recover(",
   "LearningOwnerJournalV1::create(","LearningOwnerJournalV1::recover(",
   "OriginalArtifactPreparedPublicationV1 {","request.payload","request.signing_bytes","permit_all","if false",
  ],["serve_commands"]),
 row(REGISTRY,[
   "pub struct OriginalArtifactRegistrySourceOwnerV1 {",
   "pub struct OriginalArtifactRegistrySourceClientV1 {",
   "pub(super) struct QueueFence(pub(super) Arc<AtomicBool>);",
  ],[
   "wire::Action::Sign","SigningKey","Signer","UnixStream::connect","UnixListener",
   "File::open","OpenOptions","HostAuthorityPeerChannel::from_stream",
   "LearningArtifactOwnerService::open(","LearningArtifactOwnerService::create(",
   "OriginalArtifactPreparedPublicationV1 {","sign_original(","commit_once(",
   "publish_original(","resume_original(","repair_original(","pub writer:","pub channel:",
   "pub fn read_current_in_lane(","pub(crate) fn read_current_in_lane(","permit_all","if false",
  ],["from_original_writer","serve_reads","respond","from_original_stream","read_current","read_current_in_lane","drop"],
  ["pub struct OriginalArtifactRegistrySourceOwnerV1 {","struct Channel {","pub struct OriginalArtifactRegistrySourceClientV1 {"]),
 row(OWNER,[
   "pub struct OriginalArtifactHeadOwnerV1<W: AnchorWitnessStore> {",
   "pub(super) fn sign_original(","pub(super) fn read_original(",
  ],[
   "SigningKey::generate","SigningKey::from_bytes","self.admitted.store(",
   "self.original_key.replace(","self.original_key.get_or_insert","UnixStream::connect",
   "File::open","OpenOptions","pub original_key:","pub admitted:","pub journal:",
   "pub fn sign_original(","pub(crate) fn sign_original(",
   "pub fn read_original(","pub(crate) fn read_original(",
   "permit_all","if false",
  ],["create","recover","sign_original","read_original","require_subject","read_record"],
  ["pub struct OriginalArtifactHeadOwnerV1<W: AnchorWitnessStore> {"]),
 row(WIRE,["pub(super) const MAX_BYTES: usize = 16_384;","const HEADER: usize = 50;",'const MAGIC: &[u8; 8] = b"HARPC001";'],
  ["SigningKey","Signer","File::open","UnixStream::connect","serde_json::Value","permit_all","if false"],
  ["new","encode","decode","response"],
  ["pub(super) enum Purpose {","pub(super) enum Action {","pub(super) enum Status {","pub(super) struct Request {"],
  ["fn read_response<'a>("]),
 row(CONFIG,["pub struct ArtifactHeadSigningConfigV1 {",'b"hepta.original-artifact-head-native.v1"'],
  ["SigningKey","Signer","File::open","UnixStream::connect","permit_all","if false"],
  ["binding","writer_lease_digest","authenticate_current","require_registered_key","unsigned_head",
   "verify_original_head","expected_generation"],
  ["pub struct ArtifactHeadSigningConfigV1 {"]),
 row(DURABLE,[
   "pub struct OriginalArtifactRegistryDurableV1 {",
   "pub(crate) fn read_original_registry_durable(",
  ],[
   "SigningKey","Signer","File::create","OpenOptions","std::fs::write","fs::write",
   "std::fs::rename","fs::rename","UnixStream::connect","permit_all","if false",
   "pub checkpoint:","pub registry:","pub current:","pub writer_lease:",
   "pub trust_digest:","pub observed_unix_millis:",
  ],["authority","same_original_read","read_original_publication_checkpoints",
     "read_original_registry_durable","preparation_head_requirement","read_preparation_current"],
  ["pub struct OriginalArtifactRegistryDurableV1 {"]),
]
def tv(v):
 if isinstance(v,str):return json.dumps(v)
 if isinstance(v,list):return "["+", ".join(map(tv,v))+"]"
 if isinstance(v,dict):return "{ "+", ".join(k+" = "+tv(x) for k,x in v.items())+" }"
 raise TypeError(type(v))
before=(ROOT/"base-v2/CALLERS.toml").read_text()
prior=(SELECTION/"post/CALLERS.toml").read_text()
assert identity(before.encode())["git_blob_sha"]=="317da5f28fbc1cf2556fa5935bb846dce8c7c2cb"
assert identity(prior.encode())["git_blob_sha"]=="d375c16067d212105ebb73d9054fdfe17739e2e3"
base=tomllib.loads(before);selection=tomllib.loads(prior)
for p in (CLIENT,SERVICE,REGISTRY,OWNER,WIRE,CONFIG,DURABLE):
 assert not any(r["path"]==p for r in selection["protected_file"])
identifier="learning_original_owner_command_channel"
at=prior.index('id = "'+identifier+'"');start=prior.rfind("[[boundary]]",0,at)
end=prior.find("\n[[",at);section=prior[start:end]
match=re.search(r"(?m)^product_callers = \[[^\n]*\]",section);assert match
old=next(r["product_callers"] for r in selection["boundary"] if r["id"]==identifier)
assert not set((CLIENT,SERVICE,REGISTRY)).intersection(old)
section=section[:match.start()]+"product_callers = "+tv(old+[CLIENT,SERVICE,REGISTRY])+section[match.end():]
after=prior[:start]+section+prior[end:]
for entry in rows:
 after+="\n[[protected_file]]\n"+"\n".join(k+" = "+tv(v) for k,v in entry.items())+"\n"
parsed=tomllib.loads(after)
assert len(parsed["boundary"])==534 and len(parsed["protected_file"])==399
assert parsed["protected_file"][:390]==base["protected_file"]
changes=[]
for old,new in zip(base["boundary"],parsed["boundary"]):
 assert old["id"]==new["id"]
 if old!=new:
  assert {k:v for k,v in old.items() if k!="product_callers"}=={k:v for k,v in new.items() if k!="product_callers"}
  assert new["product_callers"][:len(old["product_callers"])]==old["product_callers"]
  changes.append({"boundary":old["id"],"field":"product_callers","before":old["product_callers"],"after":new["product_callers"],"added":new["product_callers"][len(old["product_callers"]):]})
assert len(changes)==4 and sum(len(c["added"]) for c in changes)==9
for k in base:
 if k not in ("boundary","protected_file"):assert base[k]==parsed[k]
(ROOT/"post/CALLERS.toml").write_text(after)
(ROOT/"artifact-protected-rows.json").write_text(json.dumps(rows,indent=2)+"\n")
(ROOT/"final-v3-ast-diff.json").write_text(json.dumps({
 "base":identity(before.encode()),"post":identity(after.encode()),
 "existing_boundaries":534,"unchanged_boundary_rows":530,
 "membership_additions":9,"boundary_field_changes":changes,
 "existing_protected_rows_preserved":390,"new_protected_paths":[r["path"] for r in parsed["protected_file"][390:]],
 "protected_count":399,"other_top_level_fields_unchanged":True,
 "artifact_audit_blob":"a36b1e0596a80ebb55aa163fb2719a245fc5f5ee",
 "selection_audit_blob":"7fb2fd1ef668e38163917fcc2b23a2036967566d",
 "production_rust_mutations":[],
},indent=2)+"\n")

# Preserve the original literal text, append only additional members, and leave functions byte-identical.
changed_ids={change["boundary"] for change in changes}
expected={r["id"]:r["product_callers"] for r in parsed["boundary"] if r["id"] in changed_ids}
qa_changes=[]
inputs=list(sorted((ROOT/"base-v2/qa").rglob("*.py")))
extra=SELECTION/"post/qa/b4-no-bypass/test_original_selection_readback_source_closure.py"
inputs.append(extra)
for path in inputs:
 original=path.read_text();tree=ast.parse(original)
 assignment=next((n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="EXPECTED" for t in n.targets)),None)
 if assignment is None or not isinstance(assignment.value,ast.Dict):continue
 offsets=[0]
 for line in original.splitlines(keepends=True):offsets.append(offsets[-1]+len(line))
 replacements=[];fields=[]
 for key,value in zip(assignment.value.keys,assignment.value.values):
  if not isinstance(key,ast.Constant) or key.value not in expected:continue
  old=ast.literal_eval(value);new=expected[key.value]
  if list(old)==new:continue
  assert list(old)==new[:len(old)],(path,key.value)
  additions=new[len(old):]
  a=offsets[value.lineno-1]+value.col_offset;b=offsets[value.end_lineno-1]+value.end_col_offset
  literal=original[a:b];assert literal[-1] in ")]"
  head=literal[:-1].rstrip();tail=literal[len(head):-1]
  sep=" " if head.endswith(",") else ", "
  insertion=", ".join(repr(x) for x in additions)
  if isinstance(old,tuple):insertion+=","
  rendered=head+sep+insertion+tail+literal[-1]
  assert list(ast.literal_eval(rendered))==new
  replacements.append((a,b,rendered))
  fields.append({"boundary":key.value,"before":list(old),"after":new,"added":additions})
 if not replacements:continue
 post=original
 for a,b,replacement in sorted(replacements,reverse=True):post=post[:a]+replacement+post[b:]
 def funcs(text):
  return [(n.name,ast.get_source_segment(text,n),ast.dump(n,include_attributes=False)) for n in ast.walk(ast.parse(text)) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
 assert funcs(original)==funcs(post),path
 def rest(text):
  tree=ast.parse(text)
  return ast.dump(ast.Module(body=[n for n in tree.body if not(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="EXPECTED" for t in n.targets))],type_ignores=[]),include_attributes=False)
 assert rest(original)==rest(post),path
 rel=(path.relative_to(ROOT/"base-v2") if path.is_relative_to(ROOT/"base-v2") else Path("qa/b4-no-bypass")/path.name)
 target=ROOT/"post"/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(post)
 qa_changes.append({"path":str(rel),"base_kind":"v2_or_unchanged_b298" if path.is_relative_to(ROOT/"base-v2") else "selection_only_checkpoint",
 "base":identity(original.encode()),"post":identity(post.encode()),"expected_fields":fields,
 "functions_preserved_byte_for_byte":len(funcs(original)),"function_names":[x[0] for x in funcs(original)],"all_other_ast_unchanged":True})
(ROOT/"final-v3-expected-qa-preservation.json").write_text(json.dumps(qa_changes,indent=2)+"\n")
newrows=parsed["protected_file"][390:]
source_identity=[]
for entry in newrows:
 p=ROOT/"source-inputs"/entry["path"];b=p.read_bytes();target=ROOT/"validation-source"/entry["path"]
 target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b)
 source_identity.append({"path":entry["path"],**identity(b)})
shutil.copyfile(ROOT/"post/CALLERS.toml",ROOT/"validation-source/CALLERS.toml")
checked=PROOF._verify_protected_files(ROOT/"validation-source",{"protected_file":newrows})
(ROOT/"final-v3-nine-protected-diagnostic.json").write_text(json.dumps({
 "status":"passed_scoped_protected_diagnostic","original_function":"_verify_protected_files",
 "protected_paths":checked,"production_rust_mutations":[],"inputs":source_identity,
 "full_caller_status":"not_run","full_gate_status":"not_run","runtime_tests":"not_run",
 "authority_granted":False,
},indent=2)+"\n")
print(json.dumps({"callers":identity(after.encode()),"boundaries":534,"protected":399,"membership_additions":9,
"qa_expected_files":len(qa_changes),"qa_functions_preserved":sum(x["functions_preserved_byte_for_byte"] for x in qa_changes),
"scoped_protected_paths":checked}))
