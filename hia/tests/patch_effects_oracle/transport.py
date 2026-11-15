"""Check conservative committed-delta handling for native transport errors.

Only a selected planner call returns the documented no-write INVALID status.
All filesystem operations use the real LocalFileSystem. The other planner
calls forward unchanged to the actual production static archive.
"""
import hashlib
from pathlib import Path

from file_update_oracle import cargo


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(rustc, graph, env, commands, library_dir, producer, output):
    output.mkdir()
    fixtures = output / "fixtures"
    fixtures.mkdir()
    source = Path(__file__).with_name("transport_error_driver.rs")
    driver_hash = sha(source)
    binary = output / "native-transport-error-observer"
    flags = cargo.flags(rustc, graph, original=False)
    flags += ["-L", "native=" + str(library_dir)]
    for module in ("seek_sequence", "source_file", "file_update", "parser", "patch_effects"):
        flags += ["-l", "static=codex_hia_" + module]
    commands.run("compile-native-transport-observer", flags + [
        "--crate-name", "patch_effects_transport_observer",
        "-C", "link-arg=-Wl,--wrap=codex_hia_patch_effects", source, "-o", binary,
    ], cwd=producer / "codex-rs", env=env)
    symbols = commands.run("native-transport-observer-symbols", [
        "nm", "--defined-only", binary,
    ], cwd=producer, env=env).read_text()
    assert " __wrap_codex_hia_patch_effects\n" in symbols
    assert " codex_hia_patch_effects\n" in symbols
    report = {"passed": False, "cases": [], "driver_sha256": driver_hash,
              "observer_sha256": sha(binary),
              "scope": "Declared native transport error at seven selected planner calls; real unchanged filesystem callbacks in 14 public API scenarios."}
    repo = producer
    cases=[
    ('add',0,'success',True,1,6,None,None,b'new\n'),
    ('add',5,'error',False,0,5,None,None,b'new\n'),
    ('delete',0,'success',True,1,7,None,None,None),
    ('delete',6,'error',False,0,6,None,None,None),
    ('inplace',0,'success',True,1,6,None,b'new\n',None),
    ('inplace',5,'error',False,0,5,None,b'new\n',None),
    ('move',0,'success',True,1,11,None,None,b'new\n'),
    ('move',8,'error',False,0,8,None,b'old\n',b'new\n'),
    ('move',10,'error',False,1,10,None,None,b'new\n'),
    ('prefix',0,'success',True,2,11,b'first\n',None,b'new\n'),
    ('prefix',10,'error',False,1,10,b'first\n',None,b'new\n'),
    ('update-missing',0,'error',True,0,4,None,None,None),
    ('delete-missing',0,'error',False,0,5,None,None,None),
    ('add',1,'error',False,0,1,None,None,None)]
    for i,(scenario,fail,status,exact,count,calls,first,source_bytes,target) in enumerate(cases):
     fixture=fixtures/str(i)
     raw=commands.run('transport-public-case-'+str(i),[binary,fixture,scenario,str(fail)],cwd=repo/'codex-rs',env=env).read_text()
     observation={}
     for line in raw.splitlines():
      key,value=line.split('=',1);assert key not in observation;observation[key]=value
     assert observation['status']==status and observation['delta_exact']==str(exact).lower() and int(observation['delta_changes'])==count,(scenario,fail,observation)
     assert int(observation['planner_call_attempts'])==calls and int(observation['native_forwarded_calls'])==calls-(1 if fail else 0),(scenario,fail,observation)
     for name,wanted in [('first.txt',first),('source.txt',source_bytes),('target.txt',target)]:
      assert observation['file_'+name]==('absent' if wanted is None else wanted.hex()),(scenario,fail,name,observation)
      path=fixture/name;assert (not path.exists()) if wanted is None else path.read_bytes()==wanted
     error=bytes.fromhex(observation.get('error_hex','')).decode()
     if fail:assert 'HIA patch_effects: native ABI rejected request (4294967295)' in error and observation['stdout_hex']==''
     if status=='success':assert b'Success.' in bytes.fromhex(observation['stdout_hex']) and observation['stderr_hex']==''
     if scenario=='move' and fail==10:
      text=bytes.fromhex(observation['delta_hex']).decode();assert 'change: Add' in text and 'change: Update' not in text
     report['cases'].append({'scenario':scenario,'transport_error_ordinal':fail,'observations':observation,'actual_post_files_verified':True})
    assert sha(source) == driver_hash and sha(binary) == report["observer_sha256"]
    report["actual_processes"] = len(cases)
    report["planner_call_attempts"] = sum(int(row["observations"]["planner_call_attempts"]) for row in report["cases"])
    report["real_native_forwarded_calls"] = sum(int(row["observations"]["native_forwarded_calls"]) for row in report["cases"])
    assert report["actual_processes"] == 14
    assert report["planner_call_attempts"] == 95
    assert report["real_native_forwarded_calls"] == 88
    report["passed"] = True
    return report
