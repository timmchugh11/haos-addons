# Nginx Proxy

Expose one HTTP web page from your local network through Home Assistant ingress.

This is intended for devices or services that are available from the Home Assistant host on plain HTTP, for example:

```text
http://192.168.1.100/
```

When the add-on is opened through Home Assistant, including over Nabu Casa cloud remote access, Home Assistant terminates the external HTTPS connection and forwards the request to this add-on internally. The add-on then makes a plain HTTP request to the local target.

## Options

| Option | Description |
| --- | --- |
| `target_url` | Local HTTP URL to proxy. Must start with `http://`. |
| `preserve_host` | Send Home Assistant's incoming host header to the target instead of the target host. Usually leave this disabled. |
| `rewrite_absolute_paths` | Rewrite common absolute HTML/CSS paths so many simple apps work inside Home Assistant ingress. |

## Notes

Some web applications assume they are hosted at `/` and may use JavaScript-generated absolute URLs. The path rewrite option covers common static HTML/CSS cases, but some applications may still need app-specific base URL settings.
