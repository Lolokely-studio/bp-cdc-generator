import pytest

from esquisse.auth.bearer import bearer_token


@pytest.mark.parametrize(
    "entete, attendu",
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
def test_bearer_token(entete, attendu):
    assert bearer_token(entete) == attendu
