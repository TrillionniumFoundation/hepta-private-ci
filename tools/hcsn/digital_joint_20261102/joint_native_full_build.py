"""Add a new real joint native crate while retaining every old native test.

All old modules come from the exact frozen builder. Explicit, checked overlays
implement only the new task/mass semantics, runtime labels and READ completion
time. Original just fmt/test helpers and original four-crate tests remain.
"""
import hashlib
import json
import os
from pathlib import Path

from . import joint_native_build as hooks

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replace(text, before, after):
    if text.count(before)!=1:
        raise ValueError("joint full owner overlay anchor mismatch: "+before)
    return text.replace(before,after)


def create_joint(old_crate, work, inherited, binding):
    joint=old_crate.parent/"digital-joint-native"; source=joint/"src";source.mkdir(parents=True,exist_ok=True)
    for path in (old_crate/"src").glob("*.rs"):
        inherited.write(source/path.name,path.read_bytes())
    inherited.write(joint/"Cargo.toml",inherited.CRATE.replace("hepta-digital-read-before-native","hepta-digital-joint-native"))
    workspace=work/"codex-rs/Cargo.toml"
    workspace.write_text(replace(workspace.read_text(),'"digital-read-before-native"]','"digital-read-before-native", "digital-joint-native"]'))
    lock=work/"codex-rs/Cargo.lock"; text=lock.read_text();start=text.index('[[package]]\nname = "hepta-digital-read-before-native"');end=text.index('[[package]]',start+1)
    lock.write_text(text[:start]+text[start:end].replace("hepta-digital-read-before-native","hepta-digital-joint-native")+text[start:])
    hooks.overlay(joint)
    for old,new in [("policy.rs","joint_native_policy.rs"),("cell.rs","joint_native_cell.rs"),("task.rs","joint_native_task.rs"),("port.rs","joint_native_port.rs"),("tests.rs","joint_native_full_tests.rs")]:
        inherited.write(source/old,(HERE/new).read_bytes())
    main=source/"main.rs"; text=main.read_text()
    text=replace(text,'        "structured_value" => policy::Controller::StructuredValue,\n','')
    text=replace(text,'#[cfg(test)]\nmod structured_tests;\n','')
    text=text.replace("digital-read-before-native-run-v1","joint-current-due-native-run-v1").replace("digital-read-before-native-error-v1","joint-current-due-native-error-v1")
    text=replace(text,'hard-sampled 17-state finite projection of exported Brownian-image tables; not an exact continuous-path simulation','full conditional 33-state finite CTMC or GRU reconstruction; current-at-due observations; not a continuous Brownian path or production qualification')
    main.write_text(text)
    owner=source/"owner.rs"; text=owner.read_text()
    text=replace(text,'        let mut cell = cell::State::new(self.identity.seed);\n','')
    start=text.index('            if ![0, 4, 5].contains(&entry.action) {');end=text.index('            if let Some(output) = &entry.content {',start);text=text[:start]+text[end:]
    text=replace(text,'                        failure: false,\n                        observation: Some(output.observation),','                        observation_tick: source + 1,\n                        failure: false,\n                        observation: Some(output.observation),')
    text=replace(text,'        if state != self.task || cell != self.cell || content != self.content {','        let cell = cell::State::new(policy, public, &state)?;\n        if state != self.task || cell != self.cell || content != self.content {')
    text=replace(text,'    pub representation_features: [f64; 12],','    pub representation_features: Vec<f64>,')
    text=replace(text,'    pub cell_event: bool,\n    pub draw: Option<cell::Draw>,\n','')
    text=replace(text,'                    cell: cell::State::new(args.seed),','                    cell: cell::State::new(&policy, &public, &task::State::initial())?,')
    text=replace(text,'        let (sparse, config) = runtime::configuration(model, 36);','        let (sparse, config) = runtime::configuration(model, 43);')
    text=replace(text,'            public_features: public_features.clone(),','            public_features: public_features.clone(),\n            public: &self.public,')
    start=text.index('        let mut draw = None;');end=text.index('        let due_source = before.due',start);text=text[:start]+text[end:]
    text=replace(text,'                        failure: false,\n                        observation: Some(result.observation),','                        observation_tick: source + 1,\n                        failure: false,\n                        observation: Some(result.observation),')
    text=replace(text,'                        failure: true,\n                        observation: None,','                        observation_tick: source + 1,\n                        failure: true,\n                        observation: None,')
    text=replace(text,'        candidate.task = before.successor(&self.public, action, completion.as_ref())?;','        candidate.task = before.successor(&self.public, action, completion.as_ref())?;\n        let propagation_start = Instant::now();\n        candidate.cell = cell::State::new(&self.policy, &self.public, &candidate.task)?;\n        costs.propagation_nanos = port::nanos(propagation_start);')
    text=replace(text,'            cell_event: draw.as_ref().is_some_and(|d| d.event),\n            draw,\n','')
    owner.write_text(text.replace("digital-read-before-pair-v1","joint-conditional-pair-v1"))
    runtime=source/"runtime.rs";runtime.write_text(runtime.read_text().replace("finite17","conditional33").replace("preread","current-due"))
    bind_joint(joint,work,binding)


