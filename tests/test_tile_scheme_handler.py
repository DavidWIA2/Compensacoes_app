from app.services import tile_scheme_handler


def test_install_tile_scheme_reuses_handler_for_same_profile(monkeypatch):
    installs = []

    class FakeProfile:
        def installUrlSchemeHandler(self, scheme_name, handler):
            installs.append((scheme_name, handler))

    class FakeHandler:
        def __init__(self, parent=None, **kwargs):
            self.parent = parent

    fake_profile = FakeProfile()

    monkeypatch.setattr(tile_scheme_handler, "TileSchemeHandler", FakeHandler)
    monkeypatch.setattr(
        tile_scheme_handler,
        "QWebEngineProfile",
        type("ProfileNS", (), {"defaultProfile": staticmethod(lambda: fake_profile)}),
    )
    monkeypatch.setattr(tile_scheme_handler, "_INSTALLED_HANDLERS", {})

    first = tile_scheme_handler.install_tile_scheme()
    second = tile_scheme_handler.install_tile_scheme(fake_profile)

    assert first is second
    assert len(installs) == 1
    assert installs[0][0] == tile_scheme_handler.TILE_SCHEME_NAME
