#!/usr/bin/env python3
"""Check application, Debian and schema versions without importing dependencies."""
import ast
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = {
    "nipap": "nipap/__init__.py", "pynipap": "pynipap/__init__.py",
    "nipap-www": "nipapwww/__init__.py", "nipap-cli": "nipap_cli/__init__.py",
    "whoisd": "nipap_whoisd.py",
}


def constant(path, name):
    for statement in ast.parse(path.read_text()).body:
        if isinstance(statement, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in statement.targets):
                return ast.literal_eval(statement.value)
    raise ValueError(f"Missing {name} in {path}")


def check(tag=None):
    version = constant(ROOT / "nipap/nipap/__init__.py", "__version__")
    if tag is not None and tag != "v" + version:
        raise ValueError(f"Tag {tag!r} does not match v{version}")
    for project, module in PROJECTS.items():
        if constant(ROOT / project / module, "__version__") != version:
            raise ValueError(f"Application version mismatch: {project}")
        first = (ROOT / project / "debian/changelog").read_text().splitlines()[0]
        if f"({version}-1) trixie;" not in first:
            raise ValueError(f"Debian release version/distribution mismatch: {project}")
    if not (ROOT / "NEWS").read_text().startswith(f"Version {version}\n"):
        raise ValueError("NEWS does not describe this release")
    schema = constant(ROOT / "nipap/nipap/__init__.py", "__db_version__")
    sql = (ROOT / "nipap/sql/ip_net.plsql").read_text()
    if f"NIPAP database - schema version: {schema}'" not in sql:
        raise ValueError("SQL schema version mismatch")
    config = (ROOT / "nipap/debian/nipapd.config").read_text()
    if not re.search(rf"^CURRENT_DB_VERSION={schema}$", config, re.M):
        raise ValueError("Debian configuration schema version mismatch")
    for previous in range(1, schema):
        if not (ROOT / f"nipap/sql/upgrade-{previous}-{previous + 1}.plsql").is_file():
            raise ValueError(f"Missing schema migration from {previous}")
    if not (ROOT / f"docs/releases/{version}.md").is_file():
        raise ValueError("Release notes are missing")
    print(version)


if __name__ == "__main__":
    try:
        check(sys.argv[1] if len(sys.argv) > 1 else None)
    except ValueError as error:
        sys.exit(str(error))
