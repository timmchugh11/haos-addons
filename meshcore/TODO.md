# MeshCore GUI Roadmap

This file tracks what is still needed to make the custom Home Assistant add-on
feel like a full MeshCore companion application rather than a read-only
dashboard.

## Current State

- [x] Standalone custom web UI served at `/`
- [x] Home Assistant ingress support
- [x] Serial and BLE connection options
- [x] Read-only dashboard
- [x] Channel/direct message history and composer
- [x] Read-only nodes/contacts table
- [x] Read-only channels table
- [x] Leaflet map view for contacts with advertised coordinates
- [x] Basic REST API under `/api/v1/*`

## Priority 1 - Core Companion Experience

- [x] Send public channel messages
- [x] Send private channel messages where keys/passwords are configured
- [x] Send direct messages to contacts
- [x] Receive and display direct messages separately from public traffic
- [x] Conversation view grouped by channel/contact
- [x] Message composer with channel/contact selector
- [x] Message delivery state: sent, failed, ACK timed out
- [x] Message queue state before radio handoff
- [x] Multi-ACK display when supported by firmware
- [x] Message retry/resend controls
- [x] Local persistent message archive under `/data/.meshcore`
- [x] Message search, filters, and pagination
- [x] Export messages as JSON/CSV
- [x] Notification hooks for new direct messages and selected channels

## Priority 2 - Contacts, Nodes, and Identity

- [x] Add, edit, and remove contacts
- [x] Manual add-contact flow by public key
- [x] Contact discovery/advert handling
- [x] Contact aliases and notes stored locally
- [x] Contact trust/verification indicators
- [x] Node type display for companion, repeater, room server, sensor, and unknown
- [x] Device identity page: name, public key, role, and firmware/device info
- [ ] Owner info editor/display
- [x] Device battery, storage, radio parameters, and telemetry status
- [ ] Admin-safe private key backup/export flow
- [ ] Admin-safe identity restore/import flow

## Priority 3 - Accurate Map and Location

- [ ] Normalize all position sources: self info, contact adverts, GPS fields, telemetry
- [ ] Distinguish stale coordinates from live/recent coordinates
- [ ] Show marker age and last-seen timestamp
- [ ] Marker icons by node role/type
- [ ] Marker clustering for dense networks
- [ ] Optional heatmap layer
- [ ] Fit-to-live-nodes and fit-to-all-known-nodes controls
- [ ] Click marker to open node/contact details
- [ ] Show own node position and advertised location policy
- [ ] Set own node latitude/longitude when supported
- [ ] GPS status panel when GPS support is compiled into firmware
- [ ] Offline tile/cache strategy or documented internet requirement
- [ ] Coordinate validation to prevent `0,0` and malformed advert markers

## Priority 4 - Channels and Room Servers

- [ ] Full channel management UI
- [ ] Create/update channel names
- [ ] Configure private channel passwords/keys securely
- [ ] Channel backup and restore
- [ ] Per-channel mute/pin/sort settings
- [ ] Room server discovery and connection flow
- [ ] Room/BBS message list with history sync
- [ ] Create room posts
- [ ] Reply/delete/moderate room posts where permissions allow
- [ ] Room server read-only/admin permission display
- [ ] Room server ACL management where supported

## Priority 5 - Radio, Routing, and Admin

- [ ] Radio parameter viewer: frequency, bandwidth, spreading factor, coding rate, TX power
- [ ] Safe radio parameter editor with validation and confirmation
- [ ] Repeater/admin login flow for managed nodes
- [ ] Reboot and clock sync commands
- [ ] Flood advert and zero-hop advert commands
- [ ] Routing flags: repeat, loop detection, advert path hash size
- [ ] Retransmit delay factors for flood/direct traffic
- [ ] Duty cycle and airtime factor display/config
- [ ] Multi-ACK enable/disable where supported
- [ ] Flood hop limit config
- [ ] Region management: list, allow/block, home/default region, save
- [ ] ACL viewer/editor for repeaters and room servers
- [ ] Bridge status/config where firmware supports bridge features

## Priority 6 - Sensors, Telemetry, and Diagnostics

- [ ] Sensor list and values when sensor support is compiled in
- [ ] Telemetry history charts
- [ ] Battery calibration/admin controls where supported
- [ ] Packet/event log viewer
- [ ] Raw protocol event inspector for debugging
- [ ] Connection health panel with reconnect attempts and last error
- [ ] BLE pairing/status diagnostics
- [ ] Serial port scanner and connection test endpoint
- [ ] Simulator coverage for messages, contacts, channels, and map coordinates

## Priority 7 - API and Home Assistant Integration

- [x] Write-capable API endpoints for messages
- [ ] Write-capable API endpoints for contacts, channels, and device config
- [ ] API auth/rate limiting appropriate for Home Assistant ingress/direct access
- [ ] Home Assistant sensors for connection, node count, message count, battery, GPS
- [ ] Home Assistant services for sending messages and triggering adverts
- [ ] WebSocket or Server-Sent Events for live UI updates instead of polling
- [ ] Stable OpenAPI schema for external automations
- [ ] Backup/restore support for local add-on data

## Priority 8 - UI Polish and Reliability

- [ ] Responsive mobile layout pass
- [ ] Loading, empty, stale, and disconnected states for every panel
- [ ] Toasts/dialogs for command results and errors
- [ ] Confirm dialogs for destructive/admin actions
- [ ] Keyboard-friendly message composer
- [ ] Accessibility pass: focus styles, labels, contrast, table semantics
- [ ] Dark Starlink-style visual consistency pass across all pages
- [ ] Browser cache-busting for deployed `custom-ui` assets
- [ ] Automated frontend smoke test for dashboard and map rendering

## Protocol/Feature References

- MeshCore Companion Protocol v1.12.0+ covers BLE communication, packets, commands,
  contacts, channels, messages, device info, telemetry, and self info.
- MeshCore CLI command documentation covers repeater, room server, sensor, routing,
  ACL, region, GPS, bridge, and admin operations.
- MeshCore FAQ describes room servers as stored-history message servers, unlike
  live-only channel messages.
