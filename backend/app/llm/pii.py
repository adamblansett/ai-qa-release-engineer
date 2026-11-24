import re
from dataclasses import dataclass

from pydantic import BaseModel


class RedactionFinding(BaseModel):
    """Summary count of redacted PII or secret tokens by category."""

    category: str
    count: int
    placeholder: str


class RedactionResult(BaseModel):
    """Result returned by PII and CI secret scrubbing before outbound cloud inference."""

    redacted_text: str
    findings: list[RedactionFinding]
    total_redactions: int


@dataclass(frozen=True)
class _PatternRule:
    category: str
    placeholder: str
    pattern: re.Pattern[str]


_RULES: tuple[_PatternRule, ...] = (
    _PatternRule(
        category="private_key",
        placeholder="[REDACTED_PRIVATE_KEY]",
        pattern=re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
        ),
    ),
    _PatternRule(
        category="credential_uri",
        placeholder="[REDACTED_CREDENTIAL_URI]",
        pattern=re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s:@/]+:[^\s@/]+@[^\s/]+"),
    ),
    _PatternRule(
        category="jwt_token",
        placeholder="[REDACTED_JWT]",
        pattern=re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    ),
    _PatternRule(
        category="bearer_token",
        placeholder="Bearer [REDACTED_TOKEN]",
        pattern=re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    ),
    _PatternRule(
        category="api_key",
        placeholder="[REDACTED_API_KEY]",
        pattern=re.compile(
            r"\b(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
            r"AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|"
            r"sk-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})\b"
        ),
    ),
    _PatternRule(
        category="secret_assignment",
        placeholder="[REDACTED_SECRET]",
        pattern=re.compile(
            r"(?i)\b(?:password|passwd|secret|api_key|apikey|access_token|"
            r"auth_token|client_secret)\b\s*[:=]\s*['\"]?(?!\[REDACTED_)[^\s'\"\\,;]{4,}['\"]?"
        ),
    ),
    _PatternRule(
        category="ssn",
        placeholder="[REDACTED_SSN]",
        pattern=re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    ),
    _PatternRule(
        category="email",
        placeholder="[REDACTED_EMAIL]",
        pattern=re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    _PatternRule(
        category="phone",
        placeholder="[REDACTED_PHONE]",
        pattern=re.compile(r"(?<!\w)(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}\b"),
    ),
)

_CARD_CANDIDATE_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn_valid(digits: str) -> bool:
    if not digits.isdigit() or not (13 <= len(digits) <= 19):
        return False
    total = 0
    reverse_digits = digits[::-1]
    for idx, ch in enumerate(reverse_digits):
        n = int(ch)
        if idx % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def redact_pii(text: str) -> RedactionResult:
    """Scrub sensitive PII, tokens, and CI secrets before sending to external LLMs."""
    if not text:
        return RedactionResult(redacted_text="", findings=[], total_redactions=0)

    working = text
    counts: dict[tuple[str, str], int] = {}

    for rule in _RULES:
        working, n = rule.pattern.subn(rule.placeholder, working)
        if n > 0:
            key = (rule.category, rule.placeholder)
            counts[key] = counts.get(key, 0) + n

    card_count = 0

    def _replace_card(match: re.Match[str]) -> str:
        nonlocal card_count
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if _luhn_valid(digits):
            card_count += 1
            return "[REDACTED_CARD]"
        return raw

    working = _CARD_CANDIDATE_RE.sub(_replace_card, working)
    if card_count > 0:
        key = ("payment_card", "[REDACTED_CARD]")
        counts[key] = counts.get(key, 0) + card_count

    findings = [
        RedactionFinding(category=cat, count=cnt, placeholder=ph)
        for (cat, ph), cnt in counts.items()
    ]
    total = sum(f.count for f in findings)
    return RedactionResult(
        redacted_text=working,
        findings=findings,
        total_redactions=total,
    )
