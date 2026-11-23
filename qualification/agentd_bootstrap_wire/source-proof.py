"""Read back the one product change and all baseline files used by this observer."""
from hashlib import sha1, sha256
from pathlib import Path
import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument("baseline", type=Path)
parser.add_argument("candidate", type=Path)
parser.add_argument("donor", type=Path)
parser.add_argument("--output", type=Path)
args = parser.parse_args()
p = Path("codex-rs/hepta-agentd/src/authority_host_publication_bootstrap.rs")
old = (args.baseline / p).read_bytes()
new = (args.candidate / p).read_bytes()
donor = args.donor.read_bytes()
base_sha = "fa030952bbeab410c565278000c0449aaf4b40840ec1cad9b477e83634c3b6aa"
new_sha = "57110d846ffd07128830f8ae9c025e3f0f50270d501a3fb4c276594a79589b5a"
assert sha256(old).hexdigest() == base_sha and sha256(new).hexdigest() == new_sha
expect = old
for before, after in [
    (b"Legacy(PublicationBootstrap),", b"Legacy(Box<PublicationBootstrap>),"),
    (b"Durable(PublicationBootstrapV2),", b"Durable(Box<PublicationBootstrapV2>),"),
    (b"            Ok((route, None))", b"            let route = *route;\n            Ok((route, None))"),
    (b"            Ok((value.route, Some(value.prepared)))", b"            let value = *value;\n            Ok((value.route, Some(value.prepared)))"),
]:
    assert expect.count(before) == 1
    expect = expect.replace(before, after)
assert expect == new
assert donor.count(b"            Ok((*route, None))") == 1
assert donor.replace(b"            Ok((*route, None))",b"            let route = *route;\n            Ok((route, None))") == new
names = ["authority_host_publication_bootstrap.rs", "authority_host_generation_publication.rs", "authority_host_original_publication_route.rs",
         "authority_host_generation_publication_root_tests.rs", "authority_host_generation_publication_root_fixture_tests.rs",
         "authority_host_publication_deployment_tests.rs", "authority_host_publication_input_data.rs",
         "authority_host_successor_deployment_files_tests.rs","authority_host_post_a_publication.rs",
         "authority_host_post_a_learning.rs","root_generation_publication_inputs.rs","ordinary_q24_post_a_deployment_tests.rs",
         "ordinary_q24_post_a_process_tests.rs","authority_host_publication_profile_versions_tests.rs"]
rows = {}
for name in [*(p.parent / name for name in names),Path("CALLERS.toml"),Path("qa/b4-no-bypass/test_post_a_physical_preparation_source_closure.py")]:
    data = (args.baseline/name).read_bytes()
    updated = (args.candidate/name).read_bytes()
    assert (data == updated) == (name != p)
    def git_blob(raw):
        return sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    rows[str(name)] = {"base":git_blob(data),"candidate":git_blob(updated)}
out = {"base":"43e5da1bb81369e4e999adfa8558f5ccb5460eb6","candidate":"2b75c8df6b804b87dd8c3cbca8d8a4b37d1d97d4",
       "donor":"24abd04c825cb0d5d0ce27b52ac5008eda13dde4","donor_blob":git_blob(donor),
       "base_sha256":base_sha,"candidate_sha256":new_sha,"files":rows}
text=json.dumps(out,indent=2,sort_keys=True)+"\n"
if args.output: args.output.write_text(text)
else: print(text,end="")
