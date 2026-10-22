"""PR9 repository-layout contract and HACS packaging checks.

The production integration is intentionally stored in the canonical
custom_components/<domain> directory, not in the repository root.
"""

import json

from conftest import ROOT, SOURCE_ROOT

DOMAIN = "fmi"

PRODUCTION_FILES = (
    "__init__.py",
    "config_flow.py",
    "const.py",
    "forecast.py",
    "sensor.py",
    "utils.py",
    "weather.py",
    "wfs.py",
    "manifest.json",
    "strings.json",
)

TRANSLATIONS = ("en.json", "fi.json", "ru.json")


def test_component_lives_at_canonical_location_only():
    assert SOURCE_ROOT == ROOT / "custom_components" / DOMAIN
    assert SOURCE_ROOT.is_dir()
    for filename in PRODUCTION_FILES:
        assert (SOURCE_ROOT / filename).is_file(), filename
        assert not (ROOT / filename).exists(), filename
    for filename in TRANSLATIONS:
        assert (SOURCE_ROOT / "translations" / filename).is_file(), filename
        assert not (ROOT / "translations" / filename).exists(), filename


def test_hacs_uses_standard_integration_directory():
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (SOURCE_ROOT / "manifest.json").read_text(encoding="utf-8")
    )
    assert hacs["name"] == "FMI"
    assert hacs.get("content_in_root") is not True
    assert manifest["domain"] == DOMAIN
    assert manifest["version"] == "0.9.0"
    assert manifest["config_flow"] is True


def test_ci_uses_actual_component_directory_without_root_repackaging():
    workflow = (ROOT / ".github/workflows/verify.yml").read_text()
    runner = (ROOT / ".github/scripts/run-ha-tests.sh").read_text()
    assert "pylint custom_components/fmi/*.py" in workflow
    assert "$GITHUB_WORKSPACE/custom_components/fmi:" in workflow
    assert 'cp -R "$repo_root/custom_components/fmi"' in runner
    assert 'cp "$repo_root"/*.py' not in runner


def test_release_notes_and_manifest_version_are_consistent():
    """Release candidate metadata and root documentation must agree."""
    manifest = json.loads((SOURCE_ROOT / "manifest.json").read_text())
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    checklist = (ROOT / "RELEASE_CHECKLIST_0.9.0.md").read_text()
    notes = (ROOT / "RELEASE_NOTES_0.9.0.md").read_text()
    assert manifest["version"] == "0.9.0"
    assert "## v0.9.0" in changelog
    assert "## v0.8.0" in changelog
    assert "PR10" in changelog and "PR9" in changelog
    assert "CHANGELOG.md" in readme
    assert "## FMI source availability (PR3)" not in readme
    assert "v0.9.0" in checklist and "v0.9.0" in notes
