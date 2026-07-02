# Proxmox Proxy Documentation

Set `target_url` to the local Proxmox endpoint you want to expose through Home Assistant ingress.

Example:

```yaml
target_url: https://192.168.1.5:8006/
preserve_host: false
rewrite_absolute_paths: true
ssl_verify: false
```

