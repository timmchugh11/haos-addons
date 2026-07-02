# Nginx Proxy Documentation

Set `target_url` to the local HTTP endpoint you want to expose through Home Assistant ingress.

Example:

```yaml
target_url: http://192.168.1.100/
preserve_host: false
rewrite_absolute_paths: true
```

The first version supports a single target. A future multi-endpoint version can use path-based routing such as `/device-a/` and `/device-b/`, but that needs additional handling for applications that generate absolute links.
