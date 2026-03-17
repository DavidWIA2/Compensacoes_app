import os
from types import SimpleNamespace

def run_debug():
    state = {"last_excel_path": "stub_path.xlsx"}
    class MockSettings:
        def __init__(self, *args, **kwargs): pass
        def value(self, key, default=""): return state.get(key, default)
        def setValue(self, key, val): state[key] = val
        def remove(self, key): state.pop(key, None)

    # Simular o comportamento interno do _load_last_excel
    settings = MockSettings()
    path = settings.value("last_excel_path")
    print(f"Path antes: {path}")
    
    # Simulando o mock_exists
    if path and True:  # os.path.exists
        try:
            # Simular o erro do excel.load
            raise RuntimeError("planilha corrompida")
        except Exception as exc:
            settings.remove("last_excel_path")
            print("Removido no except")
            
    print(f"State depois: {state}")

if __name__ == "__main__":
    run_debug()