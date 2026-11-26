//! Compatibility facade for anymap2 backed by anymap3.
pub use anymap3::Map;
pub mod any {
    pub use anymap3::CloneAny;
    pub use anymap3::CloneAny as CloneAnySend;
    pub use anymap3::CloneAny as CloneAnySync;
    pub use anymap3::CloneAny as CloneAnySendSync;
    pub use anymap3::CloneAny as Any;
}
pub mod raw {
    pub use anymap3::RawMap;
}
pub type AnyMap = anymap3::AnyMap;
