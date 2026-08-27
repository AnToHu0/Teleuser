import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_portable_agent_skill_is_present():
    skill = ROOT / "skills" / "teleuser"
    assert (skill / "SKILL.md").is_file()
    assert not (ROOT / ".agents" / "skills" / "teleuser" / "SKILL.md").is_file()


def test_agent_installation_guides_are_present():
    assert (ROOT / "AGENTS.md").is_file()
    assert (ROOT / "CLAUDE.md").is_file()


def test_source_distribution_includes_portable_skill_and_agent_guides():
    sdist = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["hatch"]["build"][
        "targets"
    ]["sdist"]["include"]

    assert "/skills" in sdist
    assert "/AGENTS.md" in sdist
    assert "/CLAUDE.md" in sdist


def test_windows_credential_backend_is_packaged_only_for_windows():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    dependency = next(item for item in project["dependencies"] if item.startswith("keyring"))

    assert "sys_platform == 'win32'" in dependency
    assert (ROOT / "src" / "teleuser" / "windows_credentials.py").is_file()
