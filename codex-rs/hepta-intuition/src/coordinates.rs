//! Distinct coordinates at typed policy boundaries; historical wire values stay u64.
//! Zero is valid for a sequence, counter and Unix epoch. Monotonic admission
//! belongs to the authoritative owner rather than to a numeric wrapper.

macro_rules! coordinate {
    ($name:ident) => {
        #[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
        pub struct $name(u64);
        impl $name {
            #[must_use]
            pub const fn from_raw(value: u64) -> Self { Self(value) }
            #[must_use]
            pub const fn get(self) -> u64 { self.0 }
            #[must_use]
            pub const fn checked_next(self) -> Option<Self> {
                match self.0.checked_add(1) { Some(value) => Some(Self(value)), None => None }
            }
        }
    };
}
coordinate!(PolicySequence);
coordinate!(PolicyWallClockMillis);
coordinate!(AssignmentCounter);

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn coordinate_overflow_never_wraps() {
        assert_eq!(PolicySequence::from_raw(u64::MAX).checked_next(), None);
        assert_eq!(PolicyWallClockMillis::from_raw(u64::MAX).checked_next(), None);
        assert_eq!(AssignmentCounter::from_raw(u64::MAX).checked_next(), None);
        assert_eq!(PolicySequence::from_raw(0).checked_next().unwrap().get(), 1);
    }
}
