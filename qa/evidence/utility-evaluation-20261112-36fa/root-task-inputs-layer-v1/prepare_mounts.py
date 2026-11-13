from pathlib import Path
import hashlib
import json

BASE = Path('/tmp/hepta-36fa-root-product-composition-v5/after')
OUT = Path('/tmp/hepta-36fa-root-task-cli-loader-proposal-v1/task-inputs-layer-v1')
P = 'codex-rs/hepta-agentd/src/'

def pins(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}

changes = [
    (P+'authority_host_generation.rs',
     'pub(crate) use input_loader::LoadedOriginalGeneration as OriginalLoadedGeneration;\n',
     '\n#[path = "authority_host_generation_task_input_loader.rs"]\nmod task_input_loader;\npub use task_input_loader::RootHostQ24TaskFilesV1;\npub(crate) use task_input_loader::TaskFilePurpose as OriginalTaskFilePurpose;\n'),
    (P+'authority_host_service.rs',
     'pub(crate) use generation::OriginalLoadedGeneration;\n',
     'pub use generation::RootHostQ24TaskFilesV1;\npub(crate) use generation::OriginalTaskFilePurpose;\n'),
    (P+'authority_host_session_generation_task.rs',
     'pub use root_task::OriginalRootMaterialSourceRegistrationV1;\n',
     '\n#[path = "authority_host_session_generation_task_loader.rs"]\nmod task_input_loader;\n'),
    (P+'lib.rs',
     '#[cfg(target_os = "linux")]\npub use authority_host_service::RootHostInitialGenerationFilesV1;\n',
     '#[cfg(target_os = "linux")]\npub use authority_host_service::RootHostQ24TaskFilesV1;\n'),
]
rows=[]
for name, anchor, addition in changes:
    before=(BASE/name).read_bytes()
    needle=anchor.encode(); extra=addition.encode()
    assert before.count(needle)==1, name
    after=before.replace(needle,needle+extra,1)
    assert after.replace(needle+extra,needle,1)==before
    for root,data in [('before',before),('after',after)]:
        dest=OUT/root/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open('xb') as stream: stream.write(data)
    rows.append({'path':name,'before':pins(before),'after':pins(after),
                 'anchor':anchor,'addition':addition,'exact_inverse':True})
with (OUT/'MOUNT_SPLICES.json').open('x') as stream:
    json.dump({'baseline':str(BASE),'changes':rows,'project_execution':False},stream,indent=2)
    stream.write('\n')
print(json.dumps({'old_paths':len(rows),'all_exact_inverse':True}))
