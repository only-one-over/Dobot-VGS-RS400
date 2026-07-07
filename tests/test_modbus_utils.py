"""Tests for Modbus F32 encode/decode."""
import pytest
import struct
from dobot_move.communication.modbus_utils import float_to_regs, regs_to_float


class TestFloatToRegs:
    """Test float to register conversion."""

    def test_zero(self):
        high, low = float_to_regs(0.0)
        result = regs_to_float(high, low)
        assert result == pytest.approx(0.0)

    def test_positive(self):
        high, low = float_to_regs(123.456)
        result = regs_to_float(high, low)
        assert result == pytest.approx(123.456, rel=1e-5)

    def test_negative(self):
        high, low = float_to_regs(-50.5)
        result = regs_to_float(high, low)
        assert result == pytest.approx(-50.5, rel=1e-5)

    def test_large_value(self):
        high, low = float_to_regs(9999.99)
        result = regs_to_float(high, low)
        assert result == pytest.approx(9999.99, rel=1e-4)

    def test_roundtrip_special_values(self):
        """Test roundtrip for various values."""
        for val in [0.0, 1.0, -1.0, 100.0, 0.001, 3.14159]:
            high, low = float_to_regs(val)
            result = regs_to_float(high, low)
            assert result == pytest.approx(val, rel=1e-5), f"Roundtrip failed for {val}"

    def test_manual_verification(self):
        """Manually verify encoding against struct.pack."""
        val = 42.0
        high, low = float_to_regs(val)
        packed = struct.pack('>f', val)
        expected_high = struct.unpack('>H', packed[0:2])[0]
        expected_low = struct.unpack('>H', packed[2:4])[0]
        assert high == expected_high
        assert low == expected_low
