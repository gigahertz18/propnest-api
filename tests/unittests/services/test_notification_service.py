from types import SimpleNamespace

from app.services.notification_service import (
    LoggingNotificationChannel,
    NotificationChannel,
    NotificationService,
)


class SpyChannel(NotificationChannel):
    def __init__(self):
        self.calls = []

    def send(self, recipient, subject, body):
        self.calls.append((recipient, subject, body))


def _user(id=1, username="alice", email="alice@example.com"):
    return SimpleNamespace(id=id, username=username, email=email)


class TestNotificationServiceSend:
    def test_dispatches_to_all_configured_channels(self):
        first, second = SpyChannel(), SpyChannel()
        svc = NotificationService(channels=[first, second])

        svc.send(recipient="bob@example.com", subject="hi", body="body text")

        assert first.calls == [("bob@example.com", "hi", "body text")]
        assert second.calls == [("bob@example.com", "hi", "body text")]

    def test_defaults_to_logging_channel_when_none_given(self):
        svc = NotificationService()

        assert len(svc.channels) == 1
        assert isinstance(svc.channels[0], LoggingNotificationChannel)


class TestNotifyPasswordChanged:
    def test_dispatches_through_configured_channels(self):
        spy = SpyChannel()
        svc = NotificationService(channels=[spy])
        user = _user()

        svc.notify_password_changed(user)

        assert len(spy.calls) == 1
        recipient, subject, body = spy.calls[0]
        assert recipient == user.email
        assert "password" in subject.lower()
        assert str(user.id) in body
        assert user.username in body


class TestLoggingNotificationChannel:
    def test_send_logs_instead_of_raising(self, caplog):
        channel = LoggingNotificationChannel()

        with caplog.at_level("WARNING"):
            channel.send(recipient="bob@example.com", subject="hi", body="body text")

        assert "bob@example.com" in caplog.text
        assert "hi" in caplog.text
