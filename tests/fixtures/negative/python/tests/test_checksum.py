from ciwf_negative import checksum


def test_checksum_is_deliberately_wrong() -> None:
    """Asserts a value the implementation cannot produce, so pytest must fail.

    If this ever passes, python-ci has stopped reporting test failures.
    """
    assert checksum("ci") == 999
