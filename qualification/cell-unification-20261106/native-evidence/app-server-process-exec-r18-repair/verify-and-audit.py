from pathlib import Path
import hashlib,json,re,shutil,difflib
r=Path('app-server-process-exec-r18-repair')
native=Path('native-validation-results/r18-blockers/original-input')
def pin(p):
 b=p.read_bytes()
 return {'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def save(name,v):
 p=r/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');return pin(p)
native_manifest=json.loads((native/'source-manifest.json').read_text())
assert pin(native/'source-manifest.json')['sha256']=='4cfe1c080f2c09b4eadb5da65ae212157a10ef064e040dd3dcfa7dfdd735f047'
verified=[]
for item in native_manifest['files']:
 p=native/'source'/item['path']; got=pin(p)
 assert got['bytes']==item['bytes'] and got['sha256']==item['sha256'] and got['git_blob']==item['git_blob'], item['path']
 local=r/'original'/item['path']
 if local.exists(): assert local.read_bytes()==p.read_bytes(),item['path']
 else: local.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,local)
 verified.append({**item,'github_exact_match':item['path'] in [x['path'] for x in json.loads((r/'github-source-input-pins.json').read_text())['files']]})
ev=r/'evidence';ev.mkdir(exist_ok=True)
shutil.copyfile(native/'source-manifest.json',ev/'native-workspace-r18-app-server-blocker-input.json')
closed=Path('native-validation-results/r18-workspace-closed')
receipt_path=closed/'native-workspace-r18-tests-receipt.json'
receipt=json.loads(receipt_path.read_text())
log_path=closed/'native-workspace-r18-tests.log'
resources_path=closed/'native-workspace-r18-tests-resources.txt'
assert pin(log_path)['sha256']==receipt['log_sha256']
assert pin(resources_path)['sha256']==receipt['resources_sha256']
assert receipt['source_tree']==native_manifest['source_tree'] and receipt['exit_code']==101
for p in [receipt_path,resources_path]:shutil.copyfile(p,ev/p.name)
log=log_path.read_bytes()
start=log.index(b'error[E0308]: mismatched types\n')
end=log.index(b'warning: build failed, waiting for other jobs to finish...',start)
failure=log[start:end]
fp=ev/'compiler-failure-block.txt';fp.write_bytes(failure)
assert log.count(b'error[E0308]: mismatched types\n')==1
failure_info={'schema':'hepta.closed-compiler-failure-readback.v1','source_commit':receipt['source_commit'],'source_tree':receipt['source_tree'],'receipt':pin(ev/receipt_path.name),'raw_log':pin(log_path),'resources':pin(ev/resources_path.name),'block':pin(fp),'byte_range_half_open':[start,end],'line_range_inclusive':[log[:start].count(b'\n')+1,log[:end].count(b'\n')],'compiler_error':'E0308','compiler_error_instances':1,'target':'codex-app-server (test all)','phase':'cargo test --no-run','nextest_execution_started':False,'execution_boundary':'原失败发生在编译阶段；没有工作区测试执行计数或新候选资格。'}
save('failure-readback.json',failure_info)
gp=json.loads((r/'github-source-input-pins.json').read_text())
save('source-input-pins.json',{'schema':'hepta.scoped-source-input-pins.v1','source_commit':gp['source_commit'],'source_tree':gp['source_tree'],'github_files':gp['files'],'native_raw_input':pin(ev/'native-workspace-r18-app-server-blocker-input.json'),'native_verified_files':verified,'nearest_instructions':['AGENTS.md'],'scope_note':'原件和调用图均以 source46 为准；原始 helper/fixture 同时与 immutable GitHub raw bytes 一致。'})
p='codex-rs/app-server/tests/suite/v2/process_exec.rs'
before=(r/'original'/p).read_text();after=(r/'source'/p).read_text()
ops=json.loads((r/'edit-operations.json').read_text())['operations']
forward=before
for op in ops:
 assert forward.count(op['before'])==1
 forward=forward.replace(op['before'],op['after'])
assert forward==after
inverse=after
for op in reversed(ops):
 assert inverse.count(op['after'])==1
 inverse=inverse.replace(op['after'],op['before'])
