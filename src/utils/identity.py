import re


EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')


def extract_email(text: str) -> str | None:
    """Extract first valid email from text."""
    match = EMAIL_REGEX.search(text or "")
    return match.group(0).lower() if match else None


def extract_name_from_email(email: str) -> str:
    """Extract first name from email local-part.

    Only the first segment (before any separator) is used so we never
    assume the second part of the email is a real surname.

    Examples:
        john.doe@company.com -> "John"
        jane_doe@company.com -> "Jane"
        john123@company.com -> "John"
        john@company.com -> "John"
    """
    if not email or "@" not in email:
        return "Customer"

    local = email.split("@")[0]
    # Take only the first segment (before any separator)
    first = re.split(r'[._-]+', local)[0].strip()
    # Remove trailing numbers
    first = re.sub(r'\d+$', '', first).strip()
    # Title case
    name = first.title() if first else "Customer"
    return name


def is_valid_email(email: str) -> bool:
    """Validate email format."""
    return bool(EMAIL_REGEX.fullmatch(email or ""))