def bind_joint(joint,work,binding):
    source=joint/"src";workspace=work/"codex-rs/Cargo.toml"
    binding.update(joint_sources={p.name:sha(p) for p in sorted(source.glob("*.rs"))},
                   actual_workspace_sha256=sha(workspace),joint_crate_sha256=sha(joint/"Cargo.toml"),
                   fixture_hashes={p.name:sha(p) for p in sorted((HERE/"evidence/development_policy_fixture").glob("*.json"))})


def main():
    original=hooks.FROZEN.read_bytes()
    if hashlib.sha256(original).hexdigest()!=hooks.EXPECTED:
        raise ValueError("frozen inherited builder identity mismatch")
    os.environ["HEPTA_JOINT_GOLDEN_DIR"]=str(HERE/"evidence/development_policy_fixture")
    full_binding={};text=original.decode()
    text=replace(text,'    run(["just", "fmt"])','    joint_create(crate, work, old, FULL_BINDING)\n    run(["just", "fmt"])')
    text=replace(text,'    binding = dict(upstream=ident, generated_sources=generated,','    binding = dict(joint_full_builder_sha256=digest(Path(JOINT_FULL_BUILDER).read_bytes()), joint_hook_builder_sha256=digest(Path(JOINT_HOOK_BUILDER).read_bytes()), full_native=FULL_BINDING, upstream=ident, generated_sources=generated,')
    text=replace(text,'    generated = [dict(path=str(x.relative_to(work)), sha256=digest(x.read_bytes()))','    joint_bind(crate.parent / "digital-joint-native", work, FULL_BINDING)\n    generated = [dict(path=str(x.relative_to(work)), sha256=digest(x.read_bytes()))')
    text=replace(text,'"--release", "-p", "hepta-digital-read-before-native"','"--release", "-p", "hepta-digital-joint-native"')
    text=replace(text,'"codex-hepta-types"]','"codex-hepta-types", "hepta-digital-joint-native"]')
    text=replace(text,'    binary = cargo / "target/release/hepta-digital-read-before-native"','    binary = cargo / "target/release/hepta-digital-joint-native"')
    start,end=text.index("    direct = []\n"),text.index("    binary = cargo / ")
    text=text[:start]+'    direct = []\n    if gate.returncode:\n        raise RuntimeError("real unchanged nextest gate failed; no fallback allowed")\n'+text[end:]
    scope=dict(__file__=str(hooks.FROZEN),__name__="joint_full_inherited_builder",joint_create=create_joint,joint_bind=bind_joint,FULL_BINDING=full_binding,
               JOINT_FULL_BUILDER=str(Path(__file__).resolve()),JOINT_HOOK_BUILDER=str(HERE/"joint_native_build.py"))
    exec(compile(text,str(hooks.FROZEN),"exec"),scope);scope["main"]()


if __name__=="__main__":
    main()
