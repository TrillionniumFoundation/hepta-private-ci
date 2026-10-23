//! Process-only representations of unverified scalar and enum inputs.
//! No opaque admission, selection, or authority token implements this mapping.

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;
use serde::Serializer;

#[derive(Debug)]
pub(super) struct Digest(pub Digest32);
#[derive(Debug)]
pub(super) struct Id(pub StableId);
#[derive(Debug)]
pub(super) struct GenerationWire(pub Generation);
#[derive(Debug)]
pub(super) struct Fixed(pub FixedQ32);
#[derive(Debug)]
pub(super) struct Probability(pub ProbabilityQ32);
#[derive(Debug)]
pub(super) struct Key(pub [u8; 32]);
#[derive(Debug)]
pub(super) struct Signature(pub [u8; 64]);

macro_rules! scalar {
    ($wire:ident, $native:ty, $input:ty, $parse:expr, $encode:expr) => {
        impl<'de> Deserialize<'de> for $wire {
            fn deserialize<D: Deserializer<'de>>(decoder: D) -> Result<Self, D::Error> {
                let value = <$input>::deserialize(decoder)?;
                ($parse)(value).map(Self).map_err(serde::de::Error::custom)
            }
        }
        impl Serialize for $wire {
            fn serialize<S: Serializer>(&self, encoder: S) -> Result<S::Ok, S::Error> {
                ($encode)(&self.0).serialize(encoder)
            }
        }
        impl From<$wire> for $native {
            fn from(value: $wire) -> Self {
                value.0
            }
        }
        impl From<$native> for $wire {
            fn from(value: $native) -> Self {
                Self(value)
            }
        }
    };
}
scalar!(
    Digest,
    Digest32,
    String,
    |s: String| s.parse::<Digest32>(),
    |v: &Digest32| v.to_string()
);
scalar!(Id, StableId, String, StableId::new, |v: &StableId| v
    .to_string());
scalar!(
    GenerationWire,
    Generation,
    u64,
    Generation::new,
    |v: &Generation| v.get()
);
scalar!(
    Fixed,
    FixedQ32,
    i64,
    |value| Ok::<_, std::convert::Infallible>(FixedQ32::from_raw(value)),
    |v: &FixedQ32| v.raw()
);
scalar!(Key, [u8; 32], String, parse_hex::<32>, |v: &[u8; 32]| hex(
    v
));
scalar!(
    Probability,
    ProbabilityQ32,
    u64,
    ProbabilityQ32::from_raw,
    |v: &ProbabilityQ32| v.raw()
);
scalar!(
    Signature,
    [u8; 64],
    String,
    parse_hex::<64>,
    |v: &[u8; 64]| hex(v)
);

fn parse_hex<const N: usize>(value: String) -> Result<[u8; N], &'static str> {
    if value.len() != N * 2 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("invalid fixed-length hex input");
    }
    let mut output = [0; N];
    for (index, slot) in output.iter_mut().enumerate() {
        *slot = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)
            .map_err(|_| "invalid hex input")?;
    }
    Ok(output)
}

fn hex(value: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(value.len() * 2);
    for byte in value {
        output.push(char::from(DIGITS[usize::from(byte >> 4)]));
        output.push(char::from(DIGITS[usize::from(byte & 15)]));
    }
    output
}

macro_rules! simple_enum {
    ($wire:ident, $native:path, $($variant:ident),+ $(,)?) => {
        #[derive(Debug, Deserialize, Serialize)]
        #[serde(rename_all = "snake_case")]
        pub(super) enum $wire { $($variant),+ }
        impl From<$wire> for $native {
            fn from(value: $wire) -> Self { match value { $($wire::$variant => Self::$variant),+ } }
        }
        impl From<$native> for $wire {
            fn from(value: $native) -> Self { use $native as Native; match value { $(Native::$variant => Self::$variant),+ } }
        }
    };
}
simple_enum!(
    ProductMetricSourceV1Raw,
    codex_hepta_intelligence_eval::ProductMetricSourceV1,
    Ips,
    Snips,
    DoublyRobust
);
simple_enum!(
    LearningEvidenceRoleV1Raw,
    codex_hepta_learning_ledger::LearningEvidenceRoleV1,
    Generator,
    Observer,
    Evaluator,
    CreditAllocator,
    UnlearningAuthority,
    Selector
);
simple_enum!(
    EvaluationClaimScopeV1Raw,
    codex_hepta_intelligence_eval::EvaluationClaimScopeV1,
    Qualification,
    SystemLongitudinal
);
simple_enum!(
    EvaluationDirectionV1Raw,
    codex_hepta_intelligence_eval::EvaluationDirectionV1,
    Maximize,
    Minimize
);
simple_enum!(
    ArtifactKindRaw,
    codex_hepta_learning_artifacts::ArtifactKind,
    Prompt,
    Policy,
    Model,
    Workflow,
    Skill,
    Parameters,
    Topology,
    Code,
    ExternalAdapter,
    SensorCore
);
simple_enum!(
    ProvenanceModeV1Raw,
    codex_hepta_learning_artifacts::ProvenanceModeV1,
    DatasetDerived,
    DatasetIndependent
);

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum MetricRoleV2Raw {
    PrimarySuperiority { minimum_improvement: Fixed },
    NonInferiority { maximum_regression: Fixed },
    AbsoluteConstraint,
}
impl From<MetricRoleV2Raw> for codex_hepta_intelligence_eval::MetricRoleV2 {
    fn from(value: MetricRoleV2Raw) -> Self {
        match value {
            MetricRoleV2Raw::PrimarySuperiority {
                minimum_improvement,
            } => Self::PrimarySuperiority {
                minimum_improvement: minimum_improvement.into(),
            },
            MetricRoleV2Raw::NonInferiority { maximum_regression } => Self::NonInferiority {
                maximum_regression: maximum_regression.into(),
            },
            MetricRoleV2Raw::AbsoluteConstraint => Self::AbsoluteConstraint,
        }
    }
}
impl From<codex_hepta_intelligence_eval::MetricRoleV2> for MetricRoleV2Raw {
    fn from(value: codex_hepta_intelligence_eval::MetricRoleV2) -> Self {
        use codex_hepta_intelligence_eval::MetricRoleV2;
        match value {
            MetricRoleV2::PrimarySuperiority {
                minimum_improvement,
            } => Self::PrimarySuperiority {
                minimum_improvement: minimum_improvement.into(),
            },
            MetricRoleV2::NonInferiority { maximum_regression } => Self::NonInferiority {
                maximum_regression: maximum_regression.into(),
            },
            MetricRoleV2::AbsoluteConstraint => Self::AbsoluteConstraint,
        }
    }
}
