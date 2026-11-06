#!/usr/bin/env python3
"""Read-only decoder for the fixed Bazel 9.3.0 compact ExecLogEntry evidence.

The original compressed artifact is never modified. Field numbers are bound to
primary/spawn.proto. This projection retains every Spawn field and every raw
entry count; source files and original ZIP remain authority.
"""
import collections, hashlib, json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent
COMPACT = ROOT / "artifacts/windows-shard4-original/execution-log-test-test-windows-shard-3686.zst"

def varint(data, pos=0):
    n = 0
    for k in range(10):
        if pos >= len(data): raise ValueError("truncated_varint")
        b = data[pos]; pos += 1
        n |= (b & 127) << (7 * k)
        if not b & 128: return n, pos
    raise ValueError("varint_overflow")

def fields(data):
    out = collections.defaultdict(list)
    pos = 0
    while pos < len(data):
        tag, pos = varint(data, pos)
        no, wire = tag >> 3, tag & 7
        if no == 0: raise ValueError("zero_field_number")
        if wire == 0: value, pos = varint(data, pos)
        elif wire == 1:
            value = data[pos:pos+8]; pos += 8
            if len(value) != 8: raise ValueError("truncated_fixed64")
        elif wire == 2:
            size, pos = varint(data, pos)
            value = data[pos:pos+size]; pos += size
            if len(value) != size: raise ValueError("truncated_bytes")
        elif wire == 5:
            value = data[pos:pos+4]; pos += 4
            if len(value) != 4: raise ValueError("truncated_fixed32")
        else: raise ValueError("unsupported_wire_type")
        out[no].append((wire, value))
    return out

def scalar(f, no, default=0):
    a = f.get(no)
    if not a: return default
    if len(a) != 1 or a[0][0] != 0: raise ValueError("scalar_wire_or_repetition")
    return a[0][1]

def strs(f, no):
    a = f.get(no, [])
    if any(w != 2 for w, _ in a): raise ValueError("string_wire")
    return [v.decode("utf-8", "strict") for _, v in a]

def string(f, no, default=""):
    a = strs(f, no)
    if len(a) > 1: raise ValueError("string_repetition")
    return a[0] if a else default

def msgs(f, no):
    if any(w != 2 for w, _ in f.get(no, [])): raise ValueError("message_wire")
    return [fields(v) for _, v in f.get(no, [])]

def msg(f, no):
    a=msgs(f,no)
    if len(a)>1: raise ValueError("message_repetition")
    return a[0] if a else {}

