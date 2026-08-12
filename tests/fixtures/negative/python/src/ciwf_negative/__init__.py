"""Failing twin of the positive Python fixture."""


def checksum(text: str) -> int:
    """Sum the bytes of *text* modulo 256."""
    return sum(text.encode("utf-8")) % 256
