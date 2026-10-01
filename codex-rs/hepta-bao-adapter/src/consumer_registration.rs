use super::*;

pub type BaoOperationConsumerCallback =
    Arc<dyn Fn(&str, [u8; 32], &[u8]) -> Result<(), ()> + Send + Sync + 'static>;
pub type BaoConsumerObserverCallback =
    Arc<dyn Fn(&str, [u8; 32]) -> Result<BaoConsumerObservationV1, ()> + Send + Sync + 'static>;

/// Durable observation of the original consumer effect.
///
/// The legacy `NotApplied` value remains conservative and cannot release quota.
/// `NotAppliedWithEvidence` is the terminal negative outcome: the enrolled
/// observer must return a nonzero immutable evidence digest for the original
/// operation identity and semantic digest.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaoConsumerObservationV1 {
    Succeeded,
    NotApplied,
    NotAppliedWithEvidence { evidence_sha256: [u8; 32] },
    Unknown,
}

pub type BaoConsumerCallback = Arc<dyn Fn(&[u8]) -> Result<(), ()> + Send + Sync + 'static>;

#[derive(Clone)]
pub struct RegisteredBaoConsumer {
    pub(super) id: String,
    pub(super) callback: BaoConsumerCallback,
    pub(super) configuration_sha256: Option<[u8; 32]>,
    pub(super) operation_callback: Option<BaoOperationConsumerCallback>,
    pub(super) operation_preparer: Option<BaoOperationConsumerPreparer>,
    pub(super) observer: Option<BaoConsumerObserverCallback>,
}

impl fmt::Debug for RegisteredBaoConsumer {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RegisteredBaoConsumer")
            .field("id", &self.id)
            .field("callback", &"[TRUSTED CALLBACK]")
            .finish()
    }
}

impl RegisteredBaoConsumer {
    pub fn new(id: String, callback: BaoConsumerCallback) -> Result<Self, BaoFinalUseHostError> {
        if !consumer_id(&id) {
            return Err(BaoFinalUseHostError::InvalidConsumerId);
        }
        Ok(Self {
            id,
            callback,
            configuration_sha256: None,
            operation_callback: None,
            operation_preparer: None,
            observer: None,
        })
    }

    /// A product registration must bind its immutable implementation/configuration
    /// identity and provide an operation-bound observer for restart reconciliation.
    pub fn for_operations(
        id: String,
        configuration_sha256: [u8; 32],
        callback: BaoOperationConsumerCallback,
        observer: BaoConsumerObserverCallback,
    ) -> Result<Self, BaoFinalUseHostError> {
        if !consumer_id(&id) || configuration_sha256 == [0; 32] {
            return Err(BaoFinalUseHostError::InvalidConsumerConfiguration);
        }
        Ok(Self {
            id,
            callback: Arc::new(|_| Err(())),
            configuration_sha256: Some(configuration_sha256),
            operation_callback: Some(callback),
            operation_preparer: None,
            observer: Some(observer),
        })
    }

    /// Prepare a bounded external consumer port before the final authority
    /// check. The resulting one-shot callback crosses its first effect
    /// synchronously; it cannot reconnect or replay after an uncertain result.
    pub fn for_prepared_operations(
        id: String,
        configuration_sha256: [u8; 32],
        preparer: BaoOperationConsumerPreparer,
        observer: BaoConsumerObserverCallback,
    ) -> Result<Self, BaoFinalUseHostError> {
        let mut registration = Self::for_operations(
            id,
            configuration_sha256,
            Arc::new(|_, _, _| Err(())),
            observer,
        )?;
        registration.operation_preparer = Some(preparer);
        Ok(registration)
    }

    pub fn id(&self) -> &str {
        &self.id
    }
}

pub type BaoPreparedConsumerCallback = Box<dyn FnOnce(&[u8]) -> Result<(), ()> + Send + 'static>;
pub type BaoOperationConsumerPreparer =
    Arc<dyn Fn(&str, [u8; 32]) -> Result<BaoPreparedConsumerCallback, ()> + Send + Sync + 'static>;
