import pytest

from brain.utils.camelcase import split_camel


@pytest.mark.parametrize("inp,expected", [
    ("useCurrentUser", "use Current User"),
    ("LoginButton", "Login Button"),
    ("ActivePromos", "Active Promos"),
    ("HTTPStatus", "HTTP Status"),
    ("API", "API"),
    ("httpGet2xxResponse", "http Get 2xx Response"),
    ("simple", "simple"),
    ("", ""),
    ("ALLCAPS", "ALLCAPS"),
    ("snake_case", "snake_case"),
    ("kebab-case", "kebab-case"),
    ("mixedCase_with_snake", "mixed Case_with_snake"),
])
def test_split_camel(inp: str, expected: str) -> None:
    assert split_camel(inp) == expected
