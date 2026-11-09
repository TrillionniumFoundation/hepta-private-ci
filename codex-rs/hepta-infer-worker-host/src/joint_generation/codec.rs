//! The native process and host inspection share the original packet codec.

pub use codex_hepta_infer_core::JointPacketResultV1 as Result;
pub use codex_hepta_infer_core::JointTensorPacketV1 as Packet;
#[cfg(test)]
pub use codex_hepta_infer_core::JointTensorV1 as Tensor;
pub use codex_hepta_infer_core::joint_packet_sha256_v1 as sha256;
