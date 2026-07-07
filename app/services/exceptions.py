"""
Service layer exceptions.

These are domain exceptions raised by services — they have no knowledge
of HTTP. Routes catch these and convert them to appropriate HTTP responses.
"""


class ServiceException(Exception):
    """Base class for all service exceptions."""

    pass


# ─── Auth ─────────────────────────────────────────────────
class InvalidCredentialsError(ServiceException):
    """Raised when identifier/password combination is invalid."""

    pass


class AccountInactiveError(ServiceException):
    """Raised when a user account exists but is deactivated."""

    pass


class TokenExpiredError(ServiceException):
    """Raised when a JWT token has expired."""

    pass


class InvalidTokenError(ServiceException):
    """Raised when a JWT token is malformed or invalid."""

    pass


# ─── User ─────────────────────────────────────────────────
class UserNotFoundError(ServiceException):
    """Raised when a user cannot be found."""

    pass


class EmailAlreadyExistsError(ServiceException):
    """Raised when trying to create/update a user with a duplicate email."""

    pass


class UsernameAlreadyExistsError(ServiceException):
    """Raised when trying to create/update a user with a duplicate username."""

    pass


class UnauthorizedError(ServiceException):
    """Raised when a user tries to perform an action they're not allowed to."""

    pass


class ForbiddenError(ServiceException):
    """Raised when a user is authenticated but lacks the required role."""

    pass


# ─── Contract / Document ────────────────────────────────────────────────
class ContractActiveError(ServiceException):
    """Raised when attempting to create an ACTIVE contract for a property
    that already has an active contract."""

    pass


class DocumentUploadError(ServiceException):
    """Raised when storing a document fails due to external storage errors."""

    pass


class DocumentDeletionError(ServiceException):
    """Raised when deleting a document failes due to external storage errors."""

    pass


class DocumentForbiddenError(ServiceException):
    """Raised when a document is acccessed by an unauthorized user"""

    pass


class DocumentValidationError(ServiceException):
    """Raised when a document validation fails"""

    pass


class RelatedResourceNotFoundError(ServiceException):
    """Raised when there is a missing/failed property/contract/tenant lookup"""

    pass
