"""fly.toml: one always-on machine with one volume (hosted design H3, 4.10)."""

import tomllib

from tests.harness import REPO_ROOT

FLY = tomllib.loads((REPO_ROOT / "fly.toml").read_text(encoding="utf-8"))


def test_one_always_on_machine_with_one_volume() -> None:
    assert FLY["app"] == "realoem-searcher"
    service = FLY["http_service"]
    assert (service["internal_port"], service["force_https"]) == (8080, True)
    assert (service["auto_stop_machines"], service["min_machines_running"]) == ("off", 1)
    assert service["auto_start_machines"] is False  # a crash-looped machine stays stopped
    assert service["http_options"] == {"idle_timeout": 180}  # past a 50 s call and a slow fetch
    assert service["concurrency"] == {"type": "requests", "soft_limit": 100, "hard_limit": 200}
    (check,) = service["checks"]
    assert (check["method"], check["path"]) == ("GET", "/healthz")
    assert FLY["mounts"] == [{"source": "realoem_data", "destination": "/data"}]
    assert FLY["restart"] == [{"policy": "on-failure", "retries": 10}]
    assert FLY["vm"] == [{"size": "shared-cpu-1x", "memory": "512mb"}]
    assert FLY["build"] == {"dockerfile": "server/Dockerfile"}


def test_the_server_keeps_its_data_on_the_volume() -> None:
    # Other settings (a different call limit, say) may join these.
    assert (
        FLY["env"].items()
        >= {
            "REALOEM_PUBLIC_URL": "https://realoem-searcher.fly.dev",
            "REALOEM_CACHE_DIR": "/data/cache",
            "REALOEM_DATA_DIR": "/data/data",
            "REALOEM_BRANDS_DIR": "/app/brands",
        }.items()
    )
