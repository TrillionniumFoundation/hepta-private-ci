"""Prepare a small workspace from pinned, unchanged native repository sources.

This never changes the production Cargo workspace. A full checkout at the
documented source reference supplies the original files; a sparse checkout must
materialize them first. Compilation and just test remain explicit commands.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


CORE=("hepta-types","hepta-infer-core","hepta-neuron","hepta-plasticity")
OWNERS=("hepta-contracts","hepta-ndu","hepta-learning-artifacts","hepta-learning-ledger",
        "hepta-intuition","hepta-memory-retrieval","hepta-cognitive-types","hepta-cognitive-read",
        "hepta-context-compiler","hepta-intelligence-eval","hepta-prompt-optimizer","hepta-prompt-registry",
        "hepta-intelligence","hepta-objective","hepta-wire","hepta-kg")


def prepare(source,output):
    area=Path(__file__).resolve().parent
    catalog=json.loads((area/'UPSTREAM_SOURCE_PINS.json').read_text())
    for item in catalog['files']:
        p=source/item['path']
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('Materialize the exact documented source ref before building: '+item['path'])
    output.mkdir(parents=True,exist_ok=False)
    changes=[]
    for name in CORE+OWNERS:
        for item in catalog['files']:
            path=Path(item['path'])
            if path.parts[:2]!=("codex-rs",name):continue
            relative=path.relative_to(Path('codex-rs')/name)
            destination=output/name/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            raw=(source/path).read_bytes()
            if name in OWNERS and relative==Path('Cargo.toml'):
                raw=re.sub(r'\n\[dev-dependencies\][\s\S]*?(?=\n\[|\Z)','\n',raw.decode()).encode()
                changes.append({'path':str(path),'adaptation':'omit unused dev-dependencies in the isolated dependency mirror'})
            destination.write_bytes(raw)
    bridge=output/'native-owner-bridge';(bridge/'src').mkdir(parents=True)
    for name in ('plasticity_host','plasticity_owner_evidence','plasticity_anchor_journal'):
        shutil.copyfile(source/'codex-rs/hepta-agentd/src'/f'{name}.rs',bridge/'src'/f'{name}.rs')
    (bridge/'src/lib.rs').write_text('mod plasticity_anchor_journal;\nmod plasticity_host;\nmod plasticity_owner_evidence;\npub use plasticity_host::*;\npub use plasticity_owner_evidence::*;\n')
    dependencies=('hepta-intelligence','hepta-learning-artifacts','hepta-learning-ledger',
                  'hepta-plasticity','hepta-types','hepta-ndu','hepta-neuron')
    (bridge/'Cargo.toml').write_text('[package]\nname="codex-native-owner-bridge"\nversion="0.0.0"\nedition="2024"\n[dependencies]\n'
        +''.join('codex-'+name+'={path="../'+name+'"}\n' for name in dependencies)
        +'[dev-dependencies]\ntempfile="=3.27.0"\n')
    harness=output/'native-head';(harness/'src').mkdir(parents=True)
    for p in area.glob('*.rs'):shutil.copyfile(p,harness/'src'/p.name)
    (harness/'Cargo.toml').write_text('[package]\nname="codex-native-head"\nversion="0.0.0"\nedition="2024"\n[dependencies]\n'
        +''.join('codex-'+name+'={path="../'+name+'"}\n' for name in dependencies)
        +'codex-native-owner-bridge={path="../native-owner-bridge"}\nserde={workspace=true,features=["derive"]}\nserde_json={workspace=true}\n'
        +'[[bin]]\nname="codex-native-proposal"\npath="src/proposal.rs"\n')
    members=list(CORE+OWNERS)+['native-owner-bridge','native-head']
    (output/'Cargo.toml').write_text('[workspace]\nmembers='+json.dumps(members)+'\nresolver="2"\n'
        +'[workspace.package]\nversion="0.0.0"\nedition="2024"\nlicense="Apache-2.0"\n[workspace.dependencies]\n'
        +'serde="=1.0.228"\nserde_json="=1.0.149"\nsha2="=0.10.9"\npretty_assertions="=1.4.1"\n'
        +'ed25519-dalek={version="=2.2.0",features=["pkcs8"]}\nrustix="=1.1.4"\nzeroize="=1.8.2"\n'
        +'codex-hepta-types={path="hepta-types"}\n[workspace.lints]\n[profile.dev]\ndebug=0\n'
        +'[profile.test]\ndebug=0\n[profile.release]\ndebug=0\n')
    shutil.copyfile(source/'codex-rs/Cargo.lock',output/'Cargo.lock')
    # These are the original local/default settings. Overrides concerning packages
    # absent from this deliberately small workspace cannot parse in nextest.
    (output/'nextest-scoped.toml').write_text('[profile.default]\nslow-timeout={period="30s",terminate-after=2}\n'
        +'retries=1\n[profile.default.junit]\npath="junit.xml"\n[profile.local]\ninherits="default"\n')
    receipt={'upstream_ref':catalog['ref'],'source_catalog_sha256':hashlib.sha256((area/'UPSTREAM_SOURCE_PINS.json').read_bytes()).hexdigest(),
             'production_rust_source_modified':False,'manifest_adaptations':changes,
             'harness_sources':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in area.glob('*.rs')},
             'build_scope':'22 local library/harness crates; original Agentd host modules, no App Server or fleet daemon'}
    (output/'preparation-receipt.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    print(json.dumps(receipt,sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[4])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();prepare(args.source,args.output)
