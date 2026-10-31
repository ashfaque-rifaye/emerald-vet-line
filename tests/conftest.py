import pytest


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Every test gets its own database, keys and registry."""
    monkeypatch.setenv("EMERALD_DATA", str(tmp_path))
    from emerald import registry

    registry.world.cache_clear()
    registry.world()
    yield
    registry.world.cache_clear()
