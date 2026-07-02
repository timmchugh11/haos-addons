# Proxmox Proxy

Expose a local Proxmox web interface through Home Assistant ingress.

This is intended for devices or services that are available from the Home Assistant host on plain HTTP, for example:

```text
https://192.168.1.5:8006/
```

When the add-on is opened through Home Assistant, including over Nabu Casa cloud remote access, Home Assistant terminates the external HTTPS connection and forwards the request to this add-on internally. The add-on then makes a plain HTTP request to the local target.

## Options

| Option | Description |
| --- | --- |
| `target_url` | Local HTTP or HTTPS URL to proxy. |
| `preserve_host` | Send Home Assistant's incoming host header to the target instead of the target host. Usually leave this disabled. |
| `rewrite_absolute_paths` | Rewrite common absolute HTML/CSS paths so many simple apps work inside Home Assistant ingress. |
| `ssl_verify` | Verify the upstream HTTPS certificate. Disable this for self-signed local services such as Proxmox. |

## Notes

Proxmox assumes it is hosted at `/` and uses absolute API/static paths. This add-on rewrites common Proxmox paths so they are requested through the Home Assistant ingress URL.
