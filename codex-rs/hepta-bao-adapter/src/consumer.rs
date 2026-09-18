use std::collections::BTreeMap;
use std::fmt;
use std::sync::Arc;

const MAX_TRUSTED_CONSUMERS: usize = 64;

pub trait TrustedSecretConsumer: Send + Sync + 'static {
    fn consume(&self, secret: &[u8]) -> Result<(), ()>;
}

impl<F> TrustedSecretConsumer for F
where
    F: Fn(&[u8]) -> Result<(), ()> + Send + Sync + 'static,
{
    fn consume(&self, secret: &[u8]) -> Result<(), ()> {
        self(secret)
    }
}

/// Host-built consumer registry. A signed consumer name selects one entry from
/// this registry; it can never authenticate or construct a callback supplied by
/// request/plugin data at final-use time.
#[derive(Clone, Default)]
pub struct TrustedConsumerRegistry {
    consumers: Arc<BTreeMap<String, Arc<dyn TrustedSecretConsumer>>>,
}

impl fmt::Debug for TrustedConsumerRegistry {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("TrustedConsumerRegistry")
            .field("consumer_count", &self.consumers.len())
            .finish()
    }
}

impl TrustedConsumerRegistry {
    pub fn new(
        entries: impl IntoIterator<Item = (String, Arc<dyn TrustedSecretConsumer>)>,
    ) -> Result<Self, TrustedConsumerRegistryError> {
        let mut consumers = BTreeMap::new();
        for (id, consumer) in entries {
            if !consumer_id(&id) {
                return Err(TrustedConsumerRegistryError::InvalidConsumerId);
            }
            if consumers.insert(id, consumer).is_some() {
                return Err(TrustedConsumerRegistryError::DuplicateConsumer);
            }
            if consumers.len() > MAX_TRUSTED_CONSUMERS {
                return Err(TrustedConsumerRegistryError::CapacityExceeded);
            }
        }
        Ok(Self {
            consumers: Arc::new(consumers),
        })
    }

    pub(crate) fn consume(&self, id: &str, secret: &[u8]) -> Result<(), TrustedConsumerError> {
        let consumer = self
            .consumers
            .get(id)
            .ok_or(TrustedConsumerError::UnknownConsumer)?;
        consumer
            .consume(secret)
            .map_err(|()| TrustedConsumerError::Indeterminate)
    }

    pub fn contains(&self, id: &str) -> bool {
        self.consumers.contains_key(id)
    }
}

fn consumer_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value != "."
        && value != ".."
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:".contains(&byte))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TrustedConsumerRegistryError {
    InvalidConsumerId,
    DuplicateConsumer,
    CapacityExceeded,
}

impl fmt::Display for TrustedConsumerRegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl std::error::Error for TrustedConsumerRegistryError {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum TrustedConsumerError {
    UnknownConsumer,
    Indeterminate,
}