assert inverse==before
assert ''.join(difflib.unified_diff(before.splitlines(keepends=True),after.splitlines(keepends=True),fromfile='a/'+p,tofile='b/'+p)).encode()==(r/'repair.patch').read_bytes()
test_names=re.findall(r'#\[tokio::test\]\nasync fn (\w+)',before)
assert test_names==re.findall(r'#\[tokio::test\]\nasync fn (\w+)',after)
body_marker='    let codex_app_server_protocol::JSONRPCMessage::Response(response) = initialize else {'
assert before[before.index(body_marker):]==after[after.index(body_marker):]
assert before.count('assert')==after.count('assert')
mechanical={'schema':'hepta.scoped-mechanical-readback.v1','forward_exact':True,'inverse_exact':True,'patch_regenerated_exact':True,'changed_paths':[p],'original_assertion_macro_count':15,'candidate_assertion_macro_count':15,'test_functions_unchanged':test_names,'test_function_count':len(test_names),'jsonrpc_response_match_through_file_end_exact':True,'disabled_env_initialize_statement_unchanged':True,'all_non_target_regions_exact_via_inverse':True,'production_and_shared_helper_edits':False,'rust_executed':False,'scope':'字节级正逆回放和原断言保留；不是Rust编译或执行资格。'}
save('MECHANICAL-READBACK.json',mechanical)
audit={'schema':'hepta.app-server-process-initialize-repair-audit.v1','status':'FROZEN_CANDIDATE_NATIVE_GATE_PENDING','source_commit':gp['source_commit'],'source_tree':gp['source_tree'],'changed_files':[p],'candidate_manifest':pin(r/'source-manifest.json'),'patch':pin(r/'repair.patch'),'input_pins':pin(r/'source-input-pins.json'),'failure_readback':pin(r/'failure-readback.json'),'mechanical_readback':pin(r/'MECHANICAL-READBACK.json'),
'observed_failure':{'fact':'r18 原默认工作区门在 cargo test --no-run 失败：process_exec.rs:251 将 unit 返回值匹配为 JSONRPCMessage，rustc E0308。','execution_started':False,'gate_exit_code':101,'classification':'继承 fixture 与既有 helper 返回类型错配；当前两个原文件均与 bef6fa 原始 blob 相同。'},
'causal_chain':[
 {'path':'codex-rs/app-server/tests/common/test_app_server.rs','lines':[324,337],'finding':'initialize() -> anyhow::Result<()> 调用 initialize_with_client_info 后只确认 Response variant，丢弃响应并返回 Ok(())。'},
 {'path':'codex-rs/app-server/tests/common/test_app_server.rs','lines':[339,365],'finding':'既有 initialize_with_client_info(ClientInfo) -> Result<JSONRPCMessage> 保留真实 response/error；复用 process_indeterminate=true、experimental_api=true 与其余默认 capability。'},
 {'path':'codex-rs/app-server/tests/common/test_app_server.rs','lines':[367,416],'finding':'共用 initialize_with_params 发送真实 initialize 请求，读取真实 JSON-RPC，校验 Response/Error request ID；Response 路径发送 Initialized ACK 后返回原消息。'},
 {'path':p,'lines':[242,257],'finding':'initialized_mcp 确实需要读取真实 InitializeResponse.process_indeterminate。删除 Response 匹配或能力断言会丢失原 oracle，故不采用。'}],
'change':{'description':'唯一 initialized_mcp 改调现有 initialize_with_client_info，并传入 initialize() 中原样 ClientInfo 三字段。新增 DEFAULT_CLIENT_NAME 与 ClientInfo 两个 import；不新增 helper。','client_info':{'name':'DEFAULT_CLIENT_NAME.to_string() (same exported constant)','title':None,'version':'0.1.0'},'client_constant':'pub const DEFAULT_CLIENT_NAME: &str = "codex-app-server-tests";','same_capability_defaults':True,'shared_helper_edits':False,'production_edits':False},
'preserved':[
 '全部15个原 assert/assert_eq/assert_ne 宏、4个原顶层 test 函数与原过程命令。',
 'DEFAULT_READ_TIMEOUT 仍包住完整初始化 future，未增加或延长等待。',
 '原 JSONRPCMessage::Response match、非Response bail、InitializeResponse serde 解码和 process_indeterminate 断言全字节不变。',
 '三个 initialized_mcp 调用方沿同一真实 server 握手；disabled-local-env 负例保留原 initialize() unit 调用与错误断言。',
 'process_exec_capability_tests.rs 未改，既有拒绝未协商/通知 opt-out 的负例保留。',
 '没有构造假响应、跳过 request ID 校验/ACK、改生产协议/依赖/runner/filter/ignore。'],
'compatibility':{'rust_source':'仅单 fixture call site 改用现有 public method；公共生产 API 和共用测试 helper 签名均未变化。','wire':'相同 ClientInfo、capability defaults、initialize request path、ID check、Initialized ACK；返回被保留用于原真实响应 oracle。','error_handling':'共用 helper 的传输/解析/ID mismatch 错误继续传播；既有 fixture 的非 Response bail 分支现在可实际接到返回的 Error 消息。'},
'validation':{'native_original_and_github_overlap_exact':True,'native_source_inventory_all_five_files_verified':True,'nearest_agents_read':'AGENTS.md','source_and_patch_byte_inverse':True,'native_compile_or_tests_after_candidate':False,'compiler_behavior_proof':'原闭合 E0308 diagnostic + 精确 helper 签名/返回体静态因果；尚未以新候选原生编译/测试确认。','required_next_step':'由 root 审核/冻结源，再交 native 执行 codex-app-server 原严格检查和完整项目测试；项目门成功后重启完整默认工作区门。'},
'limits':['本审计不是 native gate PASS。','修复仅处理已观察到的单项编译错配，不能据此假定 app-server 或默认工作区其余测试通过。','原 workspace no-run 失败不能当作测试运行失败计数；nextest 未启动。']}
save('repair-audit.json',audit)
index=[]
for x in sorted(r.rglob('*')):
 if x.is_file() and 'original' not in x.parts and 'source' not in x.parts and x.name!='evidence-manifest.json':index.append(pin(x))
save('evidence-manifest.json',{'schema':'hepta.scoped-evidence-manifest.v1','source_candidate_sha256':pin(r/'source'/p)['sha256'],'files':index,'not_execution_evidence':True})
print(json.dumps({'audit':pin(r/'repair-audit.json'),'source_input':pin(r/'source-input-pins.json'),'failure_range':failure_info['byte_range_half_open'],'test_names':test_names,'evidence_manifest':pin(r/'evidence-manifest.json')},indent=2))
