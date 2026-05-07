from pathlib import Path


path = Path("/opt/meshcore-gui/meshcore_gui/__main__.py")
text = path.read_text()
marker = "    # ── Start NiceGUI server (blocks) ──\n"
insert = """    # ── Serve custom Home Assistant style UI ──
    custom_ui_dir = Path('/opt/meshcore-custom-ui')
    if custom_ui_dir.is_dir():
        from fastapi.responses import HTMLResponse
        app.add_static_files('/custom-ui', str(custom_ui_dir))

        @app.get('/custom', include_in_schema=False)
        async def _custom_meshcore_ui():
            html = (custom_ui_dir / 'index.html').read_text(encoding='utf-8')
            return HTMLResponse(html)

        print("Custom MeshCore UI enabled — /custom")

"""

if marker not in text:
    raise SystemExit(f"Expected NiceGUI run marker not found in {path}")

path.write_text(text.replace(marker, insert + marker))
print(f"Patched MeshCore GUI custom UI route in {path}")
