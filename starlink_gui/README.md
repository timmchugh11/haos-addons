# Starlink GUI

Full router-style admin interface for your local Starlink dish and WiFi router,
accessible directly from Home Assistant via the sidebar.

Communicates with the dish over gRPC on your local network — no Starlink account
or internet access required.

## Features

- Live dish status (signal, obstruction, uptime, GPS, alerts)
- Real-time network throughput graphs
- WiFi router overview (clients, bands, channels)
- Embedded in HA via ingress — no extra port to open
- Optional direct access on port 3000

## Configuration

| Option | Default | Description |
|---|---|---|
| `dish_host` | `192.168.100.1` | IP address of the Starlink dish |
| `dish_port` | `9200` | gRPC port of the dish |
| `router_host` | `192.168.1.1` | IP address of the Starlink WiFi router |
| `router_port` | `9000` | gRPC port of the router |

The defaults work for a standard Starlink setup where the dish and router are on
the `192.168.100.x` / `192.168.1.x` subnets. Only change these if you have a
custom network configuration.

## Usage

After installing and starting the add-on, click **Open Web UI** or use the
**Starlink** item that appears in the HA sidebar.

Data is fetched live on each page load — there is nothing to persist.

## Network requirements

Home Assistant must be able to reach the dish and router IPs directly.
If you have a double-NAT setup (e.g. HA behind a separate router and Starlink is
in bypass mode), you may need to add a static route or place HA on the same subnet.
