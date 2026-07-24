"""Rev-D input bias must come only from the qualified external 47k network."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

LANE_DIR = Path(__file__).resolve().parents[1] / "lane_node"
if str(LANE_DIR) not in sys.path:
    sys.path.insert(0, str(LANE_DIR))

import controller_io  # noqa: E402


class RegisterBus:
    def __init__(self, _bus_id=1, *, bad_readback=None):
        self.registers = {}
        self.writes = []
        self.bad_readback = bad_readback

    def write_byte_data(self, addr, reg, value):
        self.writes.append((addr, reg, value))
        self.registers[(addr, reg)] = value

    def read_byte_data(self, addr, reg):
        if self.bad_readback == (addr, reg):
            return self.registers.get((addr, reg), 0) ^ 0x01
        return self.registers.get((addr, reg), 0)


def _install_fake_smbus(monkeypatch, bus):
    module = types.SimpleNamespace(SMBus=lambda _bus_id: bus)
    monkeypatch.setitem(sys.modules, "smbus2", module)


def test_machine_inputs_disable_all_mcp_internal_pullups(monkeypatch):
    bus = RegisterBus()
    _install_fake_smbus(monkeypatch, bus)

    controller_io.MachineIO(21, 1)

    for addr in (controller_io.ADDR_IN_A, controller_io.ADDR_IN_B):
        assert bus.registers[(addr, controller_io._GPPUA)] == 0x00
        assert bus.registers[(addr, controller_io._GPPUB)] == 0x00


def test_mcp_configuration_readback_mismatch_fails_startup():
    bus = RegisterBus(
        bad_readback=(controller_io.ADDR_IN_A, controller_io._GPPUA))

    with pytest.raises(IOError, match="GPPUA readback"):
        controller_io._MCP23017(
            bus,
            controller_io.ADDR_IN_A,
            dir_mask_a=0xFF,
            dir_mask_b=0xFF,
            pullup_a=0x00,
            pullup_b=0x00,
        )
