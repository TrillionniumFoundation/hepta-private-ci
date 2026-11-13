#!/usr/bin/env python3
"""Root actual d256 index/record review from original fixed-version SDKs, no H."""
import base64,hashlib,json,pathlib,struct,zlib
ROOT=pathlib.Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
RUN=pathlib.Path('/tmp/hepta-36fa-coordinator-a489-materializer-runtime-v1')
EXPECTED=pathlib.Path('/tmp/hepta-36fa-coordinator-final-candidate-graph-v1/expected-inventory-v1/EXPECTED_CLEAN_INVENTORY.json')
def identity(raw):
 return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
def equal_pin(raw,p):
 assert identity(raw)=={k:p[k] for k in ('bytes','sha256','git_blob')}
result_raw=(RUN/'RESULT.json').read_bytes()
assert identity(result_raw)['git_blob']=='30ab4aad6ff10942063da972e02db49629e3809c'
result=json.loads(result_raw)
review_raw=(RUN/'ACTUAL_ARTIFACT_READBACK_REVIEW.json').read_bytes()
review=json.loads(review_raw);assert review['job_id']=='1a1d468462a-392-3bb'
retained={};observations=[];sdk_count=0
for record in review['records']:
 output=b''
 for row in record['original_sdk_ranges']:
  original=(RUN/row['name']).read_bytes();equal_pin(original,row)
  sdk=json.loads(original);assert sdk['isError'] is False
  seen=json.loads(sdk['content'][0]['text'])
  assert seen['path']==record['native_path'] and seen['version']==record['actual_version']
  assert seen['offset']==row['offset']==len(output)
  part=base64.b64decode(seen['data_base64'],validate=True)
  assert hashlib.sha256(part).hexdigest()==seen['chunk_sha256']
  assert seen['next_offset']==row['next_offset']==len(output)+len(part)
  output+=part;sdk_count+=1
 assert seen['eof'] is True and seen['size']==len(output)
 equal_pin(output,record['actual_full_read'])
 assert record['full_coverage']==[0,len(output)]
 name=record['actual_full_read']['name']
 assert output==(RUN/name).read_bytes()
 retained[name]=output
 if 'decompressed_actual_read' in record:
  decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
  body=decoder.decompress(output)+decoder.flush()
  assert decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
  equal_pin(body,record['decompressed_actual_read'])
  decoded_name=record['decompressed_actual_read']['name']
  assert body==(RUN/decoded_name).read_bytes();retained[decoded_name]=body
 observations.append({'path':record['native_path'],'version':record['actual_version'],'chunks':len(record['original_sdk_ranges']),'full':identity(output)})
raw=retained['final.new-index.raw'];compressed=retained['final.new-index.raw.gz']
equal_pin(raw,result['current_index']['raw'])
metadata=retained['final.git-metadata.json'];equal_pin(metadata,result['current_git_metadata'])
assert json.loads(retained['final.new-index-check.json'])==result['current_index']
assert json.loads(retained['SOURCE_COORDINATION_EX.json'])==result['coordination_lock']
assert result['current_source_before']==result['current_source_after']
assert result['current_git_state_before']==result['current_git_state_after']
assert result['donor_git_state_before']==result['donor_git_state_after']
assert raw[:4] == b"DIRC"
version, count = struct.unpack_from(">II", raw, 4)
assert version == 2 and count == 15243
assert hashlib.sha1(raw[:-20]).digest() == raw[-20:]
expected_raw = EXPECTED.read_bytes()
equal_pin(expected_raw, result["current_source_after"]["inventory"])
expected = json.loads(expected_raw)
expected_rows = {row["path"]: row for row in expected["files"]}
assert len(expected_rows) == count
offset = 12
paths = []
modes = {}
for _ in range(count):
    start = offset
    fields = struct.unpack_from(">10I20sH", raw, offset)
    mode, uid, gid, size, oid, flags = fields[6], fields[7], fields[8], fields[9], fields[10], fields[11]
    assert not flags & 0xF000
    end = raw.index(b"\0", offset + 62)
    path_raw = raw[offset + 62:end]
    path = path_raw.decode("utf-8", "strict")
    assert flags & 0xFFF == min(len(path_raw), 0xFFF)
    offset = start + ((end + 1 - start + 7) // 8) * 8
    assert raw[end:offset] == b"\0" * (offset - end)
    row = expected_rows[path]
    assert oid.hex() == row["index_blob"] == row["working_blob"]
    assert format(mode, "o") == row["index_mode"]
    assert size == row["bytes"] and uid == gid == 1000
    assert fields[0] > 0 and fields[2] > 0 and fields[4] == 2050 and fields[5] > 0
    paths.append(path_raw)
    modes[format(mode, "o")] = modes.get(format(mode, "o"), 0) + 1
assert paths == sorted(paths) and len(set(paths)) == count
assert {p.decode("utf-8") for p in paths} == set(expected_rows)
extensions = []
while offset < len(raw) - 20:
    name = raw[offset:offset + 4]
    size = struct.unpack_from(">I", raw, offset + 4)[0]
    body = raw[offset + 8:offset + 8 + size]
    assert len(body) == size
    extensions.append({"name": name.decode("ascii"), "bytes": size})
    if name == b"TREE":
        zero = body.index(b"\0")
        line_end = body.index(b"\n", zero + 1)
        root_count, child_count = map(int, body[zero + 1:line_end].split())
        assert body[:zero] == b"" and root_count == count
        assert body[line_end + 1:line_end + 21].hex() == result["source_tree"]
    offset += 8 + size
assert offset == len(raw) - 20
assert extensions == [{"name": "TREE", "bytes": 68848}]
report={
 'format':'hepta-root-d256-actual-index-and-artifact-read-review-v1','qualification':False,'result':identity(result_raw),
 'native_actual_readback_review':identity(review_raw),'raw_index':identity(raw),'gzip_index':identity(compressed),
 'git_metadata':identity(metadata),'complete_native_artifact_paths':len(observations),'original_binary_read_SDKs':sdk_count,
 'observations':observations,'index_version':version,'entries':count,'all_paths_modes_blob_ids_sizes_equal_actual_bound_frozen_inventory':True,
 'all_stage_assume_unchanged_extended_flags_zero':True,'uid_gid_1000_and_device_2050':True,'footer_checksum_and_cache_tree_verified':True,
 'extensions':extensions,'mode_counts':modes,'expected_inventory_pin':identity(expected_raw),
 'actual_current_and_donor_git_state_before_after_equal':True,
 'source_of_index':'Actual complete native gzip read, decompressed; not synthesized from expected inventory.',
 'stat_scope':'Original producer checked actual H file stat fields. Root independently parsed actual index and checked logical fields; Root did not rescan H.',
 'integer_handling':'All actual native JSON in this verification is parsed with Python integers. A preliminary JS diagnostic display of RESULT was not reused for any original or derived native-stat evidence.',
 'H_calls':0,'source_mutations':0,'real_authorized_task_chains':0}
out=ROOT/'ROOT_D256_ACTUAL_INDEX_REVIEW.json'
out.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
print(json.dumps({'result':'ACTUAL_INDEX_AND_FIXED_VERSION_ARTIFACTS_VERIFIED','report':identity(out.read_bytes()),'entries':count,'read_SDKs':sdk_count,'modes':modes}))
