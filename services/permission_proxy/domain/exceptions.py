class DomainError(Exception):
    """Base class for expected control-plane domain failures."""


class EntityNotFoundError(DomainError):
    """Raised when a requested persistent entity does not exist."""


class InvalidManifestStateError(DomainError):
    """Raised when a manifest cannot transition to the requested state."""


class SeedDataConflictError(DomainError):
    """Raised when existing seed identifiers contain unexpected data."""
