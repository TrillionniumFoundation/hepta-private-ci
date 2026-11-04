# Original union metadata evidence

Source `0cf81d65646b8907e42e781ea35a28437b5b0054`, original run `41777289308`, artifact `13297307552` remained failed at the strict dependency-record gate. The independent read-only bridge `37d397ad40ec19b012eec22360cd74b62f19a3ab`, run `41778545855`, job `126404487847` succeeded without running the archived generator or product.

The projection contains all requested 18 package declarations, features, actual resolve nodes and selected dependency identities. It preserves the original 1518-package proposal and exact 18 registry dependency-record changes. Package versions, source IDs, checksums and all other registry fields are unchanged in those 18 records. Only Unicode 0.1.25 to 0.1.26 and the local `hepta-control-core` addition change the package identity set.

All 10,909 source entries were compared with exact Git blob bytes, including raw link payloads and file modes. All ZIP members and original command outputs were checked. The only source differences after the failed generator are its three allowed formatter changes and its actual Cargo lock proposal. The complete output-hash inventory remains in the bridge artifact's `VERIFIED.json`, identified in the projection; the projection does not pretend to contain that inventory.

This evidence supports review of the original rejected proposal. It does not adopt the lock, rerun Cargo, qualify semver independently, or declare joint CI complete.
