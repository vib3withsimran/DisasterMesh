"""
Unit tests for the WebSocket ConnectionManager — Phase 6.

Tests cover:
  - connect / disconnect lifecycle
  - broadcast delivers to all active clients
  - dead connections are automatically evicted on broadcast failure
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.routers.communication import ConnectionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ws() -> MagicMock:
    """Return a mock WebSocket with async accept / send_json / receive_text."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.receive_text = AsyncMock(return_value="ping")
    return ws


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConnectionManager:
    def setup_method(self):
        self.manager = ConnectionManager()

    @pytest.mark.asyncio
    async def test_connect_adds_to_active_set(self):
        ws = _make_ws()
        await self.manager.connect(ws)
        assert ws in self.manager.active
        ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_removes_from_active_set(self):
        ws = _make_ws()
        await self.manager.connect(ws)
        self.manager.disconnect(ws)
        assert ws not in self.manager.active

    @pytest.mark.asyncio
    async def test_disconnect_idempotent_for_unknown_socket(self):
        """Disconnecting a socket that was never connected must not raise."""
        ws = _make_ws()
        self.manager.disconnect(ws)  # should silently succeed

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_clients(self):
        ws1 = _make_ws()
        ws2 = _make_ws()
        await self.manager.connect(ws1)
        await self.manager.connect(ws2)

        payload = {"event": "lifecycle_transition", "new_status": "EN_ROUTE"}
        await self.manager.broadcast(payload)

        ws1.send_json.assert_awaited_once_with(payload)
        ws2.send_json.assert_awaited_once_with(payload)

    @pytest.mark.asyncio
    async def test_broadcast_evicts_dead_connections(self):
        """A client that raises on send_json must be removed from the active set."""
        ws_good = _make_ws()
        ws_dead = _make_ws()
        ws_dead.send_json = AsyncMock(side_effect=RuntimeError("connection closed"))

        await self.manager.connect(ws_good)
        await self.manager.connect(ws_dead)

        payload = {"event": "lifecycle_transition", "new_status": "ON_SCENE"}
        await self.manager.broadcast(payload)

        # Good client received the message
        ws_good.send_json.assert_awaited_once_with(payload)
        # Dead client is evicted
        assert ws_dead not in self.manager.active
        # Good client remains
        assert ws_good in self.manager.active

    @pytest.mark.asyncio
    async def test_broadcast_to_empty_set_is_no_op(self):
        """Broadcasting with no clients must not raise."""
        await self.manager.broadcast({"event": "test"})

    @pytest.mark.asyncio
    async def test_multiple_connect_disconnect_cycles(self):
        """Repeated connect/disconnect cycles must keep the set consistent."""
        ws = _make_ws()
        for _ in range(3):
            ws.accept.reset_mock()
            await self.manager.connect(ws)
            assert ws in self.manager.active
            self.manager.disconnect(ws)
            assert ws not in self.manager.active
