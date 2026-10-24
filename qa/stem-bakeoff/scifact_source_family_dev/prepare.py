"""Custodian-side historical source-family partition, never imported by worker."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def normalized(text):
    return " ".join(re.findall(r"\w+", text.lower()))


def families(claims, source_map):
    parent = {c["id"]: c["id"] for c in claims}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    seen, missing = {}, set()
    for claim in claims:
        key = digest(normalized(claim["claim"]).encode())
        sources = source_map.get(key, set())
        if not sources:
            missing.add(claim["id"])
        links = {"text:" + key} | {"paper:" + s for s in sources}
        links |= {"paper:" + str(d) for d in claim["cited_doc_ids"]}
        links |= {"paper:" + str(d) for d in claim["evidence"]}
        for link in sorted(links):
            if link in seen:
                a, b = find(claim["id"]), find(seen[link])
                parent[max(a, b)] = min(a, b)
            seen[link] = claim["id"]
    groups = {}
    for claim in claims:
        groups.setdefault(find(claim["id"]), []).append(claim["id"])
    return [sorted(v) for _, v in sorted(groups.items())], missing


def main():
    plan = json.loads((ROOT / "protocol.json").read_text())
    assert digest((ROOT / "protocol.json").read_bytes()) == (ROOT / "protocol.sha256").read_text().split()[0]
    data = ROOT / "local-data"
    assert digest((data / "data.tar.gz").read_bytes()) == "11c621288d41ac144d29b13b0f8503b3820b7d6e8b1f6ff24dff335c196d76be"
    source_bytes = (data / "citances-local-only.jsonl").read_bytes()
    assert digest(source_bytes) == "a12af8640b5079dc6ceccbf1a31e755b28158643ddd1928f91b92caa0c388704"
    source_map = {}
    for line in source_bytes.splitlines():
        row = json.loads(line)
        for claim in row["claims"]:
            key = digest(normalized(claim["text"]).encode())
            source_map.setdefault(key, set()).add(str(row["s2orc_id"]))
    claims = []
    for name in ["claims_train.jsonl", "claims_dev.jsonl"]:
        claims.extend(json.loads(line) for line in (data / name).read_text().splitlines())
    assert len({c["id"] for c in claims}) == len(claims)
    groups, missing = families(claims, source_map)
    split, assignment = [], {}
    for group in groups:
        group_id = digest((plan["grouping"]["seed"] + "\0" + ",".join(map(str, group))).encode())
        role = "quarantine_unknown_source" if set(group) & missing else "heldout" if int(group_id, 16) % 5 == 0 else "development"
        split.append({"family_id": group_id, "claim_ids": group, "role": role})
        assignment.update({i: (group_id, role) for i in group})
    out = ROOT / "prepared"
    out.mkdir(exist_ok=False)
    (out / "source-paper-map.json").write_text(json.dumps({k: sorted(v) for k, v in sorted(source_map.items())}, indent=2) + "\n")
    (out / "split.json").write_text(json.dumps({"groups": split, "missing_source_claim_ids": sorted(missing), "unobserved_ancestry_independence": None}, indent=2) + "\n")
    selected = [c for c in claims if assignment[c["id"]][1] == "heldout"]
    (out / "worker-queries.jsonl").write_text("".join(json.dumps({"id": c["id"], "claim": c["claim"]}, sort_keys=True) + "\n" for c in selected))
    (out / "custodian-gold.jsonl").write_text("".join(json.dumps({"id": c["id"], "family_id": assignment[c["id"]][0], "evidence": c["evidence"]}, sort_keys=True) + "\n" for c in selected))
    summary = {"claims": len(claims), "observed_families": len(groups), "missing_source_claims": len(missing), "roles": {role: {"families": sum(g["role"] == role for g in split), "claims": sum(len(g["claim_ids"]) for g in split if g["role"] == role)} for role in ["development", "heldout", "quarantine_unknown_source"]}, "heldout_evidence_claims": sum(bool(c["evidence"]) for c in selected), "future_groups": 0}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
