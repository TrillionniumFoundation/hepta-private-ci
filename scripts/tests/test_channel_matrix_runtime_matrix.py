from __future__ import annotations
import hashlib, importlib.util, json, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location("runtime",ROOT/"scripts/channel_matrix_runtime_matrix.py"); assert SPEC and SPEC.loader
M=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)

def write(path:Path,value)->dict:
    data=(json.dumps(value,sort_keys=True)+"\n").encode(); path.write_bytes(data)
    return {"path":path.name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}

class RuntimeMatrixTests(unittest.TestCase):
    def fixture(self,d:Path,postgres=False,omit=None,reuse=False):
        commit="1"*40; tree="2"*40
        profile={"schema":"hepta.channel-matrix-runtime-crash-profile.v1","schemaVersion":1,
                 "storage":{"canonicalOwner":"sqlite","postgresqlRequired":False,"postgresqlSubstitutionForbidden":True},
                 "transport":{"runnerEvidenceSchemaVersion":3},"invariants":["no_duplicate"],
                 "scenarios":[{"id":"a","evidenceClass":"real_synapse","oracles":["one"]},{"id":"b","evidenceClass":"native_process","oracles":["two"]}]}
        profile_path=d/"profile.json"; write(profile_path,profile)
        artifact_set=write(d/"artifact-set.json",{"files":[]}); completion=write(d/"completion.json",{"result":"pass"})
        runner={"schema_version":3,"candidate_sha":commit,"candidate_tree_sha":tree,"artifact_set_sha256":artifact_set["sha256"],"completion_sha256":completion["sha256"],
                "exact_candidate_evidence":True,"test_assertions_passed":True,"durable_artifacts_verified":True,"explicit_process_shutdown_completed":True,"all_historical_product_pids_absent":True,"loopback_proxy_shutdown_completed":True,"loopback_proxy_pid_absent":True,"docker_resources_removed":True,"runtime_root_removed":True,"credential_capabilities_removed":True,"private_fixture_root_removed":True,"promotion":False,"operator_acceptance":False}
        runner_ref=write(d/"runner-evidence.json",runner); supplied=[]
        first_ref=None
        for sid,evidence,oracle in (("a","real_synapse","one"),("b","native_process","two")):
            if sid==omit: continue
            if reuse and first_ref is not None:
                ref=first_ref
            else:
                ref=write(d/f"{sid}.json",{"schema":"hepta.channel-matrix-runtime-scenario.v1","id":sid,"candidate":{"commit":commit,"tree":tree},"storageOwner":"sqlite","evidenceClass":evidence,"result":"pass","oracles":{oracle:True},"claims":{"authorityGranted":False,"productionQualified":False}})
                if first_ref is None: first_ref=ref
            supplied.append({"id":sid,"result":"pass","artifact":ref})
        manifest={"schema":"hepta.channel-matrix-runtime-evidence.v1","candidate":{"commit":commit,"tree":tree},"storageOwner":"sqlite","postgresqlSubstitutionUsed":postgres,"runnerEvidence":runner_ref,"artifactSet":artifact_set,"completion":completion,"scenarios":supplied,"claims":{"productionQualified":False,"activation":False,"promotion":False,"release":False,"authorityGranted":False}}
        manifest_path=d/"manifest.json"; write(manifest_path,manifest)
        return profile_path,manifest_path,commit,tree
    def test_complete_distinct_matrix_passes_but_not_production(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td).resolve(); p,m,c,t=self.fixture(d); row=M.validate(d,m,c,t,p)
            self.assertTrue(row["runtimeMatrixQualified"]); self.assertFalse(row["productionQualified"])
    def test_postgresql_substitution_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td).resolve(); p,m,c,t=self.fixture(d,postgres=True)
            with self.assertRaisesRegex(ValueError,"identity/storage"): M.validate(d,m,c,t,p)
    def test_missing_scenario_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td).resolve(); p,m,c,t=self.fixture(d,omit="b")
            with self.assertRaisesRegex(ValueError,"missing, duplicate or unknown"): M.validate(d,m,c,t,p)
    def test_reused_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td).resolve(); p,m,c,t=self.fixture(d,reuse=True)
            with self.assertRaisesRegex((ValueError),"reused artifact"): M.validate(d,m,c,t,p)
if __name__=="__main__": unittest.main()
