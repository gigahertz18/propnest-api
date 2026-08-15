from collections.abc import Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from uuid import UUID

from app.core.security import verify_password
from app.models.audit_log import AuditAction
from app.models.user import User, UserRole
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate, UserUpdate
from app.services.audit import write_audit_log
from app.services.notification_service import NotificationService
from app.services.utils import integrity_error_message
from app.services.exceptions import (
    UserNotFoundError,
    EmailAlreadyExistsError,
    UsernameAlreadyExistsError,
    ManagerAssignedToPropertyError,
    UserForbiddenError,
    CurrentPasswordRequiredError,
    InvalidCredentialsError,
)


class UserService:
    """
    Business logic around `User` entities.

    This service wraps the repository and raises domain-specific
    exceptions where appropriate so the route layer can translate
    them into HTTP responses.
    """

    def __init__(self, user_repo: UserRepository, notification_service: NotificationService | None = None) -> None:
        self.user_repo = user_repo
        self.notification_service = notification_service or NotificationService()

    async def list_users(
        self,
        db: AsyncSession,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[User]:
        self._require_admin(current_user)
        return await self.user_repo.get_all(db, skip=skip, limit=limit)

    async def get_user(self, db: AsyncSession, id: UUID, current_user: User) -> User:
        self._authorize_self_or_admin(current_user, id)
        user = await self.user_repo.get_by_id(db, id)
        if not user:
            raise UserNotFoundError("User not found")
        return user

    async def create_user(self, db: AsyncSession, payload: UserCreate, current_user: User) -> User:
        # No self-or-admin check needed: this creates a brand-new account,
        # so there's no existing resource to own. Admin-only role gating
        # at the route layer (require_admin) is sufficient here — there's
        # no per-resource ownership dimension the way get/update/delete have.
        # Pre-check for fast feedback in the common case
        if await self.user_repo.get_by_email(db, payload.email):
            raise EmailAlreadyExistsError("A user with this email already exists")
        if await self.user_repo.get_by_username(db, payload.username):
            raise UsernameAlreadyExistsError("A user with this username already exists")

        # Concurrent requests can still race past the pre-check - translate
        # the resulting IntegrityError into a domain exception
        try:
            user = await self.user_repo.create(db, payload)
            write_audit_log(db, current_user, AuditAction.CREATE, "User", user.id)
            await db.commit()
            return user
        except IntegrityError as e:
            self._raise_conflict(
                e, default=EmailAlreadyExistsError("A user with this email or username already exists")
            )

    async def update_user(self, db: AsyncSession, id: UUID, payload: UserUpdate, current_user: User) -> User:
        self._authorize_self_or_admin(current_user, id)

        if payload.role is not None and getattr(current_user, "role", None) != UserRole.ADMIN:
            raise UserForbiddenError("You cannot change your own role.")

        is_self_service_password_change = payload.password is not None and current_user.id == id
        if is_self_service_password_change:
            self._verify_current_password(payload, current_user)

        if payload.email is not None:
            existing = await self.user_repo.get_by_email(db, payload.email)
            if existing and existing.id != id:
                raise EmailAlreadyExistsError("A user with this email already exists")

        if payload.username is not None:
            existing = await self.user_repo.get_by_username(db, payload.username)
            if existing and existing.id != id:
                raise UsernameAlreadyExistsError("A user with this username already exists")

        try:
            user = await self.user_repo.update(db, id, payload)
        except IntegrityError as e:
            self._raise_conflict(e)

        if not user:
            raise UserNotFoundError("User not found")
        write_audit_log(db, current_user, AuditAction.UPDATE, "User", id)
        await db.commit()

        if payload.password is not None:
            # Fires for both the self-service path above and an
            # admin-initiated reset of another user's password
            self.notification_service.notify_password_changed(user)
        return user

    async def delete_user(self, db: AsyncSession, id: UUID, current_user: User) -> User:
        self._require_admin(current_user)

        if current_user.id == id:
            raise UserForbiddenError("You cannot delete your own account.")

        user = await self.user_repo.delete(db, id)

        if not user:
            raise UserNotFoundError("User not found")

        write_audit_log(db, current_user, AuditAction.DELETE, "User", id)
        try:
            await db.commit()
        except IntegrityError as e:
            raise ManagerAssignedToPropertyError(
                f"User {id} cannot be deleted because they are still assigned as manager on one or more properties."
            ) from e
        return user

    @staticmethod
    def _require_admin(current_user: User) -> None:
        if getattr(current_user, "role", None) != UserRole.ADMIN:
            raise UserForbiddenError("Admin access required.")

    @staticmethod
    def _authorize_self_or_admin(current_user: User, target_id: UUID) -> None:
        role = getattr(current_user, "role", None)
        if role != UserRole.ADMIN and getattr(current_user, "id", None) != target_id:
            raise UserForbiddenError("You can only access your own profile.")

    @staticmethod
    def _verify_current_password(payload: UserUpdate, current_user: User) -> None:
        """
        Re-authentication gate for self-service password changes.

        Only reached when current_user.id == target id — an admin
        resetting a *different* user's password never calls this, since
        that path is already gated by _authorize_self_or_admin (only an
        admin or the account owner can reach update_user at all).
        """
        if not payload.current_password:
            raise CurrentPasswordRequiredError("current_password is required to change your own password.")
        if not verify_password(payload.current_password, current_user.password_hash):
            raise InvalidCredentialsError("The current password you entered is incorrect.")

    @staticmethod
    def _raise_conflict(e: IntegrityError, default: Exception | None = None) -> None:
        """
        Translate an email/username unique-constraint violation into the matching domain exception.
        `default`, if given, is raised for an unrecognized constraint instead of re-raising `e`.
        """
        msg = integrity_error_message(e)
        if "email" in msg:
            raise EmailAlreadyExistsError("A user with this email already exists") from e
        if "username" in msg:
            raise UsernameAlreadyExistsError("A user with this username already exists") from e
        if default:
            raise default from e
        raise
