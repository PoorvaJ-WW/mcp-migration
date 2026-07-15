from pathlib import Path

from mcp_migration.manifests import scan_manifest


def _scan(tmp_path: Path, name: str, content: str):
    f = tmp_path / name
    f.write_text(content)
    return scan_manifest(f, name)


def test_python_v1_pin_flagged(tmp_path):
    findings = _scan(tmp_path, "pyproject.toml",
                     '[project]\ndependencies = ["mcp>=1.2.0", "httpx"]\n')
    assert len(findings) == 1
    assert findings[0].rule.code == "C302"
    assert "2.0.0b1" in findings[0].message


def test_python_v2_pin_clean(tmp_path):
    assert _scan(tmp_path, "requirements.txt", "mcp==2.0.0b1\n") == []


def test_similar_package_names_ignored(tmp_path):
    assert _scan(tmp_path, "requirements.txt",
                 "fastmcp>=1.0\nmcp-migration==0.1.0\n") == []


def test_extras_pin_flagged(tmp_path):
    findings = _scan(tmp_path, "requirements.txt", "mcp[cli]==1.9.4\n")
    assert len(findings) == 1


def test_pyproject_keywords_not_flagged(tmp_path):
    # "mcp" as a keyword / classifier string is not a dependency
    findings = _scan(tmp_path, "pyproject.toml", (
        '[project]\n'
        'keywords = ["okf", "mcp", "lint"]\n'
        'dependencies = ["pyyaml>=6.0"]\n'
        '[project.optional-dependencies]\n'
        'serve = ["mcp>=1.2.0"]\n'))
    assert len(findings) == 1
    assert findings[0].snippet == "mcp>=1.2.0"


def test_typescript_sdk_flagged_with_codemod_hint(tmp_path):
    findings = _scan(tmp_path, "package.json",
                     '{"dependencies": {"@modelcontextprotocol/sdk": "^1.12.0"}}')
    assert len(findings) == 1
    assert "codemod" in findings[0].message


def test_go_sdk_versions(tmp_path):
    old = "require github.com/modelcontextprotocol/go-sdk v1.5.0\n"
    new = "require github.com/modelcontextprotocol/go-sdk v1.7.0\n"
    assert len(_scan(tmp_path, "go.mod", old)) == 1
    assert _scan(tmp_path, "go.mod", new) == []
