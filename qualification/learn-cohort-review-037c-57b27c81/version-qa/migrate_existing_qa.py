"""Keep old attack suites while moving only actual guards/caller expectations."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import tomllib

ROOT=Path(__file__).resolve().parent
HOME=ROOT.parent
BASE=ROOT/"base/qa/b4-no-bypass"
AFTER=ROOT/"overlay/qa/b4-no-bypass"
manifest=tomllib.loads((ROOT/"overlay/CALLERS.toml").read_text())
boundaries={r["id"]:r for r in manifest["boundary"]}
original_manifest=tomllib.loads((ROOT/"base/CALLERS.toml").read_text())
original={r["id"]:r for r in original_manifest["boundary"]}
files=("test_evaluated_published_read_source_closure.py","test_evaluated_retention_source_closure.py","test_retained_version_issuer_source_closure.py")
changes=[]
for name in files:
    before=BASE/name
    if not before.exists():
        source=HOME/"profile-evaluated-read-guards-4ab-v1/overlay/qa/b4-no-bypass"/name
        shutil.copyfile(source,before)
    text=before.read_text();tree=ast.parse(text);lines=text.splitlines(keepends=True);offset=[0]
    for line in lines:offset.append(offset[-1]+len(line))
    edits=[]
    for node in ast.walk(tree):
        if not isinstance(node,ast.Dict):continue
        for key,value in zip(node.keys,node.values):
            if not isinstance(key,ast.Constant) or key.value not in boundaries or not isinstance(value,(ast.Tuple,ast.List)):continue
            expected=tuple(boundaries[key.value]["product_callers"])
            old=eval(compile(ast.Expression(value),"<closed caller literal>","eval"),{"__builtins__":{}},{"AGENT":"codex-rs/hepta-agentd/src/","HOST":"codex-rs/hepta-agentd/src/circuit_retained_version_host.rs","WORKER":"codex-rs/hepta-agentd/src/circuit_retained_version_issuer.rs","SERVICE":"codex-rs/hepta-agentd/src/circuit_retained_version_service.rs","CONTEXT":"codex-rs/hepta-agentd/src/circuit_evaluated_retention_context.rs","REMOTE":"codex-rs/hepta-agentd/src/circuit_evaluated_selection_remote.rs","SELECTOR":"codex-rs/hepta-agentd/src/circuit_selection_receipt_owner.rs"})
            assert tuple(old)==tuple(original[key.value]["product_callers"]),(name,key.value,old)
            if tuple(old)==expected:continue
            a=offset[value.lineno-1]+value.col_offset;b=offset[value.end_lineno-1]+value.end_col_offset
            edits.append((a,b,repr(expected)));changes.append({"path":"qa/b4-no-bypass/"+name,"boundary":key.value,"before":list(old),"after":list(expected)})
    for a,b,replacement in sorted(edits,reverse=True):text=text[:a]+replacement+text[b:]
    if name=="test_evaluated_published_read_source_closure.py":
        old='            (READINESS, "read_original_readiness"),\n'
        assert text.count(old)==1;text=text.replace(old,"",1)
        anchor='        for marker in ("LearningIterationObservationV1::TrainingNoUpdateV2(_)"'
        at=text.index(anchor)
        text=text[:at]+'''        # Both explicit public protocols now call the same private physical
        # Source/Cell read. Their legacy/evaluated purpose gates stay separate.
        self.rejects(READINESS, "read_original_readiness", "self.context.decision()?")
        self.rejects_unused_body(READINESS, "read_original_readiness")
'''+text[at:]
    if name=="test_retained_version_issuer_source_closure.py":
        assert text.count('"publish_and_retain_original_trainer(",')==1
        text=text.replace('"publish_and_retain_original_trainer(",','"original.publish(signed)",',1)
        anchor='        self.reject_each(EFFECT, "run_original_c", ('
        at=text.index(anchor)
        text=text[:at]+'''        # The actual owned legacy publication moved into the private enum.
        # Preserve the old consuming call attack at its new active location.
        self.reject_each(AGENT + "circuit_retained_version_prepared.rs", "publish", (
            "self,", "PreparedOriginalCircuitRetainedPublicationV1::publish_and_retain_original_trainer(",
            "*original, signed,",
        ))
'''+text[at:]
    (AFTER/name).write_text(text)
(ROOT/"evidence/QA_CALLER_MIGRATIONS.json").write_text(json.dumps(changes,indent=2)+"\n")
print(json.dumps({"files":list(files),"exact_caller_changes":len(changes)}))
