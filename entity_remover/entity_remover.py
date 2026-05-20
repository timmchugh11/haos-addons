#!/usr/bin/env python3
"""Delete configured entities from Home Assistant on startup."""

from __future__ import annotations

import json
import logging
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOGGER = logging.getLogger("entity_remover")
BASE_URL = "http://supervisor/core/api"


def get_token() -> str | None:
    return os.getenv("SUPERVISOR_TOKEN") or os.getenv("HASSIO_TOKEN")


def load_options() -> dict:
    options_path = "/data/options.json"
    if os.path.exists(options_path):
        with open(options_path) as f:
            return json.load(f)
    return {}


def delete_entity(token: str, entity_id: str) -> None:
    """Delete an entity via state API and entity registry API."""
    _delete_via_api(token, f"{BASE_URL}/states/{entity_id}", entity_id, "state")
    _delete_via_api(token, f"{BASE_URL}/config/entity_registry/{entity_id}", entity_id, "registry")


def _delete_via_api(token: str, url: str, entity_id: str, label: str) -> None:
    request = Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
        method="DELETE",
    )
    try:
        with urlopen(request, timeout=10) as response:
            status = response.status
        LOGGER.info("Deleted %s from %s (HTTP %s)", entity_id, label, status)
    except HTTPError as err:
        if err.code == 404:
            LOGGER.info("Entity %s not found in %s (already gone)", entity_id, label)
        else:
            LOGGER.warning("Failed to delete %s from %s: HTTP %s", entity_id, label, err.code)
    except URLError as err:
        LOGGER.warning("Failed to delete %s from %s: %s", entity_id, label, err)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    token = get_token()
    if not token:
        LOGGER.error("No SUPERVISOR_TOKEN found — cannot call Home Assistant API")
        return

    options = load_options()
    entity_ids: list[str] = options.get("entity_ids", [])
    delay: int = int(options.get("delay_seconds", 10))

    if not entity_ids:
        LOGGER.info("No entity_ids configured, nothing to do")
        return

    LOGGER.info("Waiting %ds for other addons to register their entities...", delay)
    time.sleep(delay)

    for entity_id in entity_ids:
        entity_id = entity_id.strip()
        if not entity_id:
            continue
        LOGGER.info("Deleting entity: %s", entity_id)
        delete_entity(token, entity_id)

    LOGGER.info("Done. Deleted %d entity/entities.", len(entity_ids))


if __name__ == "__main__":
    main()
