"""Independent frozen-data checks only; never invoke Rust, Cargo, H, or a gate."""
import base64
import collections
import gzip
import json
from pathlib import Path
from inspect_fmt_tokens import HERE, ident, lex
from classify_fmt_items import inventories, groups

PARTS = [
    ('fmt.after.postimages.json.gz.b64.part000', 349529, '57d79a191b6785705d38ec1793a877be11237f77ca03933fdfcfe6ce3929f86f', 'bb27ecb7f6d2d4978be534e1e713c0c427ecd352'),
    ('fmt.after.postimages.json.gz.b64.part001', 170641, '5ba0aa70e2757d4f22499eaa42012252e86ac6d8e86328a2260a163edcda4aae', 'da00d9cd4c72e9931a671fb165c1ea5d233050d2'),
]
INPUT = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-runtime-v1/fmt.after.postimages.json')
REPAIR = Path('/tmp/hepta-36fa-provider-0c59-fix101-repair-v1/SOURCE_PACKET.json')

def pinned(raw, size, sha256, oid):
    value = ident(raw)
    assert value == {'bytes':size, 'sha256':sha256, 'git_blob':oid}, value
    return value

def macro_items(ts):
    pairs, _ = groups(ts)
    result, definitions = [], []
    # Keywords before unary !(...) are not macro paths.
    excluded = {'if','while','return','match','for','let','else'}
    for i,t in enumerate(ts):
        if t[1] == '!' and i > 0 and ts[i-1][0] == 'identifier' and ts[i-1][1] not in excluded and i+1 < len(ts) and ts[i+1][1] in '([{':
            end = pairs[i+1]
            result.append((ts[i-1][1], tuple(x[:2] for x in ts[i+1:end+1])))
        if t[1] == 'macro_rules' and ts[i+1][1] == '!':
            end = pairs[i+3]
            definitions.append(tuple(x[:2] for x in ts[i:end+1]))
    return result, definitions

