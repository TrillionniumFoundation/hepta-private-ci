from pathlib import Path
import hashlib, sys
p=Path(sys.argv[1])/'codex-rs/hepta-agentd/src'
here=Path(__file__).parent
names=['authority_host_publication_deployment_tests.rs','authority_host_generation_publication_root_fixture_tests.rs','authority_host_successor_deployment_files_tests.rs']
def edit(name, changes):
    file=p/name
    source=file.read_text()
    for old,new in changes:
        assert source.count(old)==1, (name,old)
        source=source.replace(old,new)
    file.write_text(source)
edit(names[0],[("        original_paths: &[PathBuf; 5],","        wire_offer: &crate::RootGenerationPublicationOfferV1,\n        original_paths: &[PathBuf; 5],"),
               ("        let material = RootGenerationPublicationDeploymentV1::encode_original_material(","        check_bootstrap_wire(wire_offer, &descriptor, &path)?;\n        let material = RootGenerationPublicationDeploymentV1::encode_original_material(")])
with (p/names[0]).open('a') as fp: fp.write((here/'observe.rs').read_text())
edit(names[1],[("            &deployment_directory,\n            &[","            &deployment_directory,\n            &publication,\n            &[")])
with (p/names[2]).open('a') as fp: fp.write('''
impl crate::authority_host_runtime::PreparedPublicationData {
    pub(crate) fn component_successor_wire_fixture() -> serde_json::Result<Value> {
        serde_json::to_value(fixture())
    }
}
''')
for name in names:
    print(hashlib.sha256((p/name).read_bytes()).hexdigest(), name)
