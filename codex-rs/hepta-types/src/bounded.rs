use std::error::Error;
use std::fmt;

/// UTF-8 text whose encoded byte length is bounded at construction.
#[derive(Clone, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct BoundedText<const MAX_BYTES: usize>(String);

impl<const MAX_BYTES: usize> BoundedText<MAX_BYTES> {
    pub fn new(value: impl Into<String>) -> Result<Self, BoundedValueError> {
        let value = value.into();
        validate_length(value.len(), MAX_BYTES)?;
        if value.contains('\0') {
            return Err(BoundedValueError::Nul);
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    pub fn into_inner(self) -> String {
        self.0
    }
}

impl<const MAX_BYTES: usize> fmt::Debug for BoundedText<MAX_BYTES> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.debug_tuple("BoundedText").field(&self.0).finish()
    }
}

impl<const MAX_BYTES: usize> fmt::Display for BoundedText<MAX_BYTES> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

/// Opaque bytes whose size is bounded at construction.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BoundedBytes<const MAX_BYTES: usize>(Vec<u8>);

impl<const MAX_BYTES: usize> BoundedBytes<MAX_BYTES> {
    pub fn new(value: Vec<u8>) -> Result<Self, BoundedValueError> {
        validate_length(value.len(), MAX_BYTES)?;
        Ok(Self(value))
    }

    pub fn as_slice(&self) -> &[u8] {
        &self.0
    }

    pub fn into_inner(self) -> Vec<u8> {
        self.0
    }
}

fn validate_length(actual: usize, maximum: usize) -> Result<(), BoundedValueError> {
    if maximum == 0 {
        return Err(BoundedValueError::InvalidMaximum);
    }
    if actual == 0 {
        return Err(BoundedValueError::Empty);
    }
    if actual > maximum {
        return Err(BoundedValueError::TooLarge { actual, maximum });
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BoundedValueError {
    InvalidMaximum,
    Empty,
    Nul,
    TooLarge { actual: usize, maximum: usize },
}

impl fmt::Display for BoundedValueError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidMaximum => formatter.write_str("maximum length must be positive"),
            Self::Empty => formatter.write_str("bounded value must not be empty"),
            Self::Nul => formatter.write_str("bounded text must not contain NUL"),
            Self::TooLarge { actual, maximum } => {
                write!(
                    formatter,
                    "bounded value has {actual} bytes; maximum is {maximum}"
                )
            }
        }
    }
}

impl Error for BoundedValueError {}

#[cfg(test)]
#[path = "bounded_tests.rs"]
mod tests;
