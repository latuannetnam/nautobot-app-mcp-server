"""Django management command: import_production_data (Phase 2 of two-phase import).

Phase 2 loads pre-fetched JSON from import_cache/ and bulk-inserts into the
dev DB. All lookups are resolved by name — no additional API calls needed.

Usage (run inside the Nautobot container):
    poetry run nautobot-server import_production_data [--dry-run]

Phase 1 (fetch) must be run first from the host:
    python scripts/fetch_production_data.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from time import time

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Phase 2: Bulk-import pre-fetched production JSON into dev DB"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview what would be imported without writing to the database",
        )
        parser.add_argument(
            "--cache-dir",
            type=str,
            default=None,
            help="Path to import_cache directory (default: <project_root>/import_cache)",
        )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _cache_path(self, cache_dir: Path, name: str) -> Path:
        return cache_dir / f"{name}.json"

    def _load(self, cache_dir: Path, name: str) -> list[dict]:
        path = self._cache_path(cache_dir, name)
        if not path.exists():
            self.stderr.write(self.style.ERROR(f"Cache file not found: {path}. Run Phase 1 first: python scripts/fetch_production_data.py"))
            sys.exit(1)
        return json.loads(path.read_text())

    def _bulk_insert(self, model_objects: list, batch_size: int = 500, label: str = ""):
        """Bulk-insert in batches, report progress."""
        total = 0
        for i in range(0, len(model_objects), batch_size):
            batch = model_objects[i:i + batch_size]
            self.stdout.write(f"    {label} batch {i // batch_size + 1}: {len(batch)} records")
        return len(model_objects)

    # -------------------------------------------------------------------------
    # handle
    # -------------------------------------------------------------------------

    def handle(self, *args, **options):
        dry_run = options["dry_run"] or os.environ.get("DRY_RUN", "false").lower() in ("true", "1", "yes")

        # Cache dir: CLI arg > NAUTOBOT_IMPORT_CACHE_DIR env > project_root/import_cache
        cache_dir_str = options.get("cache_dir") or os.environ.get("NAUTOBOT_IMPORT_CACHE_DIR")
        if cache_dir_str:
            cache_dir = Path(cache_dir_str).resolve()
        else:
            env_file = os.environ.get("NAUTOBOT_CONFIG", "")
            project_root = Path(env_file).parent.parent.parent if env_file else Path(__file__).resolve().parents[4]
            cache_dir = project_root / "import_cache"

        if not cache_dir.exists():
            self.stderr.write(
                self.style.ERROR(
                    f"Cache directory not found: {cache_dir}. "
                    "Run Phase 1 first: python scripts/fetch_production_data.py"
                )
            )
            sys.exit(1)

        manifest_path = cache_dir / "_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            self.stdout.write(self.style.HTTP_INFO(f"Loaded manifest from {manifest_path}"))
            self.stdout.write(f"  Fetched at: {manifest.get('fetched_at')}")
            self.stdout.write(f"  Prod URL:    {manifest.get('prod_url')}")
            self.stdout.write(f"  Device filter: {manifest.get('device_filter')}")

        t0 = time()

        # -------------------------------------------------------------------------
        # Lazy model imports (Django must be bootstrapped first)
        # -------------------------------------------------------------------------
        from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer, Platform
        from nautobot.extras.models import Role, Status
        from nautobot.ipam.models import IPAddress, Namespace, Prefix, VLAN

        # -------------------------------------------------------------------------
        # Build name→object maps from existing dev DB
        # -------------------------------------------------------------------------
        self.stdout.write(self.style.HTTP_INFO("[SETUP] Building name→object maps from dev DB..."))

        status_map: dict[str, Status] = {s.name: s for s in Status.objects.all()}
        role_map: dict[str, Role] = {r.name: r for r in Role.objects.all()}
        mfr_map: dict[str, Manufacturer] = {m.name: m for m in Manufacturer.objects.all()}
        devtype_map: dict[str, DeviceType] = {dt.display: dt for dt in DeviceType.objects.all()}
        platform_map: dict[str, Platform] = {p.name: p for p in Platform.objects.all()}
        ns_map: dict[str, Namespace] = {ns.name: ns for ns in Namespace.objects.all()}
        location_map: dict[str, Location] = {}
        lt_map: dict[str, LocationType] = {lt.name: lt for lt in LocationType.objects.all()}

        log = lambda msg: self.stdout.write(f"  [{time() - t0:.1f}s] {msg}")

        # -------------------------------------------------------------------------
        # 0. Load JSON cache
        # -------------------------------------------------------------------------
        self.stdout.write(self.style.HTTP_INFO("\n[0/5] Loading JSON cache..."))

        cache_statuses = self._load(cache_dir, "statuses")
        cache_roles = self._load(cache_dir, "roles")
        cache_device_types = self._load(cache_dir, "device_types")
        cache_platforms = self._load(cache_dir, "platforms")
        cache_namespaces = self._load(cache_dir, "namespaces")
        cache_locations = self._load(cache_dir, "locations")
        cache_devices = self._load(cache_dir, "devices")
        cache_interfaces = self._load(cache_dir, "interfaces")
        cache_ip_addresses = self._load(cache_dir, "ip_addresses")
        cache_prefixes = self._load(cache_dir, "prefixes")
        cache_vlans = self._load(cache_dir, "vlans")

        self.stdout.write(f"  statuses:       {len(cache_statuses)}")
        self.stdout.write(f"  roles:          {len(cache_roles)}")
        self.stdout.write(f"  device_types:   {len(cache_device_types)}")
        self.stdout.write(f"  platforms:      {len(cache_platforms)}")
        self.stdout.write(f"  namespaces:     {len(cache_namespaces)}")
        self.stdout.write(f"  locations:      {len(cache_locations)}")
        self.stdout.write(f"  devices:        {len(cache_devices)}")
        self.stdout.write(f"  interfaces:     {len(cache_interfaces)}")
        self.stdout.write(f"  ip_addresses:   {len(cache_ip_addresses)}")
        self.stdout.write(f"  prefixes:       {len(cache_prefixes)}")
        self.stdout.write(f"  vlans:          {len(cache_vlans)}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\n[DRY RUN] Nothing will be written."))
            sys.exit(0)

        # -------------------------------------------------------------------------
        # 0b. Pre-create lookup entities (Statuses, Roles, Platforms already in DB)
        # -------------------------------------------------------------------------
        self.stdout.write(self.style.HTTP_INFO("[SETUP] Pre-creating lookup entities from cache..."))

        # Statuses
        new_statuses = 0
        for s in cache_statuses:
            if s["name"] and s["name"] not in status_map:
                Status.objects.get_or_create(name=s["name"])
                status_map[s["name"]] = Status.objects.get(name=s["name"])
                new_statuses += 1
        log(f"Statuses: {len(status_map)} total, {new_statuses} created from cache")

        # Roles
        new_roles = 0
        for r in cache_roles:
            if r["name"] and r["name"] not in role_map:
                Role.objects.get_or_create(name=r["name"])
                role_map[r["name"]] = Role.objects.get(name=r["name"])
                new_roles += 1
        log(f"Roles: {len(role_map)} total, {new_roles} created from cache")

        # Manufacturers → DeviceTypes
        new_mfrs = 0
        for dt in cache_device_types:
            mfr_name = dt.get("manufacturer_name", "Unknown")
            if mfr_name and mfr_name not in mfr_map:
                Manufacturer.objects.get_or_create(name=mfr_name)
                mfr_map[mfr_name] = Manufacturer.objects.get(name=mfr_name)
                new_mfrs += 1
        log(f"Manufacturers: {len(mfr_map)} total, {new_mfrs} created")

        new_devtypes = 0
        for dt in cache_device_types:
            dt_model = dt.get("model", "")
            mfr_name = dt.get("manufacturer_name", "Unknown")
            mfr = mfr_map.get(mfr_name)
            if dt_model and dt_model not in devtype_map:
                DeviceType.objects.get_or_create(model=dt_model, defaults={"manufacturer": mfr})
                devtype_map[dt_model] = DeviceType.objects.get(model=dt_model)
                new_devtypes += 1
        log(f"DeviceTypes: {len(devtype_map)} total, {new_devtypes} created")

        # Platforms
        new_platforms = 0
        for p in cache_platforms:
            if p["name"] and p["name"] not in platform_map:
                Platform.objects.get_or_create(name=p["name"])
                platform_map[p["name"]] = Platform.objects.get(name=p["name"])
                new_platforms += 1
        log(f"Platforms: {len(platform_map)} total, {new_platforms} created")

        # Namespaces
        new_ns = 0
        for ns_data in cache_namespaces:
            ns_name = ns_data.get("name", "")
            if ns_name and ns_name not in ns_map:
                Namespace.objects.get_or_create(name=ns_name)
                ns_map[ns_name] = Namespace.objects.get(name=ns_name)
                new_ns += 1
        log(f"Namespaces: {len(ns_map)} total, {new_ns} created")

        # -------------------------------------------------------------------------
        # 1. Import locations
        # -------------------------------------------------------------------------
        self.stdout.write(self.style.HTTP_INFO("\n[1/5] Importing locations..."))

        # Some locations may have no location_type — fall back to first available LT
        default_lt = next((lt for lt in lt_map.values()), None)

        location_objs = []
        for loc_data in cache_locations:
            lt_name = loc_data.get("location_type_name", "")
            lt = lt_map.get(lt_name) if lt_name else default_lt
            status = status_map.get(loc_data.get("status_name", "Active"))
            location_objs.append(
                Location(
                    name=loc_data["name"],
                    status=status,
                    location_type=lt,
                    # parent resolved below
                )
            )
        Location.objects.bulk_create(location_objs, ignore_conflicts=True)
        # Re-read to build name→obj map
        location_map = {loc.name: loc for loc in Location.objects.all()}
        # Set parents
        parent_updates: list[Location] = []
        for loc_data in cache_locations:
            parent_name = loc_data.get("parent_name", "")
            if parent_name and parent_name in location_map:
                loc = location_map[loc_data["name"]]
                loc.parent = location_map[parent_name]
                parent_updates.append(loc)
        if parent_updates:
            Location.objects.bulk_update(parent_updates, ["parent"], batch_size=500)
        log(f"Locations: {len(location_map)} total in DB")

        # -------------------------------------------------------------------------
        # 2. Import devices
        # -------------------------------------------------------------------------
        self.stdout.write(self.style.HTTP_INFO("[2/5] Importing devices..."))

        dev_objs = []
        for dev_data in cache_devices:
            status = status_map.get(dev_data.get("status_name", "Active"))
            location = location_map.get(dev_data.get("location_name", ""))
            dt = devtype_map.get(dev_data.get("device_type_model", ""))
            platform = platform_map.get(dev_data.get("platform_name", ""))
            role = role_map.get(dev_data.get("role_name", ""))
            dev_objs.append(
                Device(
                    name=dev_data["name"],
                    status=status,
                    location=location,
                    device_type=dt,
                    platform=platform,
                    role=role,
                    serial=dev_data.get("serial", ""),
                )
            )
        Device.objects.bulk_create(dev_objs, ignore_conflicts=True)
        device_map = {d.name: d for d in Device.objects.all()}
        log(f"Devices: {len(device_map)} total in DB")

        # -------------------------------------------------------------------------
        # 3. Import interfaces
        # -------------------------------------------------------------------------
        self.stdout.write(self.style.HTTP_INFO("[3/5] Importing interfaces..."))

        iface_objs = []
        for iface_data in cache_interfaces:
            dev = device_map.get(iface_data.get("device_name", ""))
            if not dev:
                continue
            status = status_map.get(iface_data.get("status_name", "Active"))
            iface_objs.append(
                Interface(
                    device=dev,
                    name=iface_data["name"],
                    status=status,
                    enabled=iface_data.get("enabled", True),
                    type=iface_data.get("type", "other"),
                    mtu=iface_data.get("mtu"),
                    mac_address=iface_data.get("mac_address") or "",
                    description=iface_data.get("description") or "",
                )
            )
        Interface.objects.bulk_create(iface_objs, ignore_conflicts=True)
        total_ifaces = Interface.objects.count()
        log(f"Interfaces: {total_ifaces} total in DB")

        # -------------------------------------------------------------------------
        # 4. Import IPAM data
        # -------------------------------------------------------------------------
        self.stdout.write(self.style.HTTP_INFO("[4/5] Importing IPAM data..."))

        # Prefixes: bulk_create first (IPs need parent prefixes)
        prefix_objs = []
        for pf_data in cache_prefixes:
            status = status_map.get(pf_data.get("status_name", "Active"))
            namespace = ns_map.get(pf_data.get("namespace_name", "Global"))
            prefix_objs.append(
                Prefix(
                    prefix=pf_data["prefix"],
                    status=status,
                    namespace=namespace,
                    description=pf_data.get("description") or "",
                )
            )
        total_prefix_batches = 0
        for i in range(0, len(prefix_objs), 500):
            batch = prefix_objs[i:i + 500]
            Prefix.objects.bulk_create(batch, ignore_conflicts=True)
            total_prefix_batches += 1
            self.stdout.write(f"    Prefixes: batch {total_prefix_batches} ({len(batch)} records)")
        log(f"Prefixes: {Prefix.objects.count()} total in DB")

        # IP Addresses: get_or_create (parent-lookup constraint unavoidable)
        ips_imported = 0
        for ip_data in cache_ip_addresses:
            status = status_map.get(ip_data.get("status_name", "Active"))
            try:
                IPAddress.objects.get_or_create(
                    address=ip_data["address"],
                    defaults={
                        "status": status,
                        "dns_name": ip_data.get("dns_name") or "",
                        "description": ip_data.get("description") or "",
                    },
                )
                ips_imported += 1
            except Exception:  # noqa: BLE001
                pass  # Skip IPs whose parent prefix wasn't imported
            if ips_imported % 500 == 0 and ips_imported > 0:
                self.stdout.write(f"    IP Addresses: {ips_imported}/{len(cache_ip_addresses)}")
        log(f"IP Addresses: {ips_imported} imported, {IPAddress.objects.count()} total in DB")

        # VLANs: bulk_create (no namespace FK in this Nautobot version)
        vlan_objs = []
        for vlan_data in cache_vlans:
            status = status_map.get(vlan_data.get("status_name", "Active"))
            vlan_objs.append(
                VLAN(
                    name=vlan_data["name"],
                    vid=vlan_data.get("vid"),
                    status=status,
                    description=vlan_data.get("description") or "",
                )
            )
        VLAN.objects.bulk_create(vlan_objs, ignore_conflicts=True)
        log(f"VLANs: {VLAN.objects.count()} total in DB")

        # -------------------------------------------------------------------------
        # 5. Verify
        # -------------------------------------------------------------------------
        self.stdout.write(self.style.HTTP_INFO("\n[5/5] Verification:"))
        self.stdout.write(f"  Locations:    {Location.objects.count()}")
        self.stdout.write(f"  Devices:     {Device.objects.count()}")
        self.stdout.write(f"  Interfaces:  {Interface.objects.count()}")
        self.stdout.write(f"  IPAddresses: {IPAddress.objects.count()}")
        self.stdout.write(f"  Prefixes:   {Prefix.objects.count()}")
        self.stdout.write(f"  VLANs:      {VLAN.objects.count()}")

        elapsed = time() - t0
        self.stdout.write(self.style.SUCCESS(f"\nDone in {elapsed:.1f}s"))
        self.stdout.write("Run UAT: docker exec nautobot-app-mcp-server-nautobot-1 python /source/scripts/run_mcp_uat.py")
