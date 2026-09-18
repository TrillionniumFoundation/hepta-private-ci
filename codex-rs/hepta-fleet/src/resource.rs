use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FleetResourceHardnessV1 {
    Hard,
    Admission,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FleetResourceAxisV1 {
    ConcurrentTurns,
    MemoryMib,
    ToolProcesses,
    TurnQueueSlots,
}

impl FleetResourceAxisV1 {
    pub const ALL: [Self; 4] = [
        Self::ConcurrentTurns,
        Self::MemoryMib,
        Self::ToolProcesses,
        Self::TurnQueueSlots,
    ];

    pub const fn unit(self) -> &'static str {
        match self {
            Self::ConcurrentTurns => "turns",
            Self::MemoryMib => "MiB",
            Self::ToolProcesses => "processes",
            Self::TurnQueueSlots => "slots",
        }
    }

    pub const fn hardness(self) -> FleetResourceHardnessV1 {
        match self {
            Self::MemoryMib | Self::ToolProcesses => FleetResourceHardnessV1::Hard,
            Self::ConcurrentTurns | Self::TurnQueueSlots => FleetResourceHardnessV1::Admission,
        }
    }

    pub const fn read(self, vector: FleetResourceVectorV1) -> u64 {
        match self {
            Self::ConcurrentTurns => vector.concurrent_turns,
            Self::MemoryMib => vector.memory_mib,
            Self::ToolProcesses => vector.tool_processes,
            Self::TurnQueueSlots => vector.turn_queue_slots,
        }
    }

    pub fn write(self, vector: &mut FleetResourceVectorV1, value: u64) {
        match self {
            Self::ConcurrentTurns => vector.concurrent_turns = value,
            Self::MemoryMib => vector.memory_mib = value,
            Self::ToolProcesses => vector.tool_processes = value,
            Self::TurnQueueSlots => vector.turn_queue_slots = value,
        }
    }
}

#[derive(
    Clone, Copy, Debug, Default, Eq, Ord, PartialEq, PartialOrd, Deserialize, Serialize,
)]
pub struct FleetResourceVectorV1 {
    pub concurrent_turns: u64,
    pub memory_mib: u64,
    pub tool_processes: u64,
    pub turn_queue_slots: u64,
}

impl FleetResourceVectorV1 {
    pub fn checked_add(self, other: Self) -> Option<Self> {
        Some(Self {
            concurrent_turns: self.concurrent_turns.checked_add(other.concurrent_turns)?,
            memory_mib: self.memory_mib.checked_add(other.memory_mib)?,
            tool_processes: self.tool_processes.checked_add(other.tool_processes)?,
            turn_queue_slots: self.turn_queue_slots.checked_add(other.turn_queue_slots)?,
        })
    }

    pub fn checked_sub(self, other: Self) -> Option<Self> {
        Some(Self {
            concurrent_turns: self.concurrent_turns.checked_sub(other.concurrent_turns)?,
            memory_mib: self.memory_mib.checked_sub(other.memory_mib)?,
            tool_processes: self.tool_processes.checked_sub(other.tool_processes)?,
            turn_queue_slots: self.turn_queue_slots.checked_sub(other.turn_queue_slots)?,
        })
    }

    pub const fn fits(self, capacity: Self) -> bool {
        self.concurrent_turns <= capacity.concurrent_turns
            && self.memory_mib <= capacity.memory_mib
            && self.tool_processes <= capacity.tool_processes
            && self.turn_queue_slots <= capacity.turn_queue_slots
    }

    pub const fn is_zero(self) -> bool {
        self.concurrent_turns == 0
            && self.memory_mib == 0
            && self.tool_processes == 0
            && self.turn_queue_slots == 0
    }
}

pub type LocalResourceAxisV1 = FleetResourceAxisV1;
pub type LocalResourceVectorV1 = FleetResourceVectorV1;
