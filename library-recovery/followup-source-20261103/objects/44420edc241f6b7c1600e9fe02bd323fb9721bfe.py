"""Independent local repro of the sharding function extracted from PR #2059.
Does not run Rust or imply hosted CI passed.
"""
import hashlib
import json
import unittest
from pathlib import Path
import zipfile


def deterministic_shard(selected: dict, index: int, count: int) -> dict:
    """Partition the complete exact-graph set without dropping any native test."""
    if (type(index) is not int or type(count) is not int
            or not 1 <= count <= 4 or not 0 <= index < count):
        raise ValueError("invalid bounded Cargo impact shard")
    packages = selected["packages"]
    if packages != sorted(set(packages)):
        raise ValueError("noncanonical full Cargo impact package list")
    if selected["full_workspace"] and count != 1:
        raise ValueError("full workspace fallback cannot be silently sharded")
    parts = [packages[i::count] for i in range(count)]
    if sorted(p for part in parts for p in part) != packages:
        raise ValueError("Cargo impact shards lost or duplicated packages")
    return {
        "index": index,
        "count": count,
        "packages": parts[index],
        "full_selected_packages": len(packages),
        "coverage_digest": hashlib.sha256(
            json.dumps(packages, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def execution_command(
    selected: dict, action: str, *, shard: dict | None = None
) -> list[str] | None:
    """Apply one exact-revision impact plan to each native check."""
    target = selected["packages"] if shard is None else shard["packages"]
    if action == "plan" or not target:
        return None
    packages = []
    if not selected["full_workspace"]:
        for package in target:
            packages.extend(["-p", package])
    if action == "test":
        return [
            "just",
            "test",
            "--locked",
            *(["--workspace"] if selected["full_workspace"] else packages),
        ]
    if action == "fmt":
        return [
            "cargo",
            "fmt",
            *(["--all"] if selected["full_workspace"] else packages),
            "--",
            "--check",
        ]
    if action == "clippy":
        return [
            "cargo",
            "clippy",
            "--locked",
            *(["--workspace"] if selected["full_workspace"] else packages),
            "--all-targets",
            "--",
            "-D",
            "clippy::correctness",
        ]
    raise ValueError("unknown native check")

class NativeShardReproTests(unittest.TestCase):
    def test_exact_hosted_package_inventories(self):
        cases = [('/mnt/data/hepta-owner-native-ci-impact.zip', 134, [34,34,33,33]),
                 ('/mnt/data/hepta-preflight-native-ci-impact.zip', 135, [34,34,34,33])]
        for p, size, expected in cases:
            with self.subTest(p=p):
                with zipfile.ZipFile(p) as z:
                    selected=json.loads(z.read('cargo-impact.json'))
                self.assertEqual(len(selected['packages']), size)
                shards=[deterministic_shard(selected,i,4) for i in range(4)]
                self.assertEqual([len(s['packages']) for s in shards],expected)
                self.assertEqual(sorted(x for s in shards for x in s['packages']),selected['packages'])
                self.assertEqual(len({x for s in shards for x in s['packages']}),size)
                self.assertEqual(len({s['coverage_digest'] for s in shards}),1)
                selected_by_commands=[]
                for shard in shards:
                    cmd=execution_command(selected,'test',shard=shard)
                    self.assertEqual(cmd[:3],['just','test','--locked'])
                    self.assertEqual(cmd[3::2],['-p']*len(shard['packages']))
                    selected_by_commands += cmd[4::2]
                self.assertEqual(sorted(selected_by_commands),selected['packages'])

    def test_wrong_shard_bounds_rejected(self):
        chosen={'packages':['a','b'],'full_workspace':False}
        for i,n in [(-1,4),(4,4),(0,0),(0,5),(1,1)]:
            with self.assertRaises(ValueError):deterministic_shard(chosen,i,n)

    def test_unsorted_and_duplicate_names_rejected(self):
        for names in [['b','a'],['a','a']]:
            with self.assertRaises(ValueError):deterministic_shard({'packages':names,'full_workspace':False},0,4)

    def test_fallback_rejected_but_one_full_is_accepted(self):
        chosen={'packages':['a','b'],'full_workspace':True}
        with self.assertRaises(ValueError):deterministic_shard(chosen,0,4)
        self.assertEqual(execution_command(chosen,'test',shard=deterministic_shard(chosen,0,1)), ['just','test','--locked','--workspace'])

    def test_small_inventory(self):
        chosen={'packages':['only'],'full_workspace':False}
        p=[deterministic_shard(chosen,i,4) for i in range(4)]
        self.assertEqual([x['packages'] for x in p],[['only'],[],[],[]])
        self.assertIsNone(execution_command(chosen,'test',shard=p[1]))

if __name__=='__main__':unittest.main(verbosity=2)