def main():
    evidence = []
    decoded = []
    for name, size, sha256, oid in PARTS:
        data = (HERE/'input-full-get'/name).read_bytes()
        pin = pinned(data,size,sha256,oid)
        sdk = json.loads((HERE/'input-full-get'/(name+'.GITHUB_GET.original.json')).read_bytes())
        assert sdk['structuredContent']['content'].encode() == data
        decoded.append(base64.b64decode(data.strip(), validate=True))
        evidence.append({'name':name, **pin, 'actual_full_get_equal':True})
    gz = b''.join(decoded)
    gzpin = pinned(gz,390123,'ff2796b5ced568d3fa169e77046e2fea7e9f3f4548790260e0c03ec749ce597b','412d83a525a167ce682e2a0f0e2cfed2769e6192')
    raw = gzip.decompress(gz)
    rawpin = pinned(raw,2175219,'3309f2099b3545737f390f16928d5d085177e72a6e8194aa018fe5039121dc22','43f7dd7eaa1578a4d6d570252939084f80181685')
    assert raw == INPUT.read_bytes()
    packet = json.loads(raw)
    assert packet['stage'] == 'fmt.after'
    assert packet['all_physical_changes_including_untracked_or_ignored_are_recorded'] is True
    assert packet['qualification'] is False
    assert len(packet['changes']) == 62
    root_raw = (HERE/'input-full-get/ROOT_ACTUAL_SOURCE_REVIEW.json').read_bytes()
    assert ident(root_raw)['git_blob'] == '292514377a373b68f5aa7e6b82f08bbe8d2675c8'
    root = json.loads(root_raw)
    assert root['source_leaf_count'] == 15237
    assert root['applied_tree'] == '1eacf738a9ee86fe6b7bf2ab5d20a45d63c066f1'
    assert root['final_physical_tree'] == 'f905b18e6b05de1582024548179725a05d932536'
    assert root['application_inventory_exact_original_pin']['sha256'] == packet['base_inventory_sha256']
    assert root['final_inventory_exact_original_pin']['sha256'] == packet['after_inventory_sha256']
    root_rows = {x['path']:x for x in root['formatter_changes']}
    repair_raw = REPAIR.read_bytes()
    pinned(repair_raw,152573,'84b79dd4fc36e070f57f3de05982cd7a55130b5af67f7890a98ad187a1219300','12a664ce2905feb8107ae66b303c4975f17a9fe3')
    repair = json.loads(repair_raw)
    repair_rows = {x['path']:x for x in repair['changes']}
    commas = json.loads((HERE/'COMMA_CONTEXT_REVIEW.json').read_bytes())
    noncommas = json.loads((HERE/'RESIDUAL_NONCOMMA_HUNKS.json').read_bytes())
    manual_groups = [
        (0,7,'closure_tail_block'),(8,9,'match_tail_block'),(10,11,'match_assignment_tail_block'),
        (12,13,'function_local_use_order'),(14,15,'remove_closure_struct_tail_block'),
        (16,19,'closure_tail_block'),(20,20,'optional_generic_comma_and_joint_closing_angles'),
        (21,23,'match_tail_block_and_argument_comma'),(24,25,'match_tail_block'),
        (26,27,'nested_call_optional_argument_comma'),(28,31,'match_tail_block'),
        (32,33,'closure_tail_block'),(34,37,'match_tail_block'),(38,39,'function_local_use_expansion_and_order'),
        (40,41,'match_tail_block'),(42,43,'closure_tail_block'),(44,45,'nested_call_optional_argument_comma'),
        (46,47,'match_tail_block'),(48,48,'optional_generic_comma_and_joint_closing_angles'),
        (49,51,'function_local_use_expansion'),(52,57,'nested_match_tail_blocks'),
        (58,59,'closure_tail_block'),(60,67,'match_tail_blocks'),(68,71,'closure_tail_blocks'),
        (72,73,'diverging_return_block_and_semicolon'),(74,75,'closure_tail_block'),
    ]
    assignments = {}
    for start,end,label in manual_groups:
        for i in range(start,end+1):
            assert i not in assignments
            assignments[i] = label
    assert set(assignments) == set(range(len(noncommas)))
    rows=[]; macro_changes=[]; macro_counts=collections.Counter(); doc_inner_reordered=[]
    for c in packet['changes']:
        path=c['path']; sides={}
        for side in ('before','after'):
            b=base64.b64decode(c[side+'_raw_base64'],validate=True)
            pin=ident(b)
            assert pin['bytes']==c[side]['bytes'] and pin['sha256']==c[side]['sha256'] and pin['git_blob']==c[side]['working_blob']
            assert b==(HERE/side/path).read_bytes()
            sides[side]=b.decode()
            assert root_rows[path][side] == pin['git_blob']
        a,au,am,_,_,ac=inventories(sides['before'])
        b,bu,bm,_,_,bc=inventories(sides['after'])
        assert collections.Counter(au)==collections.Counter(bu)
        assert collections.Counter(am)==collections.Counter(bm)
        assert [x[:2] for x in ac]==[x[:2] for x in bc]
        assert [x[:2] for x in a if x[0]=='literal']==[x[:2] for x in b if x[0]=='literal']
        # Root use/module removal cannot hide a changed executable numeric literal.
        assert [x[:2] for x in a if x[0]=='number']==[x[:2] for x in b if x[0]=='number']
        assert [a[i+1][:2] for i,x in enumerate(a[:-1]) if x[1]=='fn']==[b[i+1][:2] for i,x in enumerate(b[:-1]) if x[1]=='fn']
        ta,_=lex(sides['before']);tb,_=lex(sides['after'])
        ma,da=macro_items(ta);mb,db=macro_items(tb)
        assert da==db and not da
        assert [x[0] for x in ma]==[x[0] for x in mb]
        macro_diffs=[]
        for i,(x,y) in enumerate(zip(ma,mb)):
            macro_counts[x[0]]+=1
            if x!=y:
                item={'path':path,'index':i,'name':x[0],
                      'before':' '.join(v[1] for v in x[1]),'after':' '.join(v[1] for v in y[1])}
                macro_diffs.append(item);macro_changes.append(item)
        docs=[]
        for ts,cs in ((ta,ac),(tb,bc)):
            docs.append([(x[1],tuple(t[:2] for t in ts if t[2]>=x[3])[:8]) for x in cs if x[1].startswith(('///','//!','/**','/*!'))])
        for x,y in zip(*docs):
            if x!=y:
                assert x[0]==y[0] and x[0].startswith('//!')
                # These are module-level inner docs; following import order is not their attachment.
                doc_inner_reordered.append({'path':path,'doc':x[0]})
        repaired=path in repair_rows
        if repaired:
            assert sides['before']==repair_rows[path]['after_text']
        rows.append({
            'path':path,'before':ident(sides['before'].encode()),'after':ident(sides['after'].encode()),
            'complete_original_bytes_verified':True,'import_leaves_equal_with_visibility_and_attributes':len(au),
            'module_items_equal_with_visibility_and_attributes':len(am),
            'comments_exact_equal':True,'remaining_string_raw_byte_char_literals_exact_equal':True,
            'remaining_numeric_literals_exact_equal':True,'function_declaration_name_sequence_equal':True,
            'raw_nonwhitespace_tokens_exact_equal': [x[:2] for x in ta]==[x[:2] for x in tb],
            'body_tokens_exact_equal_after_root_items': [x[:2] for x in a]==[x[:2] for x in b],
            'macros':len(ma),'macro_internal_token_changes':len(macro_diffs),
            'single_comma_hunks':sum(x['path']==path for x in commas),
            'manual_noncomma_hunks':[{'index':i,'classification':assignments[i]} for i,x in enumerate(noncommas) if x['path']==path],
            'approved_manual_repair_postimage_is_exact_formatter_preimage':True if repaired else None,
            'static_semantic_finding':'No non-formatting change identified in the complete actual transition.'
        })
    assert len(macro_changes)==2
    assert {(Path(x['path']).name,x['name']) for x in macro_changes}=={
        ('authority_host_learning_resident_provider_process_tests.rs','ensure'),
        ('circuit_resident_candidate_first_material_support_tests.rs','vec')}
    assert len(commas)==250 and len(noncommas)==76
    assert root['actual_fix_witness_preserved'] is True
    assert not any(Path(x['path']).name=='witness.rs' for x in packet['changes'])
    out={
        'format':'hepta-actual-fmt62-independent-frozen-byte-and-scope-review-v1',
        'scope':'Pure local evidence/token review. No Rust parser, compiler, source gate, behavioral test, formatter, or H execution.',
        'qualification':False,'actual_fmt_job':'1a1d41eb3ef-392-2b2',
        'parts_actual_full_get':evidence,'gzip':gzpin,'raw_packet':rawpin,
        'raw_packet_storage':'Losslessly reconstructed from two actual full-GET ASCII parts; raw Git identity is not a claimed standalone uploaded blob.',
        'source_head_unchanged':packet['source_commit_unchanged'],
        'baseline_tree':root['applied_tree'],'final_tree':root['final_physical_tree'],
        'base_full_inventory':root['application_inventory_exact_original_pin'],
        'final_full_inventory':root['final_inventory_exact_original_pin'],
        'full_inventory_and_tree_evidence_source':{'review_blob':ident(root_raw),'scope':'Root independently reconstructed all 15237 original inventory rows and exact producer serialization; this reviewer checks the recorded transition bindings, not a second native full inventory transfer.'},
        'approved_manual_repair':ident(repair_raw),'all_four_repaired_preimages_exact':True,
        'witness_not_in_formatter_changes_and_root_full_inventory_confirms_preserved':True,
        'macro_invocation_count':sum(macro_counts.values()),'macro_counts':dict(macro_counts),
        'macro_internal_changes':macro_changes,'macro_definitions':0,
        'outer_doc_following_token_prefixes_equal':True,
        'inner_doc_import_order_context_changes':doc_inner_reordered,
        'single_comma_hunks':250,'manual_noncomma_hunks':76,
        'manual_noncomma_categories':manual_groups,
        'rows':rows,
        'not_claimed':['Compilation success','Behavioral test success','Complete source-gate success','New fix success','Root deployment or external independent utility'],
    }
    encoded=(json.dumps(out,sort_keys=True,indent=2)+'\n').encode()
    with (HERE/'FROZEN_BYTE_AND_SCOPE_REVIEW.json').open('xb') as f:f.write(encoded)
    print(json.dumps({'report':ident(encoded),'files':len(rows),'macro_count':sum(macro_counts.values()),'macro_internal_changes':len(macro_changes),'strict_raw_tokens_equal':sum(x['raw_nonwhitespace_tokens_exact_equal'] for x in rows),'root_item_removed_tokens_equal':sum(x['body_tokens_exact_equal_after_root_items'] for x in rows)}))

if __name__=='__main__':main()
