from __future__ import annotations

from typing import Any, Callable

from app.ui.controllers.window_command_support import build_window_command_binding_map


class WindowCommandController:
    def __init__(self, window):
        self.window = window
        self._command_bindings = build_window_command_binding_map()

    def list_commands(self) -> tuple[str, ...]:
        return tuple(sorted(self._command_bindings))

    def execute(self, command_name: str, *args, **kwargs):
        binding = self._command_bindings.get(command_name)
        if binding is None:
            raise KeyError(f"Comando desconhecido: {command_name}")
        return binding.resolve(self.window)(*args, **kwargs)

    def build_handler(self, command_name: str, *args, **kwargs) -> Callable[..., Any]:
        def _handler(*_signal_args):
            return self.execute(command_name, *args, **kwargs)

        return _handler

    def __getattr__(self, name: str) -> Any:
        if name in self._command_bindings:
            def _command_proxy(*args, **kwargs):
                return self.execute(name, *args, **kwargs)

            return _command_proxy
        raise AttributeError(name)
