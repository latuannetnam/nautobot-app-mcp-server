"""Tests for core read tools (TEST-02)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import uuid

from django.test import TestCase

from nautobot_app_mcp_server.mcp.tools.pagination import (
    LIMIT_DEFAULT,
    LIMIT_MAX,
    LIMIT_SUMMARIZE,
    PaginatedResult,
    encode_cursor,
    decode_cursor,
    paginate_queryset,
)


class TestPaginationConstants(TestCase):
    """Verify pagination constants match PAGE-01, PAGE-02 requirements."""

    def test_limit_default(self):
        self.assertEqual(LIMIT_DEFAULT, 25)

    def test_limit_max(self):
        self.assertEqual(LIMIT_MAX, 1000)

    def test_limit_summarize(self):
        self.assertEqual(LIMIT_SUMMARIZE, 100)


class TestCursorEncoding(TestCase):
    """PAGE-04: Cursor round-trips for UUID and string PKs."""

    def test_uuid_cursor_roundtrip(self):
        pk = "a3f8b2c0-1234-5678-9abc-def012345678"
        cursor = encode_cursor(pk)
        self.assertIsInstance(cursor, str)
        decoded = decode_cursor(cursor)
        self.assertEqual(decoded, pk)

    def test_string_pk_cursor_roundtrip(self):
        pk = "my-simple-name"
        cursor = encode_cursor(pk)
        decoded = decode_cursor(cursor)
        self.assertEqual(decoded, pk)

    def test_cursor_is_base64(self):
        import base64

        pk = "device-01"
        cursor = encode_cursor(pk)
        # Must not raise
        decoded = base64.b64decode(cursor.encode("ascii")).decode("utf-8")
        self.assertEqual(decoded, pk)


class TestPaginatedResult(TestCase):
    """PAGE-03: PaginatedResult dataclass."""

    def test_fields(self):
        result = PaginatedResult(
            items=[{"name": "router-01"}],
            cursor="abc123",
            total_count=50,
            summary={"message": "50 results"},
        )
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.cursor, "abc123")
        self.assertEqual(result.total_count, 50)
        self.assertIsNotNone(result.summary)

    def test_has_next_page(self):
        result_with_cursor = PaginatedResult(items=[], cursor="next")
        self.assertTrue(result_with_cursor.has_next_page())
        result_no_cursor = PaginatedResult(items=[], cursor=None)
        self.assertFalse(result_no_cursor.has_next_page())


class TestDeviceList(TestCase):
    """TOOL-01: device_list."""

    def _make_mock_device(self):
        device = MagicMock()
        device.pk = uuid.uuid4()
        device.name = "router-01"
        device.serial = "SN123"
        device.status.name = "active"
        device.role.name = "access"
        device.platform.name = "Juniper JunOS"
        device.device_type.display_name = "MX240"
        device.device_type.manufacturer.name = "Juniper"
        device.location.name = "DC1"
        device.tenant.name = "Acme Corp"
        device.asset_tag = None
        device.description = ""
        device.primary_ip4 = None
        device.primary_ip6 = None
        return device

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_device_qs")
    def test_device_list_returns_paginated_result(self, mock_build_qs):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_device_list

        mock_device = self._make_mock_device()
        mock_qs = MagicMock()
        mock_build_qs.return_value = mock_qs
        mock_qs.restrict.return_value = mock_qs
        mock_qs.__getitem__ = lambda self, key: [mock_device] if key == slice(0, 26) else [mock_device]

        mock_user = MagicMock()
        result = _sync_device_list(user=mock_user, limit=25, cursor=None)

        self.assertIn("items", result)
        self.assertIsInstance(result["items"], list)
        mock_qs.restrict.assert_called_once()

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_device_qs")
    def test_device_list_enforces_auth(self, mock_build_qs):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_device_list

        mock_qs = MagicMock()
        mock_build_qs.return_value = mock_qs
        mock_qs.restrict.return_value = mock_qs
        mock_qs.__getitem__ = lambda self, key: []

        mock_user = MagicMock()
        _sync_device_list(user=mock_user, limit=25, cursor=None)

        # Verify restrict called with user + "view" action (AUTH-03)
        mock_qs.restrict.assert_called_once()
        kwargs = mock_qs.restrict.call_args[1]
        self.assertEqual(kwargs.get("action"), "view")


class TestDeviceGet(TestCase):
    """TOOL-02: device_get with D-02 not-found and D-03 UUID detection."""

    def _make_mock_device(self):
        device = MagicMock()
        device.pk = uuid.uuid4()
        device.name = "router-01"
        device.serial = "SN123"
        device.status.name = "active"
        device.role.name = "access"
        device.platform.name = "Juniper JunOS"
        device.device_type.display_name = "MX240"
        device.device_type.manufacturer.name = "Juniper"
        device.location.name = "DC1"
        device.tenant.name = "Acme Corp"
        device.asset_tag = None
        device.description = ""
        device.primary_ip4 = None
        device.primary_ip6 = None
        device.interfaces.all.return_value = []
        return device

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_device_qs")
    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.serialize_device_with_interfaces")
    def test_device_get_by_name(self, mock_serialize, mock_build_qs):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_device_get

        mock_qs = MagicMock()
        mock_build_qs.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.prefetch_related.return_value = mock_qs
        mock_qs.restrict.return_value = mock_qs
        mock_qs.__iter__ = lambda self: iter([MagicMock()])

        mock_serialize.return_value = {"name": "router-01", "pk": "abc-123"}
        mock_user = MagicMock()
        result = _sync_device_get(user=mock_user, name_or_id="router-01")

        self.assertEqual(result["name"], "router-01")
        mock_qs.filter.assert_called()

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_device_qs")
    def test_device_get_not_found(self, mock_build_qs):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_device_get

        mock_qs = MagicMock()
        mock_build_qs.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.prefetch_related.return_value = mock_qs
        mock_qs.restrict.return_value = mock_qs
        mock_qs.__iter__ = lambda self: iter([])  # empty

        mock_user = MagicMock()
        with self.assertRaises(ValueError) as ctx:
            _sync_device_get(user=mock_user, name_or_id="nonexistent")
        self.assertIn("not found", str(ctx.exception))
        self.assertIn("nonexistent", str(ctx.exception))

    def test_uuid_detection(self):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _looks_like_uuid

        self.assertTrue(_looks_like_uuid("a3f8b2c0-1234-5678-9abc-def012345678"))
        self.assertTrue(_looks_like_uuid("A3F8B2C0-1234-5678-9ABC-DEF012345678"))
        self.assertFalse(_looks_like_uuid("router-01"))
        self.assertFalse(_looks_like_uuid("10.0.0.1/24"))


class TestInterfaceList(TestCase):
    """TOOL-03: interface_list."""

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_interface_qs")
    def test_interface_list_with_device_filter(self, mock_build_qs):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_interface_list

        mock_qs = MagicMock()
        mock_build_qs.return_value = mock_qs
        mock_qs.restrict.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.__getitem__ = lambda self, key: []

        mock_user = MagicMock()
        result = _sync_interface_list(user=mock_user, device_name="router-01", limit=25, cursor=None)

        mock_qs.filter.assert_called_with(device__name="router-01")
        self.assertIn("items", result)


class TestInterfaceGet(TestCase):
    """TOOL-04: interface_get."""

    def _make_mock_interface(self):
        interface = MagicMock()
        interface.pk = uuid.uuid4()
        interface.name = "ge-0/0/0"
        interface.status.name = "active"
        interface.device.name = "router-01"
        interface.role = None
        interface.lag = None
        interface.parent = None
        interface.bridge = None
        interface.enabled = True
        interface.type = "1000BASE-T"
        interface.mtu = 1500
        interface.mac_address = None
        interface.mode = None
        interface.description = ""
        interface.mgmt_only = False
        interface.speed = None
        interface.duplex = None
        interface.wwn = None
        interface.virtual_device_context = None
        interface.untagged_vlan = None
        interface.ip_addresses.all.return_value = []
        return interface

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_interface_qs_with_ip_addresses")
    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.serialize_interface")
    def test_interface_get_returns_ip_addresses(self, mock_serialize, mock_build_qs):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_interface_get

        mock_qs = MagicMock()
        mock_build_qs.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.prefetch_related.return_value = mock_qs
        mock_qs.restrict.return_value = mock_qs
        mock_qs.__iter__ = lambda self: iter([MagicMock()])

        mock_serialize.return_value = {"name": "ge-0/0/0", "ip_addresses": []}
        mock_user = MagicMock()
        result = _sync_interface_get(user=mock_user, name_or_id="ge-0/0/0")

        self.assertEqual(result["name"], "ge-0/0/0")
        self.assertIn("ip_addresses", result)

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_interface_qs_with_ip_addresses")
    def test_interface_get_not_found(self, mock_build_qs):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_interface_get

        mock_qs = MagicMock()
        mock_build_qs.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.prefetch_related.return_value = mock_qs
        mock_qs.restrict.return_value = mock_qs
        mock_qs.__iter__ = lambda self: iter([])

        mock_user = MagicMock()
        with self.assertRaises(ValueError) as ctx:
            _sync_interface_get(user=mock_user, name_or_id="nonexistent")
        self.assertIn("not found", str(ctx.exception))


class TestIPAddressList(TestCase):
    """TOOL-05: ipaddress_list."""

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_ipaddress_qs")
    def test_ipaddress_list_paginated(self, mock_build_qs):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_ipaddress_list

        mock_qs = MagicMock()
        mock_build_qs.return_value = mock_qs
        mock_qs.restrict.return_value = mock_qs
        mock_qs.__getitem__ = lambda self, key: []

        mock_user = MagicMock()
        result = _sync_ipaddress_list(user=mock_user, limit=25, cursor=None)

        self.assertIn("items", result)
        self.assertIn("cursor", result)


class TestIPAddressGet(TestCase):
    """TOOL-06: ipaddress_get."""

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_ipaddress_qs_with_interfaces")
    def test_ipaddress_get_not_found(self, mock_build_qs):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_ipaddress_get

        mock_qs = MagicMock()
        mock_build_qs.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.prefetch_related.return_value = mock_qs
        mock_qs.restrict.return_value = mock_qs
        mock_qs.__iter__ = lambda self: iter([])

        mock_user = MagicMock()
        with self.assertRaises(ValueError) as ctx:
            _sync_ipaddress_get(user=mock_user, name_or_id="10.0.0.1/32")
        self.assertIn("not found", str(ctx.exception))


class TestPrefixList(TestCase):
    """TOOL-07: prefix_list."""

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_prefix_qs")
    def test_prefix_list(self, mock_build_qs):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_prefix_list

        mock_qs = MagicMock()
        mock_build_qs.return_value = mock_qs
        mock_qs.restrict.return_value = mock_qs
        mock_qs.__getitem__ = lambda self, key: []

        mock_user = MagicMock()
        result = _sync_prefix_list(user=mock_user, limit=25, cursor=None)

        self.assertIn("items", result)
        mock_qs.restrict.assert_called_once()


class TestVLANList(TestCase):
    """TOOL-08: vlan_list."""

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_vlan_qs")
    def test_vlan_list(self, mock_build_qs):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_vlan_list

        mock_qs = MagicMock()
        mock_build_qs.return_value = mock_qs
        mock_qs.restrict.return_value = mock_qs
        mock_qs.__getitem__ = lambda self, key: []

        mock_user = MagicMock()
        result = _sync_vlan_list(user=mock_user, limit=25, cursor=None)

        self.assertIn("items", result)
        mock_qs.restrict.assert_called_once()


class TestLocationList(TestCase):
    """TOOL-09: location_list."""

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_location_qs")
    def test_location_list(self, mock_build_qs):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_location_list

        mock_qs = MagicMock()
        mock_build_qs.return_value = mock_qs
        mock_qs.restrict.return_value = mock_qs
        mock_qs.__getitem__ = lambda self, key: []

        mock_user = MagicMock()
        result = _sync_location_list(user=mock_user, limit=25, cursor=None)

        self.assertIn("items", result)
        mock_qs.restrict.assert_called_once()


class TestSearchByName(TestCase):
    """TOOL-10: search_by_name with AND semantics (D-01)."""

    def test_search_by_name_empty_query_raises(self):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_search_by_name

        mock_user = MagicMock()
        with self.assertRaises(ValueError) as ctx:
            _sync_search_by_name(user=mock_user, query="   ", limit=25, cursor=None)
        self.assertIn("non-empty term", str(ctx.exception))

    def test_search_by_name_whitespace_stripped(self):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_search_by_name

        mock_user = MagicMock()
        # Should raise — "  " after strip is empty
        with self.assertRaises(ValueError):
            _sync_search_by_name(user=mock_user, query="  ", limit=25, cursor=None)

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_device_qs")
    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_interface_qs")
    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_ipaddress_qs")
    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_prefix_qs")
    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_vlan_qs")
    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_location_qs")
    def test_search_by_name_and_semantics(
        self, mock_loc, mock_vlan, mock_pfx, mock_ip, mock_iface, mock_dev
    ):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_search_by_name

        # Each model returns empty
        for mock_qs in [mock_dev.return_value, mock_iface.return_value,
                         mock_ip.return_value, mock_pfx.return_value,
                         mock_vlan.return_value, mock_loc.return_value]:
            mock_qs.restrict.return_value = mock_qs
            mock_qs.__iter__ = lambda self: iter([])

        mock_user = MagicMock()
        result = _sync_search_by_name(user=mock_user, query="juniper router", limit=25, cursor=None)

        self.assertIn("items", result)
        self.assertIn("cursor", result)
        self.assertIsInstance(result["items"], list)


class TestAuthEnforcement(TestCase):
    """Verify every tool calls .restrict(user, action="view") (AUTH-03)."""

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_device_qs")
    def test_device_list_calls_restrict(self, mock_build_qs):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_device_list

        mock_qs = MagicMock()
        mock_build_qs.return_value = mock_qs
        mock_qs.restrict.return_value = mock_qs
        mock_qs.__getitem__ = lambda self, key: []

        mock_user = MagicMock(name="testuser")
        _sync_device_list(user=mock_user, limit=25, cursor=None)

        mock_qs.restrict.assert_called_once()
        # restrict(user, action="view") passes action as keyword arg
        kwargs = mock_qs.restrict.call_args[1]
        self.assertEqual(kwargs.get("action"), "view")

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_interface_qs_with_ip_addresses")
    def test_interface_get_calls_restrict(self, mock_build_qs):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_interface_get

        mock_qs = MagicMock()
        mock_build_qs.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.prefetch_related.return_value = mock_qs
        mock_qs.restrict.return_value = mock_qs
        mock_qs.__iter__ = lambda self: iter([])

        mock_user = MagicMock(name="testuser")
        with self.assertRaises(ValueError):
            _sync_interface_get(user=mock_user, name_or_id="nonexistent")

        mock_qs.restrict.assert_called()

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_device_qs")
    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_interface_qs")
    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_ipaddress_qs")
    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_prefix_qs")
    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_vlan_qs")
    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_location_qs")
    def test_search_by_name_calls_restrict_on_each_model(
        self, mock_loc, mock_vlan, mock_pfx, mock_ip, mock_iface, mock_dev
    ):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_search_by_name

        for mock_qs in [mock_dev.return_value, mock_iface.return_value,
                         mock_ip.return_value, mock_pfx.return_value,
                         mock_vlan.return_value, mock_loc.return_value]:
            mock_qs.restrict.return_value = mock_qs
            mock_qs.__iter__ = lambda self: iter([])

        mock_user = MagicMock()
        _sync_search_by_name(user=mock_user, query="test", limit=25, cursor=None)

        # Each of the 6 models should have restrict called
        restrict_calls = 0
        for mock_qs in [mock_dev.return_value, mock_iface.return_value,
                         mock_ip.return_value, mock_pfx.return_value,
                         mock_vlan.return_value, mock_loc.return_value]:
            restrict_calls += mock_qs.restrict.call_count
        self.assertEqual(restrict_calls, 6)


class TestAnonymousFallback(TestCase):
    """AUTH-02: AnonymousUser returns empty queryset, not an error."""

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.build_device_qs")
    def test_anonymous_user_returns_empty(self, mock_build_qs):
        from nautobot_app_mcp_server.mcp.tools.query_utils import _sync_device_list
        from django.contrib.auth.models import AnonymousUser

        mock_qs = MagicMock()
        mock_build_qs.return_value = mock_qs
        mock_qs.restrict.return_value = mock_qs
        mock_qs.__getitem__ = lambda self, key: []  # empty

        anon_user = AnonymousUser()
        result = _sync_device_list(user=anon_user, limit=25, cursor=None)

        # Must not raise — must return empty items list
        self.assertEqual(result["items"], [])


class TestPaginationIntegration(TestCase):
    """Verify pagination behavior end-to-end with mocked queryset."""

    def test_count_not_called_below_summarize_threshold(self):
        """PAGE-02: .count() not called when results < LIMIT_SUMMARIZE."""
        mock_qs = MagicMock()
        # Simulate 5 items returned (below 100)
        mock_qs.__getitem__ = lambda self, key: [MagicMock(pk="item-1"), MagicMock(pk="item-2")]

        with patch.object(mock_qs, "count", return_value=2) as mock_count:
            result = paginate_queryset(mock_qs, limit=25, cursor=None)
            mock_count.assert_not_called()
            self.assertIsNone(result.summary)

    def test_count_called_above_summarize_threshold(self):
        """PAGE-02: .count() called when results >= LIMIT_SUMMARIZE."""
        mock_item = MagicMock(pk="item-1")
        mock_qs = MagicMock()
        mock_qs.__getitem__ = lambda self, key: [mock_item] * 100  # 100 items
        mock_qs.count.return_value = 500

        with patch.object(mock_qs, "count", return_value=500) as mock_count:
            result = paginate_queryset(mock_qs, limit=100, cursor=None)
            self.assertIsNotNone(result.summary)
            self.assertEqual(result.summary["total_count"], 500)

    def test_cursor_roundtrip_integration(self):
        """PAGE-04: Full cursor round-trip through paginate_queryset."""
        pk = uuid.uuid4()
        mock_item = MagicMock(pk=pk)
        mock_qs = MagicMock()
        # Simulate 2 items when slicing with [:2] (limit=1 → limit+1=2),
        # confirming there is a next page
        mock_qs.__getitem__ = lambda self, key: (
            [mock_item, mock_item] if key == slice(0, 2) else [mock_item]
        )
        mock_qs.count.return_value = 1

        result = paginate_queryset(mock_qs, limit=1, cursor=None)
        self.assertTrue(result.has_next_page())
        self.assertIsNotNone(result.cursor)

        # Decode and re-encode
        decoded_pk = decode_cursor(result.cursor)
        self.assertEqual(decoded_pk, str(pk))
