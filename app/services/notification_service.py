"""
Notification services for security-sensitive account events.

`NotificationChannel` is the extension point for future real delivery
(email/SMS/etc.) — `NotificationService` dispatches `send(recipient, subject,
body)` to every channel it's configured with. PropNest has no real provider
wired up yet, so `LoggingNotificationChannel` is the default: it just logs
instead of sending. Adding a real channel later means implementing
`NotificationChannel` and adding it to the configured list — no changes to
`NotificationService` or its callers.
"""

import logging
from abc import ABC, abstractmethod

from app.models.user import User

logger = logging.getLogger(__name__)


class NotificationChannel(ABC):
    """A destination `NotificationService` can dispatch messages to."""

    @abstractmethod
    def send(self, recipient: str, subject: str, body: str) -> None:
        """Deliver `subject`/`body` to `recipient` via this channel."""


class LoggingNotificationChannel(NotificationChannel):
    """Logs instead of sending — default channel until a real provider exists."""

    def send(self, recipient: str, subject: str, body: str) -> None:
        logger.warning(
            "Notification to recipient=%s subject=%s (delivery not yet implemented — logging only): %s",
            recipient,
            subject,
            body,
        )


class NotificationService:
    """Fires notifications for account-security events, dispatching to configured channels."""

    def __init__(self, channels: list[NotificationChannel] | None = None) -> None:
        self.channels = channels if channels is not None else [LoggingNotificationChannel()]

    def send(self, recipient: str, subject: str, body: str) -> None:
        """Dispatch `subject`/`body` to `recipient` on every configured channel."""
        for channel in self.channels:
            channel.send(recipient, subject, body)

    def notify_password_changed(self, user: User) -> None:
        """
        Signal that `user`'s password was just changed.

        Intended as an account-takeover detection signal for the account
        owner — if they didn't initiate the change, this is what would
        eventually become the email that tips them off.
        """
        self.send(
            recipient=user.email,
            subject="Your password was changed",
            body=f"Password changed for user_id={user.id} username={user.username}.",
        )
