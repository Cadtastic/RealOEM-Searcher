"""Settings of the hosted ("http") mode (hosted design 4.1, 4.8)."""

import pytest

from realoem_mcp.config import Settings

MB = 1024 * 1024


def test_stdio_defaults_leave_every_hosted_feature_off() -> None:
    settings = Settings()
    assert settings.mode == "stdio"
    assert settings.admins == frozenset()
    assert (settings.user_daily_limit, settings.new_user_daily_limit) == (300, 30)
    assert settings.min_account_age_days == 30
    assert settings.global_daily_limit == 0
    assert settings.call_deadline_s == 50.0
    assert settings.cache_max_mb is None
    assert (settings.cache_max_bytes, settings.cache_min_free_bytes) == (0, 0)


def test_http_mode_turns_on_the_cache_cap_and_the_free_space_floor() -> None:
    settings = Settings(mode="http")
    assert settings.cache_max_bytes == 400 * MB
    assert settings.cache_min_free_bytes == 100 * MB
    assert Settings(mode="http", cache_max_mb=0).cache_max_bytes == 0
    assert Settings(cache_max_mb=5).cache_max_bytes == 5 * MB  # stdio can opt in


def test_from_env_reads_the_hosted_settings_but_never_the_mode() -> None:
    settings = Settings.from_env(
        {
            "REALOEM_MODE": "http",  # not a setting: only the HTTP entry point sets the mode
            "REALOEM_ADMINS": " 123, 456 ,",
            "REALOEM_USER_DAILY_LIMIT": "50",
            "REALOEM_NEW_USER_DAILY_LIMIT": "5",
            "REALOEM_MIN_ACCOUNT_AGE_DAYS": "7",
            "REALOEM_GLOBAL_DAILY_LIMIT": "2000",
            "REALOEM_CALL_DEADLINE_S": "40",
            "REALOEM_CACHE_MAX_MB": "100",
        }
    )
    assert settings.mode == "stdio"
    assert settings.admins == frozenset({"github:123", "github:456"})
    assert (settings.user_daily_limit, settings.new_user_daily_limit) == (50, 5)
    assert (settings.min_account_age_days, settings.global_daily_limit) == (7, 2000)
    assert settings.call_deadline_s == 40.0
    assert settings.cache_max_bytes == 100 * MB


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("REALOEM_USER_DAILY_LIMIT", "-1"),
        ("REALOEM_NEW_USER_DAILY_LIMIT", "many"),
        ("REALOEM_MIN_ACCOUNT_AGE_DAYS", "1.5"),
        ("REALOEM_GLOBAL_DAILY_LIMIT", "x"),
        ("REALOEM_CACHE_MAX_MB", "1.5"),
        ("REALOEM_CALL_DEADLINE_S", "0"),
        ("REALOEM_CALL_DEADLINE_S", "soon"),
        ("REALOEM_ADMINS", "octocat"),
    ],
)
def test_a_bad_hosted_value_names_its_variable(name: str, value: str) -> None:
    with pytest.raises(ValueError, match=name):
        Settings.from_env({name: value})


def test_mode_must_be_stdio_or_http() -> None:
    with pytest.raises(ValueError, match="mode must be 'stdio' or 'http'"):
        Settings(mode="cli")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"user_daily_limit": -1},
        {"global_daily_limit": 1.5},
        {"min_account_age_days": True},
        {"cache_max_mb": -1},
        {"call_deadline_s": 0},
        {"call_deadline_s": float("inf")},
        {"call_deadline_s": True},
        {"admins": "github:1"},  # a string, not a set of subjects
        {"admins": frozenset({"123"})},  # a bare id
    ],
)
def test_bad_direct_values_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError, match=next(iter(kwargs))):
        Settings(**kwargs)  # type: ignore[arg-type]