def signed(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v

def digest(f):
    return {"hash":string(f,1), "size_bytes":scalar(f,2), "hash_function_name":string(f,3)}

def file_data(f):
    return {"path":string(f,1), "digest":digest(msg(f,2))}

def duration(f):
    return {"seconds":signed(scalar(f,1),64), "nanos":signed(scalar(f,2),32)}

def metrics(f):
    names={1:"total_time",2:"parse_time",3:"network_time",4:"fetch_time",5:"queue_time",
      6:"setup_time",7:"upload_time",8:"execution_wall_time",9:"process_outputs_time",
      10:"retry_time",11:"input_bytes",12:"input_files",13:"memory_estimate_bytes",
      14:"input_bytes_limit",15:"input_files_limit",16:"output_bytes_limit",
      17:"output_files_limit",18:"memory_bytes_limit",19:"time_limit",20:"start_time",
      21:"measured_memory_peak_bytes"}
    if set(f) - set(names): raise ValueError("unknown_metrics_field")
    return {names[n]:duration(msg(f,n)) if n<=10 or n in (19,20) else scalar(f,n) for n in f}

def repeated_uint(f, no):
    out=[]
    for wire, value in f.get(no,[]):
        if wire==0: out.append(value)
        elif wire==2:
            pos=0
            while pos<len(value):
                n,pos=varint(value,pos);out.append(n)
        else: raise ValueError("packed_wire")
    return out

def output(f, entries):
    if 5 in f:
        n=scalar(f,5)
        if n not in entries: raise ValueError("forward_or_missing_output")
        return {"entry_id":n, **entries[n]}
    if 4 in f: return {"invalid_output_path":string(f,4)}
    raise ValueError("output_type_missing")

def spawn(f, entries):
    if set(f)-set(range(1,19)): raise ValueError("unknown_spawn_field")
    env=[{"name":string(e,1),"value":string(e,2)} for e in msgs(f,2)]
    platform=[{"name":string(p,1),"value":string(p,2)} for p in msgs(msg(f,3),1)]
    return {"args":strs(f,1),"env_vars":env,"platform":platform,
      "input_set_id":scalar(f,4),"tool_set_id":scalar(f,5),
      "outputs":[output(o,entries) for o in msgs(f,6)],
      "target_label":string(f,7),"mnemonic":string(f,8),
      "exit_code":signed(scalar(f,9),32),"status":string(f,10),
      "runner":string(f,11),"cache_hit":bool(scalar(f,12)),
      "remotable":bool(scalar(f,13)),"cacheable":bool(scalar(f,14)),
      "remote_cacheable":bool(scalar(f,15)),"digest":digest(msg(f,16)),
      "timeout_millis":scalar(f,17),"metrics":metrics(msg(f,18))}

def decode():
    p = subprocess.run(["zstd","-q","-d","-c","--no-pass-through","--",str(COMPACT)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False)
    if p.returncode != 0: raise ValueError("zstd_decompression_failed")
    data=p.stdout
    pos=0; count=0; entries={}; spawns=[]; invocation=[]; types=collections.Counter()
    while pos<len(data):
        size,pos=varint(data,pos); raw=data[pos:pos+size]; pos+=size
        if len(raw)!=size: raise ValueError("truncated_delimited_record")
        f=fields(raw); entry_id=scalar(f,1)
        payload=[n for n in f if n!=1]
        if len(payload)!=1: raise ValueError("entry_oneof_count")
        typ=payload[0]; types[typ]+=1; g=msg(f,typ); count+=1
        if typ==2:
            d={"type":"invocation","hash_function_name":string(g,1),
               "workspace_runfiles_directory":string(g,2),
               "sibling_repository_layout":bool(scalar(g,3)),"invocation_id":string(g,4)}
            invocation.append(d)
        elif typ==3: d={"type":"file",**file_data(g)}
        elif typ==4:
            d={"type":"directory","path":string(g,1),
               "files":[file_data(x) for x in msgs(g,2)]}
        elif typ==5: d={"type":"unresolved_symlink","path":string(g,1),"target_path":string(g,2)}
        elif typ==6:
            d={"type":"input_set","input_ids":repeated_uint(g,5),"transitive_set_ids":repeated_uint(g,4)}
        elif typ==7:
            d={"type":"spawn","sequence":count,**spawn(g,entries)}; spawns.append(d)
        elif typ==8:
            d={"type":"symlink_action","input_path":string(g,1),"output_path":string(g,2),
               "target_label":string(g,3),"mnemonic":string(g,4)}
        elif typ==9:
            d={"type":"symlink_entry_set","direct_entries":
               [{"path":string(x,1),"entry_id":scalar(x,2)} for x in msgs(g,1)],
               "transitive_set_ids":repeated_uint(g,2)}
        elif typ==10:
            d={"type":"runfiles_tree","path":string(g,1),"input_set_id":scalar(g,2),
               "symlinks_id":scalar(g,3),"root_symlinks_id":scalar(g,4),
               "empty_files":strs(g,5),"repo_mapping_manifest":file_data(msg(g,6))}
        else: raise ValueError("unknown_entry_type")
        if entry_id:
            if entry_id in entries: raise ValueError("duplicate_nonzero_id")
            entries[entry_id]=d
    if len(invocation)!=1: raise ValueError("invocation_count")
    test_spawns=[s for s in spawns if s["mnemonic"]=="TestRunner"]
    core=[s for s in test_spawns if s["target_label"]=="//codex-rs/core:core-all-test"]
    summary={"schema":"hepta-compact-9.3.0-read-only-projection-v1",
      "compressed":{"bytes":COMPACT.stat().st_size,"sha256":hashlib.sha256(COMPACT.read_bytes()).hexdigest()},
      "decompressed_bytes":len(data),"record_count":count,"type_counts":dict(sorted(types.items())),
      "nonzero_entry_count":len(entries),"invocation":invocation[0],
      "spawn_count":len(spawns),"test_runner_count":len(test_spawns),
      "test_runner_runner_cache_counts":dict(collections.Counter(
        f'{s["runner"]}|cache_hit={s["cache_hit"]}' for s in test_spawns)),
      "core_test_runner_count":len(core),
      "core_test_runner_exit_counts":dict(collections.Counter(s["exit_code"] for s in core)),
      "core_test_runner_runner_cache_counts":dict(collections.Counter(
        f'{s["runner"]}|cache_hit={s["cache_hit"]}' for s in core)),
      "core_timeout_millis":sorted({s["timeout_millis"] for s in core}),
      "limits":["Projection does not turn cached results into native execution.",
                "Absent spawns may reflect persistent action-cache hits; do not infer their execution.",
                "Original ZIP, full compact bytes, fixed proto, and this decoder are retained."]}
    target=ROOT/"derived";target.mkdir(exist_ok=True)
    for name,value in [("compact-summary.json",summary),("compact-core-test-runners.json",core),
                       ("compact-all-test-runners.json",test_spawns)]:
        (target/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    # Keep input relationships needed for an independently replayable runfiles investigation.
    needed=set()
    def visit(n):
        if not n or n in needed:return
        if n not in entries:raise ValueError("missing_input_reference")
        needed.add(n); d=entries[n]
        for key in ("input_ids","transitive_set_ids"):
            for x in d.get(key,[]):visit(x)
        for key in ("input_set_id","symlinks_id","root_symlinks_id"):
            visit(d.get(key,0))
        for x in d.get("direct_entries",[]):visit(x["entry_id"])
    for s in core:
        visit(s["input_set_id"]);visit(s["tool_set_id"])
    relationships={str(n):entries[n] for n in sorted(needed)}
    (target/"compact-core-input-relationships.json").write_text(
        json.dumps(relationships,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=="__main__": decode()
