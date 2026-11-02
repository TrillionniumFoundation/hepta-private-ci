"""Pre-confirmation engineering fixture: no model fitting or generated worlds."""
import hashlib
import json
from pathlib import Path
import numpy as np
from . import joint_campaign


def main():
    here = Path(__file__).resolve().parent
    protocol = json.loads((here/"joint_protocol.json").read_bytes())
    aggregate = {}
    for split in ("iid", "ood"):
        for family in protocol["families"]:
            aggregate[split+"/"+family+"/value"] = [dict(fit=f, utility=0.,
                full_execution_cpu_seconds=1., wall_p95_seconds=1., serial_service_throughput=1.)
                for f in protocol["fits"]]
    result = joint_campaign.adoption(aggregate, protocol)
    try:
        json.dumps(result,allow_nan=False)
        error = None
    except TypeError as exception:
        error = str(exception)
    assert error is not None
    types = {key: type(value).__module__+"."+type(value).__name__
             for key,value in next(iter(result.values()))["gates"].items()}
    # Demonstrate the only required normalization, without changing candidate
    # source, monkey-patching it, or executing a confirmation world.
    normalized = json.loads(json.dumps(result, allow_nan=False,
        default=lambda x: bool(x) if isinstance(x,np.bool_) else (_ for _ in ()).throw(TypeError(type(x).__name__))))
    for name,row in result.items():
        assert normalized[name]["passed"] == row["passed"]
        assert all(normalized[name]["gates"][k] == bool(v) for k,v in row["gates"].items())
    report = dict(schema="joint-preconfirmation-serialization-audit-v1", no_confirmation_worlds_generated=True,
        candidate_campaign_sha256=hashlib.sha256(Path(joint_campaign.__file__).read_bytes()).hexdigest(),
        audit_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        original_standard_json_writable=False, error=error, gate_types=types,
        boolean_only_normalization_roundtrip=True,
        scope="engineering output defect; dummy five-fit aggregates, no efficacy observation or candidate source mutation")
    path = here/"joint_independent_audit_serialization.json"
    with path.open("x") as stream:
        json.dump(report,stream,indent=2,sort_keys=True); stream.write("\n")
    print(json.dumps(report,sort_keys=True))


if __name__ == "__main__":
    main()
