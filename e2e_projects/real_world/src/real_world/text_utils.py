"""Text processing utilities."""
import re


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace into single spaces and strip."""
    return re.sub(r"\s+", " ", text).strip()


def extract_emails(text: str) -> list[str]:
    """Return all email addresses found in text."""
    pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    return re.findall(pattern, text)


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug: lowercase, non-alnum to hyphens, strip edges."""
    lowered = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    return slug.strip("-")


def truncate(text: str, max_len: int, suffix: str = "...") -> str:
    """Truncate text to max_len. Append suffix if truncated."""
    if len(text) <= max_len:
        return text
    if max_len <= len(suffix):
        return suffix[:max_len]
    return text[: max_len - len(suffix)] + suffix


def is_valid_identifier(name: str) -> bool:
    """Check if name is a valid Python identifier (no keywords)."""
    import keyword

    if not isinstance(name, str):
        return False
    return name.isidentifier() and not keyword.iskeyword(name)


def render_template(template: str, context: dict[str, str]) -> str:
    """Replace {{key}} placeholders with values from context. Missing keys left as-is."""

    def replacer(match: re.Match) -> str:
        key = match.group(1)
        return context.get(key, match.group(0))

    return re.sub(r"\{\{(\w+)\}\}", replacer, template)


def count_words(text: str) -> int:
    """Count whitespace-separated words. Empty/whitespace-only returns 0."""
    if not text or not text.strip():
        return 0
    return len(text.split())
