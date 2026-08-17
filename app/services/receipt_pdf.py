from io import BytesIO
from pathlib import Path

from jinja2 import Environment, BaseLoader, select_autoescape
from weasyprint import HTML

_jinja_env = Environment(loader=BaseLoader(), autoescape=select_autoescape(["html"]))

# Repo-root-level, not under app/ — a sibling of alembic/, scripts/, docs/ —
# so it stays organized as a home for template *assets* (not Python code) as
# more default templates are added later (e.g. templates/invoice/default.html).
_TEMPLATES_ROOT = Path(__file__).resolve().parent.parent.parent / "templates"
_DEFAULT_RECEIPT_TEMPLATE = _TEMPLATES_ROOT / "receipt" / "default.html"


def load_default_template() -> str:
    """The built-in receipt template, used whenever no ReceiptTemplate row
    is active for a payment's property (or globally). Kept as a plain .html
    file rather than a Python string so it's editable without touching code."""
    return _DEFAULT_RECEIPT_TEMPLATE.read_text()


def _blocked_url_fetcher(url: str):
    """Templates may be uploaded by managers (see ReceiptTemplateService) —
    without this, WeasyPrint would happily follow an <img src="http://...">
    or file:// URL in a template, an SSRF/local-file-read vector this
    print-only PDF path has no reason to allow. `data:` URIs (e.g. an
    inlined base64 logo) never reach this fetcher — WeasyPrint decodes
    those directly — so embedding an image is still possible, just not by
    fetching one from the network or disk."""
    raise ValueError(f"External resource fetching is disabled for receipt rendering: {url}")


def render_receipt_pdf(*, template_html: str, receipt_number: int, payment, property_, tenant) -> BytesIO:
    """Render `template_html` (Jinja2 placeholders) with this receipt's data
    into a PDF, in-memory. Pure function — no DB/storage access — so both
    the built-in default and any uploaded ReceiptTemplate render through
    the exact same path.
    """
    template = _jinja_env.from_string(template_html)
    html = template.render(
        receipt_number=receipt_number,
        property_name=getattr(property_, "name", "-") or "-",
        tenant_name=getattr(tenant, "full_name", "-") or "-",
        amount=payment.amount,
        paid_at=payment.paid_at.isoformat(),
        payment_method=payment.payment_method or "-",
        reference_number=payment.reference_number or "-",
    )
    buf = BytesIO()
    HTML(string=html, url_fetcher=_blocked_url_fetcher).write_pdf(buf)
    buf.seek(0)
    return buf
