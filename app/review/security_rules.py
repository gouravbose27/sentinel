import re
from dataclasses import dataclass

from app.models.schemas import Category, ChangedFile, Finding, Severity
from app.review.chunker import added_lines
from app.review.secrets import find_secrets

PY = frozenset({"python", "pyspark"})
SQL = frozenset({"sql", "sparksql"})

MAX_RULE_FINDINGS = 50


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern[str]
    severity: Severity
    confidence: float
    title: str
    description: str
    cwe: str
    languages: frozenset[str] | None = None
    suggestion: str | None = None


RULES: tuple[Rule, ...] = (
    Rule(re.compile(r"(?<![.\w])(?:eval|exec)\s*\("), Severity.HIGH, 0.7,
         "Use of eval/exec",
         "Executing dynamically built code allows arbitrary code execution if any part is attacker-influenced.",
         "CWE-95", PY, "Use ast.literal_eval or an explicit dispatch table."),
    Rule(re.compile(r"\b(?:c?[pP]ickle|marshal)\.loads?\("), Severity.HIGH, 0.6,
         "Unsafe deserialization",
         "pickle/marshal can execute arbitrary code when loading untrusted data.",
         "CWE-502", PY, "Use JSON or another data-only format for untrusted input."),
    Rule(re.compile(r"\byaml\.load\((?![^)]*Loader\s*=\s*(?:yaml\.)?C?SafeLoader)"), Severity.HIGH, 0.7,
         "yaml.load without SafeLoader",
         "The default YAML loader can construct arbitrary Python objects.",
         "CWE-502", PY, "yaml.safe_load(data)"),
    Rule(re.compile(r"shell\s*=\s*True|\bos\.system\s*\("), Severity.HIGH, 0.7,
         "Shell command execution",
         "Running commands through a shell enables command injection when arguments contain user input.",
         "CWE-78", PY, "Pass an argument list to subprocess.run without shell=True."),
    Rule(re.compile(r"verify\s*=\s*False"), Severity.MEDIUM, 0.8,
         "TLS certificate verification disabled",
         "Disabling verification makes the connection vulnerable to man-in-the-middle attacks.",
         "CWE-295", PY),
    Rule(re.compile(r"\bhashlib\.(?:md5|sha1)\("), Severity.LOW, 0.5,
         "Weak hash algorithm",
         "MD5 and SHA-1 are not collision resistant; do not use them for security purposes.",
         "CWE-327", PY, "Use hashlib.sha256 (or a password hashing function for credentials)."),
    Rule(re.compile(r"\btempfile\.mktemp\("), Severity.MEDIUM, 0.8,
         "Insecure temporary file",
         "mktemp is racy: another process can create the file between name generation and use.",
         "CWE-377", PY, "Use tempfile.NamedTemporaryFile or tempfile.mkstemp."),
    Rule(re.compile(
        r"(?:execute|executemany|read_sql(?:_query)?|spark\.sql|\.sql)\s*\(\s*"
        r"(?:[rR]?[fF][rR]?[\"'][^\"'\n]*\{|[\"'][^\"'\n]*[\"']\s*(?:%\s*[\w(]|\+\s*[\w(]|\.format\())"),
         Severity.HIGH, 0.7,
         "SQL built with string interpolation",
         "Interpolating values into SQL text allows SQL injection if any value is attacker-influenced.",
         "CWE-89", PY, "Use parameterized queries (or spark.sql(query, args=...))."),
    Rule(re.compile(r"\bGRANT\s+ALL\b|\bGRANT\b[^;]*\bTO\s+PUBLIC\b", re.IGNORECASE), Severity.MEDIUM, 0.7,
         "Overly broad privileges",
         "Granting ALL privileges or access to PUBLIC violates least privilege.",
         "CWE-269", SQL, "Grant only the specific privileges each principal needs."),
    Rule(re.compile(r"\bEXEC(?:UTE)?\s+(?:IMMEDIATE\s+)?[^;]*(?:\|\||\+)", re.IGNORECASE), Severity.MEDIUM, 0.5,
         "Dynamic SQL from concatenation",
         "Executing SQL assembled by concatenation can allow SQL injection.",
         "CWE-89", SQL),
)


def scan(file: ChangedFile) -> list[Finding]:
    """Deterministic checks over the lines this PR added or rewrote."""
    added = added_lines(file.base_content, file.head_content)
    lines = file.head_content.splitlines()
    findings: list[Finding] = []

    for number in sorted(added):
        line = lines[number - 1]
        for kind in find_secrets(line):
            findings.append(Finding(
                category=Category.SECURITY, severity=Severity.HIGH, confidence=0.85,
                file=file.path, line_start=number, line_end=number,
                title=f"Possible {kind} in source",
                description="A credential-like value is committed to source control. Anyone with repository "
                            "access can read it, and it stays in history after removal.",
                suggestion="Load it from a secret store or environment variable and rotate the exposed value.",
                references=["CWE-798"],
            ))
        for rule in RULES:
            if rule.languages and file.language not in rule.languages:
                continue
            if rule.pattern.search(line):
                findings.append(Finding(
                    category=Category.SECURITY, severity=rule.severity, confidence=rule.confidence,
                    file=file.path, line_start=number, line_end=number,
                    title=rule.title, description=rule.description,
                    suggestion=rule.suggestion, references=[rule.cwe],
                ))
        if len(findings) >= MAX_RULE_FINDINGS:
            break
    return findings
