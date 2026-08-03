"""Shared exceptions for deterministic contract validation."""


class ContractValidationError(ValueError):
    """Raised when a protocol or registry contract is invalid."""


class ConfigurationError(ValueError):
    """Raised when local runtime configuration is invalid."""
