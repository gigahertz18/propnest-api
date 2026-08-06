"""
Notification services for security-sensitive account events.

Currently a log-only stub — PropNest has no SMTP/email provider wired up
yet. `UserService` depends on this class rather than logging directly so
that swapping in real email delivery later (SMTP config + provider client
+ templates) only touches this file, not the service layer.
"""

import logging

from app.models.user import User

logger = logging.getLogger(__name__)


class NotificationService:
    """Fires notifications for account-security events."""

    def notify_password_changed(self, user: User) -> None:
        """
        Signal that `user`'s password was just changed.

        Intended as an account-takeover detection signal for the account
        owner — if they didn't initiate the change, this is what would
        eventually become the email that tips them off. For now it only
        logs; real delivery is a follow-up once mail infrastructure exists.
        """
        logger.warning(
            "Password changed for user_id=%s username=%s " "(email notification not yet implemented — logging only)",
            user.id,
            user.username,
        )
