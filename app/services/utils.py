"""Small cross-service helpers with no natural home in a single service."""

from sqlalchemy.exc import IntegrityError


def integrity_error_message(exc: IntegrityError) -> str:
    """Return the DB driver's own error text from `exc`, falling back to
    the exception's string form. Services match domain-specific
    substrings (e.g. a constraint name) agains this to translate a
    raw IntegrityError into a specific domain exception."""

    return str(exc.orig) if getattr(exc, "orig", None) is not None else str(exc)
