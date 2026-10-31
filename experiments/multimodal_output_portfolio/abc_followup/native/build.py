"""Original pinned native crates, plus separate research lifecycle drivers."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from ...abc_next.native.build import prepare


def build(source,output):
    prepare(source,output)
    area=Path(__file__).parent; harness=output/"native-head"
    for name in ("continuous.rs","future_head.rs","future_head_tests.rs","stream_io.rs","ledger_probe.rs","proposal.rs","dynamics_profile.rs","dynamics_profile_tests.rs","dynamics_probe.rs","dynamics_stress.rs","parameter_geometry.rs","proposal_hook.rs"):
        shutil.copyfile(area/name,harness/"src"/name)
    manifest=harness/"Cargo.toml"
    text=manifest.read_text().replace('codex-hepta-learning-ledger={path="../hepta-learning-ledger"}',
        'codex-hepta-learning-ledger={path="../hepta-learning-ledger",features=["qualification-legacy-write"]}')
    text+='\n[[bin]]\nname="codex-native-continuous"\npath="src/continuous.rs"\n'
    text+='\n[[bin]]\nname="codex-native-dynamics-probe"\npath="src/dynamics_probe.rs"\n'
    text+='\n[[bin]]\nname="codex-native-dynamics-stress"\npath="src/dynamics_stress.rs"\n'
    manifest.write_text(text)
    receipt={"schema":"hepta.abc4.native-build.v1","production_sources_modified":False,
        "previous_preparation_sha256":hashlib.sha256((output/"preparation-receipt.json").read_bytes()).hexdigest(),
        "new_research_source_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in area.glob("*.rs")},
        "qualification_legacy_write":"original feature used only for unsigned actual-observation diagnostic; not a production trust path",
        "original_crate_dependencies":"same pinned release versions, original source bytes; no full Agentd/fleet composition"}
    (output/"followup-preparation.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    print(json.dumps(receipt))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("source","output"):parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args();build(args.source,args.output)
