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


class ResourceForbiddenError(ServiceException):
    """
    Base class for "user not authorized to manage this resource" errors.

    `ResourceAuthorizationMixin._authorize_user_to_property` raises
    `self.forbidden_error(...)`, a class attribute each service overrides
    with its own subclass below, so routes/tests can catch the specific
    entity's error rather than this base. A service that forgets to
    override it still raises a real, catchable exception via this base —
    a safe (if less specific) default rather than a silent failure.
    """

    pass


class ContractForbiddenError(ResourceForbiddenError):
    """Raised when a contract operation is attempted by a manager who
    doesn't own the contract's property."""

    pass


class DocumentUploadError(ServiceException):
    """Raised when storing a document fails due to external storage errors."""

    pass


class DocumentDeletionError(ServiceException):
    """Raised when deleting a document failes due to external storage errors."""

    pass


class DocumentForbiddenError(ResourceForbiddenError):
    """Raised when a document is acccessed by an unauthorized user"""

    pass


class DocumentValidationError(ServiceException):
    """Raised when a document validation fails"""

    pass


class RelatedResourceNotFoundError(ServiceException):
    """Raised when there is a missing/failed property/contract/tenant lookup"""

    pass


class PropertyAlreadyExistsError(ServiceException):
    pass
