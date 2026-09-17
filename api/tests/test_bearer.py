import pytest

from esquisse.auth.bearer import bearer_token


@pytest.mark.parametrize(
    "header, expected",
    [
        ("Bearer abc", "abc"),
        ("bearer abc", "abc"),
        ("BEARER abc", "abc"),
        ("Bearer   abc  ", "abc"),
        ("", ""),
        ("abc", ""),
        ("Basic abc", ""),
        ("Bearer", ""),
    ],
)
def test_bearer_token(header, expected):
    assert bearer_token(header) == expected
