from app.models.schemas import ChangedFile, Severity
from app.review.aggregator import aggregate
from app.review.secrets import find_secrets, redact
from app.review.security_rules import scan
from app.models.schemas import Category, Finding


def make_file(head: str, base: str = "", path: str = "/a.py", language: str = "python") -> ChangedFile:
    return ChangedFile(path, "edit", language, base, head)


def test_secrets_detected_and_placeholders_ignored():
    assert "hardcoded credential" in find_secrets('api_key = "sk_live_abcdef123456"')
    assert find_secrets('password = "changeme"') == []
    assert find_secrets("password = os.environ['PW']") == []
    assert "AWS access key" in find_secrets("key = AKIAABCDEFGHIJKLMNOP")


def test_redact_masks_value_only():
    out = redact('conn = "Server=x;Password=Hunter2Hunter2;"')
    assert "Hunter2" not in out and "[REDACTED]" in out and "Password=" in out


def test_scan_only_reports_added_lines_and_never_echoes_secret():
    base = 'old = "AKIAABCDEFGHIJKLMNOP"\n'
    head = base + 'token = "abcdef123456789"\nrows = spark.sql(f"select * from t where id={x}")\n'
    findings = scan(make_file(head, base, language="pyspark"))
    assert {f.line_start for f in findings} == {2, 3}  # the pre-existing key on line 1 is ignored
    assert all("abcdef123456789" not in f.description + f.title for f in findings)
    assert any("CWE-89" in f.references for f in findings)


def test_language_specific_rules():
    sql = make_file("GRANT ALL ON t TO analysts;\n", path="/a.sql", language="sql")
    assert [f.title for f in scan(sql)] == ["Overly broad privileges"]
    py_only = make_file("GRANT ALL = 1\neval(x)\n", path="/b.py")
    assert [f.title for f in scan(py_only)] == ["Use of eval/exec"]


def _finding(title, line, refs=(), sev=Severity.HIGH, conf=0.8, cat=Category.SECURITY):
    return Finding(category=cat, severity=sev, confidence=conf, file="/a.py", line_start=line,
                   title=title, description="d", references=list(refs))


def test_aggregate_merges_rule_and_llm_duplicates():
    rule = _finding("SQL built with string interpolation", 3, ["CWE-89"], conf=0.7)
    llm = _finding("Possible SQL injection in query", 3, ["CWE-89"], sev=Severity.CRITICAL, conf=0.9)
    other = _finding("Weak hash", 9, ["CWE-327"], sev=Severity.LOW)
    result = aggregate([rule, llm, other], min_confidence=0.4)
    assert [f.title for f in result] == ["Possible SQL injection in query", "Weak hash"]
    assert result[0].severity is Severity.CRITICAL


def test_aggregate_filters_and_keeps_distinct_categories():
    a = _finding("Same line", 5, cat=Category.BUG)
    b = _finding("Same line", 5, cat=Category.SECURITY)
    low = _finding("Unsure", 7, conf=0.1)
    assert len(aggregate([a, b, low], min_confidence=0.4)) == 2
