from pathlib import Path

import nicegui.client


path = Path(nicegui.client.__file__)
text = path.read_text()
old = "        prefix = request.headers.get('X-Forwarded-Prefix', '') + request.scope.get('root_path', '')\n"
new = """        prefix = (
            request.headers.get('X-Forwarded-Prefix', '')
            or request.headers.get('X-Ingress-Path', '')
        ) + request.scope.get('root_path', '')
"""

if old not in text:
    raise SystemExit(f"Expected NiceGUI prefix assignment not found in {path}")

path.write_text(text.replace(old, new))
print(f"Patched NiceGUI ingress prefix handling in {path}")
