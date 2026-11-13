from pathlib import Path
import hashlib,json

BASE=Path('/tmp/hepta-36fa-root-product-composition-v5/after')
OUT=Path('/tmp/hepta-36fa-root-task-cli-loader-proposal-v1/task-inputs-layer-v1')
P='codex-rs/hepta-agentd/src/'
assert not (OUT/'MANIFEST.json').exists(), 'immutable layer already frozen'

def pins(b):
    return dict(bytes=len(b),sha256=hashlib.sha256(b).hexdigest(),git_blob=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest())

changes=[
 (P+'authority_host_generation.rs', 'pub(crate) use input_loader::LoadedOriginalGeneration as OriginalLoadedGeneration;\n',
  '\n#[path = "authority_host_generation_task_input_loader.rs"]\nmod task_input_loader;\npub use task_input_loader::RootHostQ24TaskFilesV1;\npub(crate) use task_input_loader::TaskFilePurpose as OriginalTaskFilePurpose;\npub(crate) use task_input_loader::OriginalTaskClockStatus;\n'),
 (P+'authority_host_service.rs', 'pub(crate) use generation::OriginalLoadedGeneration;\n',
  'pub use generation::RootHostQ24TaskFilesV1;\npub(crate) use generation::OriginalTaskFilePurpose;\npub(crate) use generation::OriginalTaskClockStatus;\n'),
 (P+'authority_host_session_generation_task.rs','pub use root_task::OriginalRootMaterialSourceRegistrationV1;\n',
  '\n#[path = "authority_host_session_generation_task_loader.rs"]\nmod task_input_loader;\npub use task_input_loader::PreparedRootHostLoadedQ24TaskV1;\n'),
 (P+'authority_host_session_generation.rs','pub use task::OriginalRootMaterialSourceRegistrationV1;\n',
  'pub use task::PreparedRootHostLoadedQ24TaskV1;\n'),
 (P+'authority_host_session.rs','pub use generation::RootHostInitialTaskInstallationErrorV1;\n',
  'pub use generation::PreparedRootHostLoadedQ24TaskV1;\n'),
 (P+'authority_host_runtime.rs','pub use session::RootHostInitialTaskInstallationErrorV1;\n',
  'pub use session::PreparedRootHostLoadedQ24TaskV1;\n'),
 (P+'lib.rs','#[cfg(target_os = "linux")]\npub use authority_host_service::RootHostInitialGenerationFilesV1;\n',
  '#[cfg(target_os = "linux")]\npub use authority_host_service::RootHostQ24TaskFilesV1;\n'),
 (P+'lib.rs','#[cfg(target_os = "linux")]\npub use authority_host_runtime::RootHostInitialTaskInstallationErrorV1;\n',
  '#[cfg(target_os = "linux")]\npub use authority_host_runtime::PreparedRootHostLoadedQ24TaskV1;\n'),
]
by_path={}
for name,anchor,addition in changes:by_path.setdefault(name,[]).append((anchor,addition))
rows=[]
for name,splices in by_path.items():
    before=(BASE/name).read_bytes();after=before
    for anchor,addition in splices:
        assert after.count(anchor.encode())==1,name
        after=after.replace(anchor.encode(),(anchor+addition).encode(),1)
    inverse=after
    for anchor,addition in reversed(splices):
        assert inverse.count((anchor+addition).encode())==1
        inverse=inverse.replace((anchor+addition).encode(),anchor.encode(),1)
    assert inverse==before,name
    bp=OUT/'before'/name;bp.parent.mkdir(parents=True,exist_ok=True)
    if bp.exists():assert bp.read_bytes()==before
    else:bp.write_bytes(before)
    ap=OUT/'after'/name;ap.parent.mkdir(parents=True,exist_ok=True);ap.write_bytes(after)
    rows.append(dict(path=name,before=pins(before),after=pins(after),splices=[dict(anchor=a,addition=b) for a,b in splices],exact_inverse=True))
with (OUT/'FINAL_MOUNT_SPLICES.json').open('x') as f:json.dump(dict(baseline=str(BASE),changes=rows,project_execution=False),f,indent=2);f.write('\n')
print(json.dumps(dict(paths=len(rows),splices=len(changes),all_exact_inverse=True)))
