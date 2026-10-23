"""Trusted publisher/client orchestration; migration is staged before its CAS."""

from network_authority import placement
from network_checkpoints import pack
from network_wire import call, endpoint


class NetworkClient:
    def __init__(self, authority, nodes, key):
        endpoint(authority)
        for address in nodes.values():
            endpoint(address)
        self.authority, self.nodes, self.key = authority, dict(nodes), key

    def snapshot(self, scope, cell_id):
        return call(
            self.authority, self.key, dict(op="snapshot", scope=scope, cell_id=cell_id)
        )

    def stage(self, node_id, directory, retained_pin, scope):
        return call(
            self.nodes[node_id],
            self.key,
            dict(
                op="stage",
                package=pack(directory, retained_pin, scope),
                retained_manifest_sha256=retained_pin,
            ),
        )

    def publish(self, candidate, expected_generation):
        return call(
            self.authority,
            self.key,
            dict(
                op="publish",
                placement=placement(candidate),
                expected_generation=expected_generation,
            ),
        )

    def migrate(self, previous, target_node):
        previous = placement(previous)
        if target_node not in self.nodes or previous["node_id"] == target_node:
            raise ValueError("different registered migration target required")
        candidate = dict(
            previous, node_id=target_node, generation=previous["generation"] + 1
        )
        snapshot = self.snapshot(previous["scope"], previous["cell_id"])
        if snapshot["placement"] == candidate:
            return dict(placement=candidate, transfer=None, already_current=True)
        if snapshot["placement"] != previous:
            raise ValueError("migration source placement changed")
        package = call(
            self.nodes[previous["node_id"]],
            self.key,
            dict(op="export", scope=previous["scope"], cell_id=previous["cell_id"]),
        )
        if package["manifest_sha256"] != previous["manifest_sha256"]:
            raise ValueError("migration source pin changed")
        receipt = call(
            self.nodes[target_node],
            self.key,
            dict(
                op="stage",
                package=package,
                retained_manifest_sha256=previous["manifest_sha256"],
            ),
        )
        if receipt["roots"] != previous["roots"]:
            raise ValueError("transferred checkpoint roots changed")
        committed = self.publish(candidate, previous["generation"])
        return dict(placement=committed, transfer=receipt, already_current=False)

    def read(self, scope, cell_id, questions, *, control="adapter"):
        current = self.snapshot(scope, cell_id)["placement"]
        if current is None:
            raise ValueError("cell has no placement")
        result = call(
            self.nodes[current["node_id"]],
            self.key,
            dict(
                op="read",
                scope=scope,
                cell_id=cell_id,
                questions=questions,
                control=control,
            ),
            timeout=600,
        )
        if result["placement"] != current:
            raise ValueError("read placement changed after routing")
        return result

    def service_reader(self, active, question):
        """Callback for MemoryService.invoke_parameter; preserve raw decoder rows."""
        current = self.snapshot(active.scope, active.cell_id)["placement"]
        if current is None or current["manifest_sha256"] != active.manifest_sha256:
            raise ValueError("service and network active manifests differ")
        result = self.read(active.scope, active.cell_id, [question])
        if result["placement"]["manifest_sha256"] != active.manifest_sha256:
            raise ValueError("service manifest changed during network read")
        return result
