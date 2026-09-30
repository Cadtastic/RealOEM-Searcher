from pathlib import Path

import pytest

from realoem_mcp import __version__
from realoem_mcp.config import DEFAULT_BRANDS_DIR, USER_AGENT, Settings


def test_defaults() -> None:
    settings = Settings()
    assert settings.base_url == "https://www.realoem.com"
    assert settings.lang == "enUS"
    assert settings.min_interval_s == 2.0
    assert settings.timeout_s == 20.0
    assert settings.cache_dir.name  # platformdirs user cache dir
    assert settings.data_dir.name  # platformdirs user data dir
    assert settings.data_dir != settings.cache_dir
    assert settings.brands_dir == DEFAULT_BRANDS_DIR
    assert (DEFAULT_BRANDS_DIR.parent / "server" / "pyproject.toml").exists()


def test_user_agent_is_honest_and_versioned() -> None:
    expected = f"RealOEM-Searcher/{__version__} (+https://github.com/Cadtastic/RealOEM-Searcher)"
    assert expected == USER_AGENT
    assert Settings().user_agent == USER_AGENT


def test_from_env_overrides(tmp_path: Path) -> None:
    settings = Settings.from_env(
        {
            "REALOEM_BASE_URL": "http://localhost:8080/",
            "REALOEM_MIN_INTERVAL": "3.5",
            "REALOEM_TIMEOUT": "7",
            "REALOEM_CACHE_DIR": str(tmp_path / "cache"),
            "REALOEM_DATA_DIR": str(tmp_path / "data"),
            "REALOEM_BRANDS_DIR": str(tmp_path / "brands"),
        }
    )
    assert settings.base_url == "http://localhost:8080"
    assert settings.min_interval_s == 3.5
    assert settings.timeout_s == 7.0
    assert settings.cache_dir == tmp_path / "cache"
    assert settings.data_dir == tmp_path / "data"
    assert settings.brands_dir == tmp_path / "brands"


def test_min_interval_is_clamped_to_one_second() -> None:
    assert Settings.from_env({"REALOEM_MIN_INTERVAL": "0.1"}).min_interval_s == 1.0
    assert Settings(min_interval_s=0).min_interval_s == 1.0


def test_user_agent_and_lang_cannot_be_overridden() -> None:
    settings = Settings.from_env({"REALOEM_USER_AGENT": "Mozilla/5.0", "REALOEM_LANG": "de"})
    assert settings.user_agent == USER_AGENT
    assert settings.lang == "enUS"
    with pytest.raises(TypeError):
        Settings(user_agent="Mozilla/5.0")  # type: ignore[call-arg]


@pytest.mark.parametrize("value", ["soon", "nan", "inf", "-inf"])
@pytest.mark.parametrize("name", ["REALOEM_MIN_INTERVAL", "REALOEM_TIMEOUT"])
def test_bad_number_names_the_variable(name: str, value: str) -> None:
    with pytest.raises(ValueError, match=name):
        Settings.from_env({name: value})


@pytest.mark.parametrize("field", ["min_interval_s", "timeout_s"])
@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_values_are_rejected_directly(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=field):
        Settings(**{field: value})
