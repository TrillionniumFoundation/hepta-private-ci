use codex_hepta_automation::{AuthorizedEffectRecoveryResult, TaskFlowStepReceipt};
fn main() {
 println!("recovery_result_size={} align={}", std::mem::size_of::<AuthorizedEffectRecoveryResult>(), std::mem::align_of::<AuthorizedEffectRecoveryResult>());
 println!("step_receipt_size={} align={}", std::mem::size_of::<TaskFlowStepReceipt>(), std::mem::align_of::<TaskFlowStepReceipt>());
 println!("boxed_receipt_handle_size={}", std::mem::size_of::<Box<TaskFlowStepReceipt>>());
}
