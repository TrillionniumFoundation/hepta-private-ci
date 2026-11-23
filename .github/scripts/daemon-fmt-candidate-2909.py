"""Compare every original Rust routing decision on the true fixed-base changed-file set."""
from pathlib import Path
from collections import Counter
import gzip
import hashlib
import json
import os
import subprocess
import sys
import types

ROOT = Path.cwd()
OUT = Path(os.environ["RUNNER_TEMP"]) / "daemon-candidate-scope"
BASE = "b8e8c6e82abc1479c573f61a5e17d28d581e6cad"
PRIOR = "c12ee03f3185d5a13949faca54f066dfd634e509"
CAND = "bd4a1979d627a7e934d8aee4ba7bfc8f4d116c9f"
PROJ = "AUDIT/2026-10-20-agent-continuation/cell_p0/sources/2909/codex-rs"
CANONICAL = "scripts/format_provenance/cell-p0-2909/rustfmt.toml"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def load_fmt(ref, name):
    filename = str(ROOT / "scripts/format.py")
    module = types.ModuleType(name)
    module.__file__ = filename
    sys.modules[name] = module
    exec(compile(git("show", f"{ref}:scripts/format.py"), filename, "exec"), module.__dict__)
    return module


def command_vector(c):
    return (c.args, c.cwd)


def main():
    OUT.mkdir(exist_ok=True)
    assert git("rev-parse","HEAD").decode().strip() == CAND
    assert git("rev-parse","HEAD^").decode().strip() == PRIOR
    assert git("status","--porcelain","--untracked-files=all") == b""
    delta=git("diff","--name-only","--no-renames",PRIOR,CAND,"--").decode().splitlines()
    assert set(delta) == {"scripts/format.py","scripts/test_hepta_format_scope.py",CANONICAL}
    assert not git("diff",PRIOR,CAND,"--","AUDIT")
    (OUT/"candidate.diff").write_bytes(git("diff",PRIOR,CAND))
    candidate = load_fmt(CAND,"candidate_fmt"); original = load_fmt(PRIOR,"prior_fmt")
    current = candidate.changed_paths(BASE)
    original_diff = git("diff","--name-only","--diff-filter=ACDMRT","--no-renames","-z",BASE,PRIOR,"--")
    config_names = {"pyproject.toml","ruff.toml",".ruff.toml","rustfmt.toml",".rustfmt.toml"}
    prior=[]
    for entry in original_diff.split(b"\0"):
        if entry:
            p=Path(os.fsdecode(entry))
            if (ROOT/p).is_file() or p.name in config_names:
                prior.append(p.as_posix())
    original_rust=original.rust_configuration_scope(prior)
    candidate_rust=candidate.rust_configuration_scope(current)
    assert original_rust == candidate_rust
    selected = sorted(candidate.WAL_RUST_SOURCES)
    assert len(selected)==2 and set(selected)<=set(candidate_rust)
    old_fail=[]
    for p in original_rust:
        try:
            before=original.rust_file_command(p,check=False)
        except ValueError as err:
            assert p in selected and "owning Rust workspace missing" in str(err)
            old_fail.append(p)
        else:
            after=candidate.rust_file_command(p,check=False)
            assert command_vector(before)==command_vector(after),p
    assert sorted(old_fail)==selected
    groups=candidate.scoped_formatter_groups(current,check=False,base=BASE)
    assert [Path(c.args[-1]).relative_to(ROOT).as_posix() for g in groups if g.name=="Rust" for c in g.commands]==candidate_rust
    (OUT/"selected-rust.json.gz").write_bytes(gzip.compress(json.dumps(candidate_rust).encode(),mtime=0))
    physical={k:hashlib.sha256((ROOT/k).read_bytes()).hexdigest() for k in candidate.WAL_FORMAT_INPUTS}
    assert physical==candidate.WAL_FORMAT_INPUTS
    observed=[]
    for mode in (True,False):
        for path in selected:
            c=candidate.rust_file_command(path,check=mode)
            assert "--check" in c.args and c.args[c.args.index("--edition")+1]=="2024"
            p=subprocess.run(c.args,cwd=c.cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            observed.append({"path":path,"check_mode":mode,"args":list(c.args),"output":p.stdout.decode(),"exit":p.returncode})
            assert p.returncode==0
    assert physical=={k:hashlib.sha256((ROOT/k).read_bytes()).hexdigest() for k in physical}
    (OUT/"plan.json").write_text(json.dumps({"source":CAND,"prior":PRIOR,"base":BASE,"original_changed":len(prior),
        "candidate_changed":len(current),"added":sorted(set(current)-set(prior)),"removed":sorted(set(prior)-set(current)),
        "same_ordered_rust_paths":len(original_rust),"unchanged_other_rust_commands":len(original_rust)-2,
        "original_missing_owners":old_fail,"selected_inputs":physical,"actual_runs":observed,
        "write_mode_groups":{g.name:len(g.commands) for g in groups}},indent=2)+"\n")
    assert git("status","--porcelain","--untracked-files=all")==b""


if __name__=="__main__":
    main()
