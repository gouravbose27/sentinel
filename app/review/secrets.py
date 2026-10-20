import re

# Each pattern's group 1 is the secret value.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("hardcoded credential", re.compile(
        r"""(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|auth[_-]?token|client[_-]?secret|token)\b"""
        r"""\s*[:=]\s*["']([^"'\s]{6,})["']""")),
    ("SQL password literal", re.compile(r"""(?i)\bPASSWORD\s+['"]([^'"]{4,})['"]""")),
    ("connection string secret", re.compile(
        r"(?i)(?<=[;\"'])\s*\b(?:AccountKey|SharedAccessKey|Password|Pwd)=([^;\"'\s]{6,})")),
    ("AWS access key", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
    ("private key", re.compile(r"(-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----)")),
    ("GitHub token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,})\b")),
    ("API key", re.compile(r"\b(sk-[A-Za-z0-9_\-]{20,})\b")),
    ("JWT", re.compile(r"\b(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b")),
)

_PLACEHOLDER = re.compile(
    r"(?i)^(<.*>|\$\{.*\}|\{\{.*\}\}|%\(.*\)s|x{3,}|\*{3,}|changeme|change_me|your[_-].*|example.*|dummy.*|placeholder.*|"
    r"test|none|null|password|secret|token)$"
)


def is_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER.match(value))


def find_secrets(line: str) -> list[str]:
    """Names of secret kinds found in a line, ignoring obvious placeholders."""
    found = []
    for name, pattern in SECRET_PATTERNS:
        if any(not is_placeholder(m.group(1)) for m in pattern.finditer(line)):
            found.append(name)
    return found


def redact(text: str) -> str:
    """Mask secret values so they are not sent to the LLM."""
    for _, pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(0).replace(m.group(1), "[REDACTED]"), text)
    return text
