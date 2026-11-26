//! Bounded owner-local wire primitives for qualification archives, version 2.
//! This trait is crate-private: decoding bytes cannot mint a public sealed receipt.
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::ProductEvaluationError;

pub(crate) const MAX_BYTES: usize = 32 * 1024 * 1024;
const MAX_LIST: usize = 16_384;
pub(crate) type Result<T> = std::result::Result<T, ProductEvaluationError>;

pub(crate) fn invalid() -> ProductEvaluationError {
    ProductEvaluationError::Integrity("qualification archive codec")
}

pub(crate) trait Wire: Sized {
    fn write(&self, output: &mut Writer) -> Result<()>;
    fn read(input: &mut Reader<'_>) -> Result<Self>;
}

#[derive(Default)]
pub(crate) struct Writer(Vec<u8>);

impl Writer {
    pub(crate) fn put(&mut self, bytes: &[u8]) -> Result<()> {
        if self
            .0
            .len()
            .checked_add(bytes.len())
            .is_none_or(|size| size > MAX_BYTES)
        {
            return Err(invalid());
        }
        self.0.extend_from_slice(bytes);
        Ok(())
    }

    pub(crate) fn finish(self) -> Vec<u8> {
        self.0
    }
}

pub(crate) struct Reader<'a>(&'a [u8]);

impl<'a> Reader<'a> {
    pub(crate) fn new(bytes: &'a [u8]) -> Result<Self> {
        if bytes.len() > MAX_BYTES {
            return Err(invalid());
        }
        Ok(Self(bytes))
    }

    pub(crate) fn take(&mut self, count: usize) -> Result<&'a [u8]> {
        let (head, tail) = self.0.split_at_checked(count).ok_or_else(invalid)?;
        self.0 = tail;
        Ok(head)
    }

    pub(crate) fn finish(self) -> Result<()> {
        if self.0.is_empty() {
            Ok(())
        } else {
            Err(invalid())
        }
    }
}

macro_rules! structure {
    ($name:ty { $($field:ident),* $(,)? }) => {
        impl $crate::recorded_publication::archive::codec::Wire for $name {
            fn write(&self, output: &mut $crate::recorded_publication::archive::codec::Writer)
                -> $crate::recorded_publication::archive::codec::Result<()> {
                $($crate::recorded_publication::archive::codec::Wire::write(&self.$field, output)?;)*
                Ok(())
            }
            fn read(input: &mut $crate::recorded_publication::archive::codec::Reader<'_>)
                -> $crate::recorded_publication::archive::codec::Result<Self> {
                Ok(Self { $($field: $crate::recorded_publication::archive::codec::Wire::read(input)?,)* })
            }
        }
    };
}
pub(crate) use structure;

macro_rules! integer {
    ($type:ty, $width:expr) => {
        impl Wire for $type {
            fn write(&self, output: &mut Writer) -> Result<()> {
                output.put(&self.to_be_bytes())
            }
            fn read(input: &mut Reader<'_>) -> Result<Self> {
                let bytes: [u8; $width] = input.take($width)?.try_into().map_err(|_| invalid())?;
                Ok(Self::from_be_bytes(bytes))
            }
        }
    };
}
integer!(u8, 1);
integer!(u32, 4);
integer!(u64, 8);
integer!(i64, 8);

impl<const N: usize> Wire for [u8; N] {
    fn write(&self, output: &mut Writer) -> Result<()> {
        output.put(self)
    }
    fn read(input: &mut Reader<'_>) -> Result<Self> {
        input.take(N)?.try_into().map_err(|_| invalid())
    }
}

impl Wire for Digest32 {
    fn write(&self, output: &mut Writer) -> Result<()> {
        output.put(self.as_array())
    }
    fn read(input: &mut Reader<'_>) -> Result<Self> {
        Ok(Self::from_array(<[u8; 32]>::read(input)?))
    }
}

impl Wire for FixedQ32 {
    fn write(&self, output: &mut Writer) -> Result<()> {
        self.raw().write(output)
    }
    fn read(input: &mut Reader<'_>) -> Result<Self> {
        Ok(Self::from_raw(i64::read(input)?))
    }
}

impl Wire for StableId {
    fn write(&self, output: &mut Writer) -> Result<()> {
        let bytes = self.as_str().as_bytes();
        if !(1..=128).contains(&bytes.len()) {
            return Err(invalid());
        }
        u32::try_from(bytes.len())
            .map_err(|_| invalid())?
            .write(output)?;
        output.put(bytes)
    }
    fn read(input: &mut Reader<'_>) -> Result<Self> {
        let count = u32::read(input)? as usize;
        if !(1..=128).contains(&count) {
            return Err(invalid());
        }
        let text = std::str::from_utf8(input.take(count)?).map_err(|_| invalid())?;
        Self::new(text).map_err(|_| invalid())
    }
}

impl<T: Wire> Wire for Vec<T> {
    fn write(&self, output: &mut Writer) -> Result<()> {
        if self.len() > MAX_LIST {
            return Err(invalid());
        }
        u32::try_from(self.len())
            .map_err(|_| invalid())?
            .write(output)?;
        for value in self {
            value.write(output)?;
        }
        Ok(())
    }
    fn read(input: &mut Reader<'_>) -> Result<Self> {
        let count = u32::read(input)? as usize;
        if count > MAX_LIST {
            return Err(invalid());
        }
        let mut values = Vec::new();
        for _ in 0..count {
            values.push(T::read(input)?);
        }
        Ok(values)
    }
}

impl<T: Wire> Wire for Option<T> {
    fn write(&self, output: &mut Writer) -> Result<()> {
        match self {
            None => 0_u8.write(output),
            Some(value) => {
                1_u8.write(output)?;
                value.write(output)
            }
        }
    }
    fn read(input: &mut Reader<'_>) -> Result<Self> {
        match u8::read(input)? {
            0 => Ok(None),
            1 => Ok(Some(T::read(input)?)),
            _ => Err(invalid()),
        }
    }
}

impl Wire for AuthorityPosture {
    fn write(&self, output: &mut Writer) -> Result<()> {
        if self.grants_any() {
            return Err(invalid());
        }
        0_u8.write(output)
    }
    fn read(input: &mut Reader<'_>) -> Result<Self> {
        if u8::read(input)? != 0 {
            return Err(invalid());
        }
        Ok(Self::DENY_ALL)
    }
}
