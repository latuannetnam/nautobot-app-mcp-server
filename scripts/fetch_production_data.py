#!/usr/bin/env python3
"""Phase 1 of two-phase import: fetch production data and save to JSON.

Run from host (no Docker/Django required):
    python -u scripts/fetch_production_data.py  # -u for unbuffered output

Reads config from nautobot_import.env (same file as Phase 2).
Saves output to import_cache/*.json — gitignored.

Each JSON file contains a list of objects with resolved nested fields
(e.g. device_name instead of device UUID, namespace_name instead of namespace UUID)
so Phase 2 can import without additional API calls.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from time import time

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
CACHE_DIR = PROJECT_ROOT / "import_cache"
ENV_FILE = PROJECT_ROOT / "nautobot_import.env"


def _load_env():
    if not ENV_FILE.exists():
        sys.exit(
            f"nautobot_import.env not found at {ENV_FILE}. "
            "Copy nautobot_import.env.example to nautobot_import.env and fill in values."
        )
    load_dotenv(ENV_FILE)


# ---------------------------------------------------------------------------
# REST helpers
# ---------------------------------------------------------------------------

def prod_get(path: str, params: dict | None = None) -> requests.Response:
    url = f"{PROD_URL}/api{path}"
    for attempt in range(3):
        try:
            resp = requests.get(
                url,
                params=params,
                headers={"Authorization": f"Token {PROD_TOKEN}"},
                timeout=(10, 300),  # (connect, read) — read timeout allows large payloads
            )
            resp.raise_for_status()
            return resp
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as exc:
            if attempt < 2:
                import time as _time
                wait = 2 ** attempt * 10
                print(f"  [!] {exc!s} — retrying in {wait}s (attempt {attempt + 1}/3)...", flush=True)
                _time.sleep(wait)
            else:
                raise


def fetch_all(path: str) -> list[dict]:
    """Paginate through all results, return flat list."""
    params: dict[str, int] = {"limit": 100}
    all_items: list[dict] = []
    total_count = 0
    while True:
        resp = prod_get(path, params)
        data = resp.json()
        if total_count == 0:
            total_count = data.get("count", 0)
        all_items.extend(data["results"])
        print(f"    {len(all_items)}/{total_count} via {path}")
        if data.get("next") is None:
            break
        params["offset"] = len(all_items)
    return all_items


def fetch_nested_object(obj: dict | None) -> dict | None:
    """Fetch full object from API if URL is present."""
    if not obj or not isinstance(obj, dict):
        return None
    url = obj.get("url")
    if not url:
        return obj
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Token {PROD_TOKEN}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:  # noqa: BLE001
        return obj


def log(msg: str):
    elapsed = time() - _t0
    print(f"  [{elapsed:.1f}s] {msg}")


# ---------------------------------------------------------------------------
# Normalize helpers — convert nested API objects to flat name/id refs
# ---------------------------------------------------------------------------

def _ns(obj: dict | None, key: str) -> str | None:
    """Return .get('name') from a nested object (or None)."""
    v = obj.get(key) if isinstance(obj, dict) else None
    return (v.get("name") if isinstance(v, dict) else None) if v else None


def _nid(obj: dict | None, key: str) -> str | None:
    """Return .get('id') from a nested object (or None)."""
    v = obj.get(key) if isinstance(obj, dict) else None
    return (v.get("id") if isinstance(v, dict) else None) if v else None


def _nv(obj: dict | None, key: str) -> str | None:
    """Return .get('value') from a nested choice dict like {'value': '...', 'label': '...'}."""
    v = obj.get(key) if isinstance(obj, dict) else None
    return (v.get("value") if isinstance(v, dict) else None) if v else None


def _flatten_status(obj: dict | None) -> str | None:
    """Get status name from nested status dict."""
    return _ns(obj, "status")


def _flatten_role(obj: dict | None) -> str | None:
    return _ns(obj, "role")


def _flatten_namespace(obj: dict | None) -> str | None:
    return _ns(obj, "namespace")


# ---------------------------------------------------------------------------
# Per-model fetchers — normalize to Phase-2-friendly flat shape
# ---------------------------------------------------------------------------

def fetch_statuses() -> list[dict]:
    items = fetch_all("/extras/statuses/")
    return [{"name": i.get("name")} for i in items if i.get("name")]


def fetch_roles() -> list[dict]:
    items = fetch_all("/extras/roles/")
    return [{"name": i.get("name")} for i in items if i.get("name")]


def fetch_device_types() -> list[dict]:
    items = fetch_all("/dcim/device-types/")
    out = []
    for i in items:
        mfr_obj = i.get("manufacturer")
        mfr_name = (mfr_obj.get("name") if isinstance(mfr_obj, dict) else None) or "Unknown"
        out.append({
            "model": i.get("model"),
            "manufacturer_name": mfr_name,
        })
    return out


def fetch_platforms() -> list[dict]:
    items = fetch_all("/dcim/platforms/")
    return [{"name": i.get("name")} for i in items if i.get("name")]


def fetch_namespaces() -> list[dict]:
    items = fetch_all("/ipam/namespaces/")
    return [{"name": i.get("name"), "description": i.get("description") or ""} for i in items if i.get("name")]


def fetch_locations() -> list[dict]:
    """location_type and parent are nested objects with 'name' in the list response."""
    items = fetch_all("/dcim/locations/")
    out = []
    for i in items:
        lt_obj = i.get("location_type")
        parent_obj = i.get("parent")
        lt_name = (lt_obj.get("name") if isinstance(lt_obj, dict) else None) or ""
        parent_name = (parent_obj.get("name") if isinstance(parent_obj, dict) else None) or ""
        out.append({
            "id": i.get("id"),
            "name": i.get("name"),
            "location_type_name": lt_name,
            "parent_name": parent_name,
            "status_name": _flatten_status(i) or "Active",
        })
    return out


def fetch_devices() -> list[dict]:
    if DEVICE_NAMES:
        print(f"  Filtering by device names: {DEVICE_NAMES}")
        all_items: list[dict] = []
        for name in DEVICE_NAMES:
            resp = prod_get("/dcim/devices/", {"name": name, "limit": 1})
            results = resp.json()["results"]
            if results:
                all_items.append(results[0])
            else:
                print(f"    NOT FOUND: {name}")
        return all_items
    return fetch_all("/dcim/devices/")


def normalize_device(dev: dict) -> dict:
    """Flatten a device dict to Phase-2-friendly shape.

    The device list endpoint returns abbreviated nested objects (id/url only).
    Fetch all four FK objects by URL to get their names.
    """
    # device_type → model + manufacturer
    dt_obj = dev.get("device_type")
    dt_full = fetch_nested_object(dt_obj) if dt_obj else None
    dt_model = (dt_full.get("model") if dt_full else None) or ""
    mfr_full = fetch_nested_object((dt_full or {}).get("manufacturer")) if dt_full else None
    mfr_name = (mfr_full.get("name") if mfr_full else None) or "Unknown"

    # location → name
    loc_obj = dev.get("location")
    loc_full = fetch_nested_object(loc_obj) if loc_obj else None
    location_name = (loc_full.get("name") if loc_full else None) or ""

    # role → name
    role_obj = dev.get("role")
    role_full = fetch_nested_object(role_obj) if role_obj else None
    role_name = (role_full.get("name") if role_full else None) or ""

    # platform → name
    platform_obj = dev.get("platform")
    platform_full = fetch_nested_object(platform_obj) if platform_obj else None
    platform_name = (platform_full.get("name") if platform_full else None) or ""

    return {
        "id": dev.get("id"),
        "name": dev.get("name"),
        "device_type_model": dt_model,
        "manufacturer_name": mfr_name,
        "location_name": location_name,
        "platform_name": platform_name,
        "role_name": role_name,
        "status_name": _flatten_status(dev) or "Active",
        "serial": dev.get("serial") or "",
    }


def fetch_interfaces(device_ids: list[str]) -> list[dict]:
    """Fetch all interfaces for given device UUIDs."""
    all_ifaces: list[dict] = []
    for dev_id in device_ids:
        ifaces = fetch_all(f"/dcim/interfaces/?device_id={dev_id}")
        for i in ifaces:
            all_ifaces.append({
                "device_name": None,  # resolved below
                "device_id": dev_id,
                "name": i.get("name"),
                "status_name": _flatten_status(i) or "Active",
                "enabled": i.get("enabled", True),
                "type": _nv(i, "type") or "other",
                "mtu": i.get("mtu"),
                "mac_address": i.get("mac_address") or "",
                "description": i.get("description") or "",
                "ip_addresses": [addr.get("address") for addr in (i.get("ip_addresses") or []) if addr.get("address")],
            })
    return all_ifaces


def fetch_ip_addresses() -> list[dict]:
    items = fetch_all("/ipam/ip-addresses/")
    out = []
    for i in items:
        ns_obj = i.get("namespace")
        ns_name = (ns_obj.get("name") if isinstance(ns_obj, dict) else None) or "Global"
        out.append({
            "address": i.get("address"),
            "namespace_name": ns_name,
            "status_name": _flatten_status(i) or "Active",
            "dns_name": i.get("dns_name") or "",
            "description": i.get("description") or "",
        })
    return out


def fetch_prefixes() -> list[dict]:
    """Namespace is a nested object with 'name' already present in the list response."""
    items = fetch_all("/ipam/prefixes/")
    out = []
    for i in items:
        ns_obj = i.get("namespace")
        ns_name = (ns_obj.get("name") if isinstance(ns_obj, dict) else None) or "Global"
        out.append({
            "prefix": i.get("prefix"),
            "namespace_name": ns_name,
            "status_name": _flatten_status(i) or "Active",
            "description": i.get("description") or "",
        })
    return out


def fetch_vlans() -> list[dict]:
    """Namespace is a nested object with 'name' already present in the list response."""
    items = fetch_all("/ipam/vlans/")
    out = []
    for i in items:
        ns_obj = i.get("namespace")
        ns_name = (ns_obj.get("name") if isinstance(ns_obj, dict) else None) or "Global"
        out.append({
            "name": i.get("name"),
            "vid": i.get("vid"),
            "namespace_name": ns_name,
            "status_name": _flatten_status(i) or "Active",
            "description": i.get("description") or "",
        })
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global PROD_URL, PROD_TOKEN, DEVICE_NAMES, _t0
    _t0 = time()

    _load_env()
    PROD_URL = os.environ.get("NAUTOBOT_PROD_URL", "").rstrip("/")
    PROD_TOKEN = os.environ.get("NAUTOBOT_PROD_TOKEN", "")
    DEVICE_NAMES = [d.strip() for d in os.environ.get("DEVICE_NAMES", "").split(",") if d.strip()]

    if not PROD_URL or not PROD_TOKEN:
        sys.exit("NAUTOBOT_PROD_URL and NAUTOBOT_PROD_TOKEN must be set in nautobot_import.env")

    CACHE_DIR.mkdir(exist_ok=True)
    print(f"[FETCH] Production: {PROD_URL}")
    print(f"[FETCH] Output: {CACHE_DIR}")

    manifest: dict = {
        "fetched_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "prod_url": PROD_URL,
        "device_filter": DEVICE_NAMES or "ALL",
        "files": {},
    }

    def save(name: str, data: list[dict]):
        path = CACHE_DIR / f"{name}.json"
        path.write_text(json.dumps(data, indent=2, default=str))
        manifest["files"][name] = {"count": len(data), "path": str(path.name)}
        print(f"  Saved {name}: {len(data)} records", flush=True)

    def save_if_absent(name: str, data_fn) -> bool:
        """Save only if file not yet present (resume support for large datasets)."""
        path = CACHE_DIR / f"{name}.json"
        if path.exists():
            existing = json.loads(path.read_text())
            manifest["files"][name] = {"count": len(existing), "path": str(path.name), "resumed": True}
            print(f"  {name}: already exists ({len(existing)} records, skipping)", flush=True)
            return False
        data = data_fn()
        path.write_text(json.dumps(data, indent=2, default=str))
        manifest["files"][name] = {"count": len(data), "path": str(path.name)}
        print(f"  Saved {name}: {len(data)} records", flush=True)
        return True

    # --- Pre-import: Statuses, Roles, DeviceTypes, Platforms, Namespaces ---
    print("\n[1/6] Fetching lookup tables...", flush=True)
    save("statuses", fetch_statuses())
    save("roles", fetch_roles())
    save("device_types", fetch_device_types())
    save("platforms", fetch_platforms())
    save("namespaces", fetch_namespaces())

    # --- Locations ---
    print("\n[2/6] Fetching locations...", flush=True)
    locations = fetch_locations()
    save("locations", locations)

    # --- Devices ---
    print("\n[3/6] Fetching devices...", flush=True)
    raw_devices = fetch_devices()
    devices = [normalize_device(d) for d in raw_devices]
    save("devices", devices)
    device_ids = [d["id"] for d in devices if d.get("id")]

    # Build device name→id and id→name maps for interface normalization
    dev_name_map = {d["name"]: d["id"] for d in devices}
    dev_id_map: dict[str, str] = {}
    if device_ids:
        for d in raw_devices:
            dev_id_map[d["id"]] = d["name"]

    # --- Interfaces (for imported devices only) ---
    # Use save_if_absent so we can resume after timeout
    print(f"\n[4/6] Fetching interfaces for {len(device_ids)} devices...", flush=True)

    def _fetch_all_interfaces():
        raw = fetch_interfaces(device_ids)
        for iface in raw:
            iface["device_name"] = dev_id_map.get(iface.pop("device_id")) or ""
            iface.pop("ip_addresses", None)
        return raw

    save_if_absent("interfaces", _fetch_all_interfaces)

    # --- IPAM ---
    print("\n[5/6] Fetching IP addresses...", flush=True)
    save_if_absent("ip_addresses", fetch_ip_addresses)

    print("\n[6/6] Fetching prefixes...", flush=True)
    save_if_absent("prefixes", fetch_prefixes)

    print("\n    Fetching VLANs...", flush=True)
    save_if_absent("vlans", fetch_vlans)

    # Write manifest last
    manifest_path = CACHE_DIR / "_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\n[DONE] All data saved to {CACHE_DIR}")
    print(f"       Manifest: {manifest_path}")

    # Summary
    total = sum(f["count"] for f in manifest["files"].values())
    print(f"       Total records: {total:,}")
    print(f"\nNext: Run Phase 2 — docker exec nautobot-app-mcp-server-nautobot-1 nautobot-server import_production_data")


if __name__ == "__main__":
    main()
