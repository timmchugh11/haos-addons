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
text = path.read_text()
old = "            self.cx._connected_event.set()\n"
new = """            delay = max(0.0, float(getattr(self.cx, "cx_dly", 0.0) or 0.0))
            if delay:
                asyncio.get_running_loop().call_later(delay, self.cx._connected_event.set)
            else:
                self.cx._connected_event.set()
"""

if old not in text:
    raise SystemExit(f"Expected connected-event assignment not found in {path}")

path.write_text(text.replace(old, new))
print(f"Patched MeshCore serial RTS handling and connection delay in {path}")
