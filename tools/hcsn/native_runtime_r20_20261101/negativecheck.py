"""Independent context-loss, paid-pending and actual-token interventions."""
import json
from pathlib import Path
import shutil
import socket
import struct

import numpy as np
from scipy.linalg import expm

from .independentcheck import digest, fnv, identify, owned, save, seal, unseal, verify, wait_path


def request(endpoint, text):
    host, port = endpoint.read_text().strip().split(":")
    data = seal(text).encode()
    with socket.create_connection((host, int(port)), timeout=4) as stream:
        stream.sendall(struct.pack(">I", len(data)) + data)
        def exact(length):
            result = b""
            while len(result) < length:
                part = stream.recv(length - len(result))
                if not part:
                    raise EOFError("lost provider response")
                result += part
            return result
        return unseal(exact(struct.unpack(">I", exact(4))[0]))


def clone(source, target, states=True):
    target.mkdir(parents=True)
    for name in ("MODEL", "PLAN", "CATALOG", "REFERENCE.json") + (("owner.state", "provider.state") if states else ()):
        shutil.copyfile(source / name, target / name)
    return dict(directory=target)


def run(binary, source, output, processes):
    world = json.loads((source / "REFERENCE.json").read_text())
    rows = []
    for label, missing, expected in (("missing_owner", "owner.state", "missing owner state with paid effects"),
                                     ("missing_provider", "provider.state", "owner provider ledger gap"),
                                     ("corrupt_owner", None, "checksum mismatch")):
        d = output / label
        paths = clone(source, d)
        if missing:
            (d / missing).unlink()
        else:
            text = (d / "owner.state").read_text()
            (d / "owner.state").write_text(text.replace("STATE\t", "STXTE\t", 1))
        p = processes.start(binary, "provider", paths, "none", "provider")
        wait_path(d / "ENDPOINT")
        before = (d / "provider.state").read_bytes()
        o = processes.start(binary, "owner", paths, "none", "owner")
        assert processes.wait(o) == 2 and expected in (d / "owner.stderr").read_text()
        assert (d / "provider.state").read_bytes() == before
        processes.wait(p, kill=True)
        rows.append(dict(case=label, passed=True, provider_unchanged=True))

    for label in ("changed_model", "changed_plan", "duplicate_opid"):
        d = output / label
        paths = clone(source, d)
        model = (d / "MODEL").read_text()
        lines = unseal((d / "PLAN").read_text()).splitlines()
        if label == "changed_model":
            fields = model.split()
            fields[-1], fields[-2] = fields[-2], fields[-1]
            model = " ".join(fields) + "\n"
            (d / "MODEL").write_text(model)
            h = lines[0].split("\t")
            h[2] = identify(binary, d / "MODEL")
            lines[0] = "\t".join(h)
        else:
            fields = lines[1 if label == "changed_plan" else 4].split("\t")
            fields[3 if label == "changed_plan" else 4] = "110000001" if label == "changed_plan" else "paid1"
            lines[1 if label == "changed_plan" else 4] = "\t".join(fields)
        (d / "PLAN").write_text(seal("\n".join(lines) + "\n"))
        o = processes.start(binary, "owner", paths, "none", "owner")
        assert processes.wait(o) == 2
        assert ("duplicate opid" if label == "duplicate_opid" else "owner context") in (d / "owner.stderr").read_text()
        rows.append(dict(case=label, passed=True))

    for label in ("changed_catalog", "corrupt_provider", "invalid_catalog_token"):
        d = output / label
        paths = clone(source, d, states=label != "invalid_catalog_token")
        if label == "corrupt_provider":
            text = (d / "provider.state").read_text()
            (d / "provider.state").write_text(text.replace("EFFECT\t", "XFFECT\t", 1))
            expected = "checksum mismatch"
        else:
            lines = unseal((d / "CATALOG").read_text()).splitlines()
            fields = lines[1].split("\t")
            fields[3] = str((int(fields[3]) + 1) % 5) if label == "changed_catalog" else "5"
            lines[1] = "\t".join(fields)
            (d / "CATALOG").write_text(seal("\n".join(lines) + "\n"))
            expected = "provider context" if label == "changed_catalog" else "catalog operation"
        p = processes.start(binary, "provider", paths, "none", "provider")
        assert processes.wait(p) == 2 and expected in (d / "provider.stderr").read_text()
        rows.append(dict(case=label, passed=True))

    d = output / "changed_executable"
    paths = clone(source, d)
    alternate_binary = output / "alternate_artifact"
    alternate_binary.write_bytes(binary.read_bytes() + b"\nR20 nonexecuted artifact-identity control\n")
    alternate_binary.chmod(0o755)
    old_plan = (d / "PLAN").read_bytes()
    unchanged_provider = (d / "provider.state").read_bytes()
    old_id = unseal(old_plan).splitlines()[0].split("\t")[2]
    new_id = identify(alternate_binary, d / "MODEL", "ALTERNATE_IDENTIFY")
    assert new_id != old_id
    o = processes.start(alternate_binary, "owner", paths, "none", "alternate_old_plan")
    assert processes.wait(o) == 2 and "plan model binding" in (d / "alternate_old_plan.stderr").read_text()
    rows.append(dict(case="changed_artifact_rejects_old_plan", passed=True,
                     original_model_id=old_id, alternate_model_id=new_id,
                     alternate_sha256=digest(alternate_binary.read_bytes()),
                     scope="ELF with trailing nonexecuted control bytes; artifact binding, not a semantic-change or cryptographic test."))
    data = unseal(old_plan).splitlines()
    fields = data[0].split("\t")
    fields[2] = new_id
    data[0] = "\t".join(fields)
    (d / "PLAN").write_text(seal("\n".join(data) + "\n"))
    o = processes.start(alternate_binary, "owner", paths, "none", "alternate_new_plan")
    assert processes.wait(o) == 2 and "owner context" in (d / "alternate_new_plan.stderr").read_text()
    assert (d / "provider.state").read_bytes() == unchanged_provider
    rows.append(dict(case="changed_artifact_rejects_owned_checkpoint", passed=True, provider_unchanged=True))

    d = output / "identical_artifact_relocated"
    paths = clone(source, d)
    copied_binary = output / "identical_artifact"
    shutil.copyfile(binary, copied_binary)
    copied_binary.chmod(0o755)
    copied_id = identify(copied_binary, d / "MODEL", "COPIED_IDENTIFY")
    assert copied_id == unseal((d / "PLAN").read_bytes()).splitlines()[0].split("\t")[2]
    unchanged_owner, unchanged_provider = (d / "owner.state").read_bytes(), (d / "provider.state").read_bytes()
    p = processes.start(binary, "provider", paths, "none", "provider")
    wait_path(d / "ENDPOINT")
    o = processes.start(copied_binary, "owner", paths, "none", "owner")
    assert processes.wait(o) == 0
    assert (d / "owner.state").read_bytes() == unchanged_owner
    assert (d / "provider.state").read_bytes() == unchanged_provider
    processes.wait(p, kill=True)
    rows.append(dict(case="identical_artifact_relocated", passed=True, owner_and_provider_unchanged=True))

    d = output / "bound_retries"
    paths = clone(source, d)
    p = processes.start(binary, "provider", paths, "none", "provider")
    wait_path(d / "ENDPOINT")
    before = (d / "provider.state").read_bytes()
    h = unseal(before).splitlines()[0].split("\t")
    binding = "\t".join(h[1:4])
    cached = request(d / "ENDPOINT", f"CALL\t{binding}\t1\tpaid1\tREAD\t25\n")
    assert cached.strip() == unseal(before).splitlines()[1]
    for query in (f"CALL\t{binding}\t1\tpaid1\tREAD\t26\n", "SYNC\t" + "0" * 64 + "\t0\t0\n"):
        assert request(d / "ENDPOINT", query).startswith("ERR\t")
    host, port = (d / "ENDPOINT").read_text().strip().split(":")
    for malformed in (struct.pack(">I", 65537), struct.pack(">I", 1) + b"x"):
        with socket.create_connection((host, int(port)), timeout=3) as stream:
            stream.sendall(malformed)
            stream.shutdown(socket.SHUT_WR)
            assert stream.recv(1) == b""
    assert request(d / "ENDPOINT", f"SYNC\t{binding}\n").startswith("STATUS\t")
    assert (d / "provider.state").read_bytes() == before
    processes.wait(p, kill=True)
    rows.append(dict(case="bound_retry_and_bad_frames", passed=True, malformed_frames=2, provider_unchanged=True))

    d = output / "zero_evidence_paid_pending"
    paths = clone(source, d, states=False)
    fields = (d / "MODEL").read_text().split()
    numbers = np.array(list(map(float, fields[1:])))
    read = numbers[1600:1800].reshape(40, 5)
    read[:, 0] = 0
    read[:, 1:] = .25
    model = "HCSN_FINITE_40_V1\n" + " ".join(format(x, ".17e") for x in numbers) + "\n"
    (d / "MODEL").write_text(model)
    lines = unseal((d / "PLAN").read_text()).splitlines()
    h = lines[0].split("\t")
    model_id = identify(binary, d / "MODEL")
    h[2] = model_id
    lines[0] = "\t".join(h)
    plan = seal("\n".join(lines) + "\n")
    (d / "PLAN").write_text(plan)
    lines = unseal((d / "CATALOG").read_text()).splitlines()
    lines[0] = f"CATALOG\t{world['run']}\t{model_id}\t{fnv(plan.encode()):016x}"
    lines[1] = "TOKEN\t1\tpaid1\t0"
    (d / "CATALOG").write_text(seal("\n".join(lines) + "\n"))
    p = processes.start(binary, "provider", paths, "none", "provider")
    wait_path(d / "ENDPOINT")
    o = processes.start(binary, "owner", paths, "none", "owner")
    assert processes.wait(o) == 2 and "zero or underflowed receipt evidence" in (d / "owner.stderr").read_text()
    oh = owned(d)["header"]
    ph = unseal((d / "provider.state").read_text()).splitlines()[0].split("\t")
    assert oh[4:8] == ["1", "110000000", "0", "1"] and ph[5:7] == ["1", "25"]
    processes.wait(p, kill=True)
    rows.append(dict(case="zero_evidence_paid_pending", passed=True, paid_provider_micros=25,
                     applied_owner_micros=0, durable_pending_index=1, billing_scope="Providerpaid pending cost is separate from applied-owner charge; no successful completion claimed."))

    d = output / "changed_actual_token"
    paths = clone(source, d, states=False)
    q, emission = np.array(world["q"]), np.array(world["read"])
    prior = np.array(world["reference"][-2]) @ expm(q * .09)
    candidates = []
    original = int(world["tokens"]["6"])
    for token in range(5):
        weighted = prior * emission[:, token]
        if token != original and weighted.sum() > 0:
            posterior = weighted / weighted.sum()
            candidates.append((float(np.max(abs(posterior - world["reference"][-1]))), token, posterior))
    delta, token, posterior = max(candidates, key=lambda row: row[0])
    assert delta > .01
    lines = unseal((d / "CATALOG").read_text()).splitlines()
    lines[-1] = f"TOKEN\t6\tpaid6\t{token}"
    (d / "CATALOG").write_text(seal("\n".join(lines) + "\n"))
    alternate = dict(world)
    alternate["tokens"] = dict(world["tokens"], **{"6":token})
    alternate["reference"] = world["reference"][:-1] + [posterior.tolist()]
    save(d / "ALTERNATE_REFERENCE.json", alternate)
    p = processes.start(binary, "provider", paths, "none", "provider")
    wait_path(d / "ENDPOINT")
    o = processes.start(binary, "owner", paths, "none", "owner")
    assert processes.wait(o) == 0
    result = verify(d, alternate)
    assert result["owner_sha256"] != digest((source / "owner.state").read_bytes())
    processes.wait(p, kill=True)
    rows.append(dict(case="actual_token_changes_native_posterior", passed=True,
                     public_model_and_plan_unchanged=True, maximum_posterior_change=delta, **result))
    save(output / "RESULT.json", dict(passed=True, cases=rows, case_count=len(rows),
         source_sha256=digest(Path(__file__).read_bytes()), scope="Independent valid counterfactual and invalid-state/context cases, no hostile-writer/authentication claim."))
    return rows
