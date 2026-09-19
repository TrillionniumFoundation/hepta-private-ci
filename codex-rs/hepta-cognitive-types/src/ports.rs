//! Exact ModulePort-to-schema bindings for cognitive.types.
//!
//! The canonical contract registry names the ports; this table closes the
//! previously-generic payload class by naming the only V1 schemas each port may
//! exchange.  Adding or replacing a schema requires a versioned registry change.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ModulePortSchemaBindingV1 {
    pub port_id: &'static str,
    pub schemas: &'static [&'static str],
}

pub const COGNITIVE_READ_SCHEMAS: &[&str] = &[
    "MemoryEventV1",
    "ModalitySpanRefV1",
    "MemoryCueV1",
    "RecallPacketV1",
];

pub const COGNITIVE_STORE_SCHEMAS: &[&str] = &[
    "MemoryEventV1",
    "ModalitySpanRefV1",
    "CrossModalBindingV1",
    "ForgetPropagationReceiptV1",
];

pub const KNOWLEDGE_GRAPH_SCHEMAS: &[&str] = &[
    "MemoryEventV1",
    "CrossModalBindingV1",
    "EngramNodeV1",
    "SynapseV1",
    "ForgetPropagationReceiptV1",
];

pub const LEARNING_LEDGER_SCHEMAS: &[&str] = &[
    "OutcomeSignalV1",
    "ReplaySelectionReceiptV1",
    "PlasticityBatchV1",
    "MemoryTopologyProposalV1",
    "ForgetPropagationReceiptV1",
];

pub const MODULE_PORT_SCHEMA_BINDINGS: &[ModulePortSchemaBindingV1] = &[
    ModulePortSchemaBindingV1 {
        port_id: "ModulePort::cognitive.types::cognitive.read",
        schemas: COGNITIVE_READ_SCHEMAS,
    },
    ModulePortSchemaBindingV1 {
        port_id: "ModulePort::cognitive.types::cognitive.store",
        schemas: COGNITIVE_STORE_SCHEMAS,
    },
    ModulePortSchemaBindingV1 {
        port_id: "ModulePort::cognitive.types::knowledge.graph",
        schemas: KNOWLEDGE_GRAPH_SCHEMAS,
    },
    ModulePortSchemaBindingV1 {
        port_id: "ModulePort::cognitive.types::learning.ledger",
        schemas: LEARNING_LEDGER_SCHEMAS,
    },
];

#[must_use]
pub fn schemas_for_port(port_id: &str) -> Option<&'static [&'static str]> {
    MODULE_PORT_SCHEMA_BINDINGS
        .iter()
        .find(|binding| binding.port_id == port_id)
        .map(|binding| binding.schemas)
}

#[cfg(test)]
#[path = "ports_tests.rs"]
mod tests;
