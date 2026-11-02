"""Extend the exact frozen builder without editing any inherited source file.

The only generated Rust changes are one hook module/declaration and three
exact-anchor hook calls. The inherited real just test gate must pass; no fake
nextest or replacement test driver is introduced.
"""
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
FROZEN = HERE.parent/"digital_read_followup_20261101/native_build.py"
EXPECTED = "d01d4c0ab2d421fab34f3945c8576f66fcc3a044d664ae23a8dad265de799a4e"


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError("frozen overlay anchor mismatch")
    return text.replace(before, after)


def overlay(crate):
    source = crate/"src"
    (source/"joint_fault.rs").write_bytes((HERE/"joint_native_fault.rs").read_bytes())
    main = source/"main.rs"
    main.write_text(replace_once(main.read_text(), "mod owner;", "mod owner;\nmod joint_fault;"))
    owner = source/"owner.rs"; text = owner.read_text()
    call = 'crate::joint_fault::hit({stage}, &self.snapshot, &self.pair.identity.mode, {calls}, {opens})?;'
    text = replace_once(text, "        let mut costs = decision.costs.clone();",
                        "        "+call.format(stage='"after_native_tick"', calls=0, opens=0)+"\n        let mut costs = decision.costs.clone();")
    text = replace_once(text, "        candidate.task = before.successor(&self.public, action, completion.as_ref())?;",
                        "        if due_source.is_some() {\n            "+call.format(stage='"after_due_read"', calls="read_audit.model_executions", opens="read_audit.successful_opens")+"\n        }\n        candidate.task = before.successor(&self.public, action, completion.as_ref())?;")
    text = replace_once(text, "        costs.persist_nanos += port::nanos(persist_start);",
                        "        "+call.format(stage='"after_child_commit"', calls="read_audit.model_executions", opens="read_audit.successful_opens")+"\n        costs.persist_nanos += port::nanos(persist_start);")
    owner.write_text(text)


def main():
    original = FROZEN.read_bytes()
    if hashlib.sha256(original).hexdigest() != EXPECTED:
        raise ValueError("frozen inherited builder identity mismatch")
    text = original.decode()
    text = replace_once(text, '    run(["just", "fmt"])', '    joint_overlay(crate)\n    run(["just", "fmt"])')
    text = replace_once(text, "    binding = dict(upstream=ident, generated_sources=generated,",
                        "    binding = dict(joint_builder_sha256=digest(Path(JOINT_BUILDER).read_bytes()), upstream=ident, generated_sources=generated,")
    start, end = text.index("    direct = []\n"), text.index("    binary = cargo / ")
    text = text[:start] + '    direct = []\n    if gate.returncode:\n        raise RuntimeError("real unchanged just test gate failed; no fallback allowed")\n' + text[end:]
    # The inherited source digest now also binds this overlay builder; the new
    # Rust module and every generated hook call are bound as generated_sources.
    scope = dict(__file__=str(FROZEN), __name__="joint_inherited_builder",
                 joint_overlay=overlay, JOINT_BUILDER=str(Path(__file__).resolve()))
    exec(compile(text, str(FROZEN), "exec"), scope)
    scope["main"]()


if __name__ == "__main__":
    main()
