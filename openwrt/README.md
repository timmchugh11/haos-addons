# OpenWrt

Full system OpenWrt virtual router running inside a QEMU/KVM virtual machine.
Includes the LuCI web interface, WireGuard, Wi-Fi client/AP support, and mDNS.

Upstream: [https://github.com/AlbrechtL/openwrt-docker](https://github.com/AlbrechtL/openwrt-docker)

> **Note:** This add-on requires hardware with KVM support (`/dev/kvm`).
> It is only available for `amd64` and `aarch64` architectures.

---

## Quick start

1. Install the add-on.
2. Configure the **LAN** and **WAN** interface options (see below).
3. Start the add-on.
4. Open the **Web UI** (port **8006**) to access the OpenWrt TTY console.
5. If `forward_luci` is enabled, the LuCI web interface is available on port **9000** (HTTPS).

---

## Configuration

| Option | Default | Description |
|---|---|---|
| `wan_if` | `host` | WAN interface. `host` uses QEMU user-mode networking (NAT via host). Set to a physical interface name (e.g. `eth0`) to attach it directly to OpenWrt. |
| `lan_if` | `veth` | LAN interface. `veth` creates a virtual Ethernet pair between OpenWrt and the host at `172.31.1.1/24`. Set to a physical interface name to attach it directly. |
| `forward_luci` | `true` | Expose the OpenWrt LuCI web interface via the host on port **9000** (HTTPS). Requires `lan_if=veth`. |
| `cpu_count` | `1` | Number of virtual CPUs for the OpenWrt VM. |
| `ram_count` | `256` | RAM in MB allocated to the OpenWrt VM. Minimum is 256 MB. |
| `debug` | `false` | Enable debug logging (shows the QEMU command and OpenWrt boot log). |

### Interface modes

**`wan_if`**

- `host` *(default)* — QEMU user-mode networking. OpenWrt uses the host's internet connection via NAT. No physical NIC is dedicated to OpenWrt. Performance is lower due to software emulation.
- `none` — No WAN. Useful when OpenWrt WAN is provided via USB modem or Wi-Fi client.
- `<interface>` — A specific physical Ethernet interface (e.g. `enp2s0`) is passed through exclusively to OpenWrt.

**`lan_if`**

- `veth` *(default)* — Virtual Ethernet pair. The host gets IP `172.31.1.2/24`; OpenWrt LAN is at `172.31.1.1`. LuCI is accessible at `https://172.31.1.1` or via the forwarded port 9000.
- `veth,nofixedip` — Same as `veth` but does not auto-configure the host-side IP.
- `<interface>` — A specific physical Ethernet interface passed through exclusively to OpenWrt.

---

## Persistent storage

The OpenWrt disk image and settings are stored in the add-on's internal `/data/storage` directory and persist across restarts and updates.

---

## Ports

| Port | Description |
|---|---|
| `8006` | OpenWrt TTY console (web browser viewer) |
| `9000` | OpenWrt LuCI web interface — HTTPS (only active when `forward_luci=true` and `lan_if=veth`) |

---

## Requirements

- KVM-capable host (`/dev/kvm` must be available)
- `amd64` or `aarch64` architecture
- `NET_ADMIN` capability and privileged container mode (handled automatically by the add-on)
