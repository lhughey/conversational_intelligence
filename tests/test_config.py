"""Credentials resolve from THIS repo, never a sibling project."""

import pathlib

from convint import config


def test_env_path_is_inside_this_repository():
    assert config.ENV_PATH.parent == pathlib.Path(config.REPO_ROOT)
    assert config.ENV_PATH.name == ".env"


def test_exported_variables_win_over_the_env_file(monkeypatch):
    monkeypatch.setenv("CONVINT_PROBE", "from-environment")
    config.load(force=True)
    assert config.get("CONVINT_PROBE") == "from-environment"


def test_require_names_the_file_to_edit():
    try:
        config.require("DEFINITELY_NOT_SET_ANYWHERE")
    except RuntimeError as exc:
        assert ".env" in str(exc)
        assert "will not inherit" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_status_reports_the_resolved_file():
    st = config.status()
    assert st["env_file"].endswith("conversational_intelligence/.env")
