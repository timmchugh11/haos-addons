# copyparty Add-on Documentation

## Overview

copyparty turns your Home Assistant device into a powerful file server accessible
from any web browser. It shares your HA `/share` and `/media` directories.

**Features provided by this add-on:**

- Resumable, multi-threaded drag-and-drop uploads
- File deduplication
- WebDAV support (mount as a network drive on Windows / macOS / Linux)
- FTP server (enable with `extra_args: "--ftp 3921"`)
- SFTP server (enable with `extra_args: "--sftp 3922"`)
- Music/media indexer with search
- Image, audio, and video thumbnails (FFmpeg + Pillow are pre-installed)
- File manager (cut/copy/paste/rename/delete)
- Media player for audio and video
- Markdown viewer and editor

## Configuration

### `username` *(optional)*

The username for the admin account. Leave blank to run without authentication
(anyone on your network can read and write files — not recommended!).

### `password` *(optional)*

The password for the admin account. Must be set together with `username`.

### `extra_args` *(optional)*

Extra command-line flags passed directly to copyparty. This lets you unlock any
feature not covered by the simple options above. Examples:

| Goal | Value |
|---|---|
| Enable FTP on port 3921 | `--ftp 3921` |
| Enable SFTP on port 3922 | `--sftp 3922` |
| Enable file indexing & search | `-e2dsa -e2ts` |
| Limit free disk space before uploads fail | `--df 4` (4 GiB minimum) |
| Announce on LAN (Windows Explorer / KDE) | `-z` |
| Log to a rotating file | `-lo /data/copyparty/cpp-%Y-%m%d.txt` |

See the full option reference at <https://copyparty.eu/cli/>.

## Advanced: using a config file

For complex setups (multiple volumes, multiple users, fine-grained permissions)
you can supply a full copyparty config file instead of using the options above.

1. Enable the **addon_config** map (already included).
2. Place a file named `copyparty.conf` in  
   `/addon_configs/<repo>_copyparty/` on your HA host  
   (accessible via the **Studio Code Server** or **SSH** add-ons, or from  
   **Settings → System → Storage → HA OS** if using HAOS).
3. Restart the add-on. It will automatically use the config file and ignore
   the `username`, `password`, and `extra_args` options.

See [copyparty config file docs](https://github.com/9001/copyparty/blob/hovudstraum/docs/example.conf)
for the full syntax.

## Directories

| Path (inside container) | Host path | Description |
|---|---|---|
| `/share` | HA `/share` | General shared storage; read-write |
| `/media` | HA `/media` | HA media directory; read-only by default |
| `/config` | `/addon_configs/<repo>_copyparty/` | Optional advanced config file |
| `/data/copyparty/` | Persistent add-on data | copyparty databases, thumbnails, transcodes |

## Accessing copyparty

Open `http://<your-ha-ip>:3923/` in a browser, or click **Open Web UI** in the
add-on panel.

### WebDAV

Connect from Windows Explorer: `\\<your-ha-ip>@3923\DavWWWRoot\`  
Connect from macOS Finder: `http://<your-ha-ip>:3923/`  
Connect from Linux: `davfs2` or `rclone`

## Security notes

- Always set a `username` and `password` if your HA instance is reachable from
  the internet or from untrusted networks.
- Use the `extra_args` field to add `--rproxy 1 --xff-hdr x-forwarded-for` if
  you front copyparty with a reverse proxy (e.g. nginx / Caddy).
- The add-on runs as an unprivileged container; no `full_access` or `privileged`
  capabilities are requested.
