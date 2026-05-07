from pathlib import Path

import meshcore.serial_cx


path = Path(meshcore.serial_cx.__file__)
text = path.read_text()
old = "                transport.serial.rts = False  # You can manipulate Serial object via transport\n"
new = """                try:
                    transport.serial.rts = False  # Some HA passthrough devices do not support modem control.
                except OSError as exc:
                    logger.debug("Unable to set serial RTS state: %s", exc)
"""

if old not in text:
    raise SystemExit(f"Expected RTS assignment not found in {path}")

path.write_text(text.replace(old, new))
print(f"Patched MeshCore serial RTS handling in {path}")
