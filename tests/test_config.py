from __future__ import annotations

from pathlib import Path

import pytest

from release_health_mcp.config import Config, load_config
from release_health_mcp.thresholds import ThresholdsFile, load_thresholds


def test_resolve_alias_and_package(config: Config) -> None:
    assert config.resolve_app("demo") == "com.example.app"
    assert config.resolve_app("com.example.regressed") == "com.example.regressed"
    assert config.resolve_app(None) == "com.example.app"
    with pytest.raises(ValueError, match="Unknown app"):
        config.resolve_app("nope")


def test_single_app_is_default() -> None:
    assert Config(apps={"x": "com.x"}).resolve_app(None) == "com.x"


def test_no_apps_configured_accepts_any_package() -> None:
    assert Config().resolve_app("com.any") == "com.any"


def test_load_config_resolves_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config.yaml").write_text(
        "backend: play\nthresholds_file: t.yaml\napps: {a: com.a}\n"
    )
    monkeypatch.delenv("RELEASE_HEALTH_BACKEND", raising=False)
    monkeypatch.setenv("RELEASE_HEALTH_READ_KEY", "/keys/k.json")
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg.backend == "play"
    assert cfg.thresholds_file == str(tmp_path / "t.yaml")
    assert cfg.read_key_file == "/keys/k.json"


def test_thresholds_per_app_override(tmp_path: Path) -> None:
    p = tmp_path / "t.yaml"
    p.write_text("defaults: {max_relative_increase: 0.3}\napps: {com.a: {min_user_days: 10}}\n")
    tf = load_thresholds(p)
    assert tf.for_app("com.a").min_user_days == 10
    assert tf.for_app("com.a").max_relative_increase == 0.3
    assert tf.for_app("com.b").min_user_days == 500


def test_invalid_steps_rejected() -> None:
    with pytest.raises(ValueError):
        ThresholdsFile.model_validate({"defaults": {"rollout_steps": [0.5, 2]}})


def test_example_files_are_valid() -> None:
    root = Path(__file__).parent.parent
    load_thresholds(root / "thresholds.example.yaml")
    cfg = load_config(root / "config.example.yaml")
    assert cfg.apps
