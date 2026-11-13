from pathlib import Path
import hashlib, json, difflib

ROOT = Path('/tmp/hepta-36fa-same-host-sc-first-poll-increment-v1')
REL = 'codex-rs/hepta-agentd/src/circuit_evaluated_same_host_sc_tests.rs'
BASE = Path('/tmp/hepta-36fa-same-host-sc-tests-proposal-v1/after') / REL

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

before = BASE.read_bytes()
assert pin(before)['git_blob'] == 'a75f2e9b6256a179f6307eab803a9301ef252683'
source = before.decode()
old = '''        let body: anyhow::Result<()> = async {
            let pending = std::future::poll_fn(|cx| std::task::Poll::Ready(
                std::future::Future::poll(request.as_mut(), cx).is_pending()
            )).await;
'''
new = '''        let first_poll = std::future::poll_fn(|cx| std::task::Poll::Ready(
            std::future::Future::poll(request.as_mut(), cx)
        )).await;
        let pending = first_poll.is_pending();
        let body: anyhow::Result<()> = async {
'''
assert source.count(old) == 2
source = source.replace(old, new)
old_overlap = '''        let read = request.await;
        let terminal = gate.wait_for_operation_terminal().await;
        body?;
        terminal?;
        let read = read?;
'''
new_overlap = '''        let read = match first_poll {
            std::task::Poll::Ready(read) => read,
            std::task::Poll::Pending => request.await,
        };
        let terminal = gate.wait_for_operation_terminal().await;
        if !pending {
            // Preserve an early original rejection; a completed future must
            // never be polled again, including during assertion cleanup.
            read.context("the first original S poll completed before the pause")?;
            return body.and(terminal);
        }
        body?;
        terminal?;
        let read = read?;
'''
assert source.count(old_overlap) == 1
source = source.replace(old_overlap, new_overlap)
old_cancel = '''        drop(request);
        gate.release();
        let terminal = gate.wait_for_operation_terminal().await;
        body?;
        terminal?;
'''
new_cancel = '''        drop(request);
        gate.release();
        let terminal = gate.wait_for_operation_terminal().await;
        if let std::task::Poll::Ready(read) = first_poll {
            // An already returned result is not a cancelled delivery. Retain
            // its actual error and still complete the original peer cleanup.
            read.context("the first original S poll completed before cancellation")?;
            return body.and(terminal);
        }
        body?;
        terminal?;
'''
assert source.count(old_cancel) == 1
source = source.replace(old_cancel, new_cancel)
old_expiry = '''        let started = std::time::Instant::now();
        case.export_selection(Duration::from_secs(1)).await?;
'''
new_expiry = '''        case.export_selection(Duration::from_secs(1)).await?;
        let exported = std::time::Instant::now();
'''
assert source.count(old_expiry) == 1
assert source.count('started + Duration::from_millis(1100)') == 1
source = source.replace(old_expiry, new_expiry).replace(
    'started + Duration::from_millis(1100)', 'exported + Duration::from_millis(1100)')
inverse = source.replace(new_expiry, old_expiry).replace(
    'exported + Duration::from_millis(1100)', 'started + Duration::from_millis(1100)')
inverse = inverse.replace(new_cancel, old_cancel).replace(new_overlap, old_overlap).replace(new, old)
assert inverse.encode() == before
after = source.encode()
for kind, raw in [('before', before), ('after', after)]:
    p=ROOT/kind/REL; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(raw)
patch=''.join(difflib.unified_diff(before.decode().splitlines(True),source.splitlines(True),
    fromfile='a/'+REL,tofile='b/'+REL))
(ROOT/'SOURCE_DELTA.patch').write_text(patch)
packet={'format':'hepta-isolated-source-proposal-v1','status':'PREPARED_UNFORMATTED_UNCOMPILED_UNEXECUTED',
    'base_packet':'60c3d1ba12fdf43fd3e06ae5b3c6965e636e84d9',
    'changes':[{'path':REL,'mode':'100644','before':pin(before),'after':pin(after),
                'before_text':before.decode(),'after_text':source}]}
(ROOT/'SOURCE_PACKET.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2)+'\n')
review={'status':'PURE_BYTE_REVIEW_ONLY','base_packet':packet['base_packet'],
        'changes':[{k:v for k,v in packet['changes'][0].items() if not k.endswith('_text')}],
        'inverse_full_file_equal':True,'changed_methods':[
        'local_s_aliases_refuse_real_overlapping_owner_reads',
        'cancelling_local_s_read_fences_all_aliases_after_actual_work_terminates',
        'local_s_clone_keeps_the_original_absolute_expiry'],
        'test_count_unchanged':7,'no_production_file_change':True,
        'preserved':['all original assertion strings and normal-path checks',
                     '500ms actual read/expiry limits and five-second existing fixture observation',
                     'original full first Poll::Ready(Result), without polling completed future again',
                     'actual gate release and worker terminal observation before propagating failures',
                     'outer finish_case and all original peer cleanup',
                     'original one-second capability and 1100ms expiry wait; wait now starts after successful export'],
        'executed_rust_formatter':False,'executed_rust_compiler':False,'executed_tests':False,'H':False}
(ROOT/'STATIC_REVIEW.json').write_text(json.dumps(review,indent=2)+'\n')
print(json.dumps({'path':str(ROOT),'after':pin(after),'packet':pin((ROOT/'SOURCE_PACKET.json').read_bytes()),
                  'patch':pin((ROOT/'SOURCE_DELTA.patch').read_bytes())},indent=2))
