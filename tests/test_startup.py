import os

from app import main as main_module


def test_resolve_startup_assets_returns_pair_when_files_exist(monkeypatch):
    monkeypatch.setattr(main_module, "resource_path", lambda *parts: os.path.join(*parts))
    monkeypatch.setattr(
        main_module.os.path,
        "exists",
        lambda path: path in {
            os.path.join("assets", "loading.gif"),
            os.path.join("assets", "Splash.png"),
        },
    )

    gif_path, splash_path = main_module.resolve_startup_assets()

    assert gif_path.endswith("loading.gif")
    assert splash_path.endswith("Splash.png")


def test_create_startup_splash_returns_none_without_assets(monkeypatch):
    monkeypatch.setattr(main_module, "resolve_startup_assets", lambda: (None, None))

    assert main_module.create_startup_splash() is None


def test_create_startup_splash_uses_resolved_assets(monkeypatch):
    captured = []

    class FakeSplash:
        def __init__(self, gif_path, splash_path):
            captured.append((gif_path, splash_path))

    monkeypatch.setattr(main_module, "resolve_startup_assets", lambda: ("gif", "splash"))
    monkeypatch.setattr(main_module, "AnimatedSplashScreen", FakeSplash)

    splash = main_module.create_startup_splash()

    assert captured == [("gif", "splash")]
    assert isinstance(splash, FakeSplash)
