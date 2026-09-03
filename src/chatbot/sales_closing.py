"""
Sales advancement helpers - gentle, grounded closing blocks and CTA text.

These helpers build the "wrap up" message the bot sends once a conversation is
resolved. Everything they say is either a fact from the knowledge base (toll-free
phone, contact email) or a safe, non-committal expectation. URLs come from the
response's own retrieved sources - never invented.
"""

from typing import Any, Dict, List, Optional, Tuple

CLOSING_CONTACT_PHONE = "0800 132 700"
CLOSING_CONTACT_EMAIL = "careulc@oldmutual.co.ug"

_CLOSING_EXPECTATION = (
    "**What to expect:** once you're covered, you'll receive your policy documents "
    "and a confirmation, and most cover starts as agreed on your policy start date."
)
_CLOSING_BUY_CTA = (
    'When you\'re ready to go ahead, **reset the chat, head to the main menu and click "Buy Now"**, '
    "choose what you need, and follow the steps until you're covered."
)

# Portal / self-service links pulled straight from the knowledge base, keyed by
# product. Motor insurance has a public online "Select" page, investment and
# wealth accounts live on the OMIG client portal, and securities trading accounts
# are opened via the USE Easy Portal. Everything else falls back to the product
# page itself. ``resolve_buy_links`` matches on name / product id keywords.
PORTAL_LINKS: List[Tuple[Tuple[str, ...], str]] = [
    (("securities", "scd", "use easy", "trading"), "http://scd.use.or.ug/"),
    (
        ("motor", "motor private", "motor comprehensive", "third party", "comprehensive insurance"),
        "https://www.oldmutual.co.ug/app/public/motor-insurance",
    ),
    (
        ("unit trust", "units", "money market", "dollar", "umbrella", "balanced", "wealth", "omig", "investment"),
        "https://client-portal.oldmutual.co.ug/",
    ),
]

_BUY_EXPECTATION = (
    "**What to expect:** after you submit your details our team picks it up and guides you "
    "through the next steps \u2014 you'll get a confirmation and, once everything's in place, "
    "your cover begins as agreed."
)


def extract_urls(sources: Optional[List[Dict[str, Any]]], limit: int = 3) -> List[str]:
    """Return deduplicated, non-empty URLs from retrieval sources (max ``limit``)."""
    if not sources:
        return []
    urls: List[str] = []
    seen = set()
    for item in sources:
        payload = item.get("payload") or item if isinstance(item, dict) else {}
        url = (payload.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def format_urls(urls: Optional[List[str]]) -> Optional[str]:
    if not urls:
        return None
    return " · ".join(urls)


def contact_block() -> str:
    """Contact line sourced from the Old Mutual get-help knowledge base."""
    return (
        f"And if you're ever confused or stuck, reach us toll-free at **{CLOSING_CONTACT_PHONE}** "
        f"or **{CLOSING_CONTACT_EMAIL}** \u2014 real people, happy to help."
    )


def build_buy_now_cta() -> str:
    return _CLOSING_BUY_CTA


def resolve_buy_links(
    product_label: Optional[str] = None,
    product_id: Optional[str] = None,
    product_url: Optional[str] = None,
) -> List[str]:
    """Return the buy/portal link(s) for a product, grounded in the KB.

    Matches ``product_label``/``product_id`` against known portal categories; if
    nothing matches, falls back to the product's own page. Never invents links.
    """
    haystack = " ".join(p for p in [product_label, product_id] if p).lower()
    primary: Optional[str] = None
    for keywords, link in PORTAL_LINKS:
        if any(k in haystack for k in keywords):
            primary = link
            break
    if primary is None:
        primary = (product_url or "").strip() or None
    if not primary:
        return []

    links = [primary]
    extra = (product_url or "").strip()
    if extra and extra != primary:
        links.append(extra)
    return links


def build_buy_block(
    product_label: Optional[str] = None,
    product_id: Optional[str] = None,
    product_url: Optional[str] = None,
    include_email_note: bool = True,
    include_agent_offer: bool = True,
) -> str:
    """Assemble the buy-intent reply: link(s), what-to-expect, email note,

    an agent offer, and the Buy Now CTA. No contact/phone line - the user-facing
    buttons (Zoho) carry the phone options.
    """
    links = resolve_buy_links(product_label, product_id, product_url)
    parts: List[str] = []

    if links:
        where_line = f"**You can take it up right here:** {format_urls(links)}"
        if product_label:
            where_line += f" \u2014 the fastest way to get {product_label} sorted."
        parts.append(where_line)

    parts.append(_BUY_EXPECTATION)

    if include_email_note:
        parts.append("**I'll also email this conversation to you**, so you can go through it again or catch anything you missed.")

    if include_agent_offer:
        parts.append("And if you have any doubts right now, I can connect you with an agent \u2014 no need to wait.")

    parts.append(build_buy_now_cta())

    return "\n\n".join(parts)


def build_closing_block(
    sources: Optional[List[Dict[str, Any]]] = None,
    urls: Optional[List[str]] = None,
    product_label: Optional[str] = None,
    include_email_note: bool = True,
    include_agent_offer: bool = True,
) -> str:
    """Assemble the gentle, convincing wrap-up message.

    ``urls`` takes precedence over URLs extracted from ``sources``. ``product_label``
    (e.g. "Travel Insurance") is optional and only used to personalise the link line.
    """
    urls = urls if urls is not None else extract_urls(sources)
    parts: List[str] = []

    if urls:
        link_hint = f"**You can always jump back here:** {format_urls(urls)}"
        if product_label:
            link_hint += f" \u2014 everything we just covered on {product_label}."
        parts.append(link_hint)

    parts.append(_CLOSING_EXPECTATION)
    parts.append(contact_block())

    if include_email_note:
        parts.append("**I'll also email this conversation to you**, so you can go through it again or catch anything you missed.")

    if include_agent_offer:
        parts.append("And if you have any doubts right now, I can connect you with an agent \u2014 no need to wait.")

    parts.append(build_buy_now_cta())

    return "\n\n".join(parts)