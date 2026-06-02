import pytest

from homeshare_common.duration import MAX_EXPIRES_IN, parse_duration

_Y = 365 * 24 * 3600
_W = 7 * 24 * 3600
_D = 24 * 3600
_H = 3600
_M = 60


@pytest.mark.parametrize(
    "text, expected",
    [
        pytest.param("", None, id="empty"),
        pytest.param("  ", None, id="whitespace"),
        pytest.param("never", None, id="never"),
        pytest.param(" Never ", None, id="never-mixed-case"),
        pytest.param("1 year", _Y, id="year-singular-long"),
        pytest.param("1 week", _W, id="week-singular-long"),
        pytest.param("2 weeks", 2 * _W, id="weeks-long"),
        pytest.param("7 days", 7 * _D, id="days-long"),
        pytest.param("1 day", _D, id="days-singular-long"),
        pytest.param("2 hours", 2 * _H, id="hours-long"),
        pytest.param("30 minutes", 30 * _M, id="minutes-long"),
        pytest.param("1 second", 1, id="seconds-singular-long"),
        pytest.param("1 seconds", 1, id="plural-ungrammatical"),
        pytest.param("90 seconds", 90, id="90-seconds"),
        pytest.param("7d", 7 * _D, id="short-days"),
        pytest.param("2w", 2 * _W, id="short-weeks"),
        pytest.param("30s", 30, id="short-seconds"),
        pytest.param("01d", _D, id="short-leading-zero"),
        pytest.param("007d", 7 * _D, id="short-multiple-leading-zeros"),
        pytest.param(
            "1y3d2h30m", _Y + 3 * _D + 2 * _H + 30 * _M, id="short-multiple-units"
        ),
        pytest.param("1h30s", _H + 30, id="short-hours-and-seconds"),
        pytest.param(
            "10y2w300d23h59m59s",
            10 * _Y + 2 * _W + 300 * _D + 23 * _H + 59 * _M + 59,
            id="all-units-short",
        ),
        pytest.param(
            "10 years 300 days 51 weeks 23 hours 59 minutes 59 seconds",
            10 * _Y + 51 * _W + 300 * _D + 23 * _H + 59 * _M + 59,
            id="all-units-long",
        ),
        pytest.param("1y 3d", _Y + 3 * _D, id="short-with-spaces"),
        pytest.param("1 year 3d", _Y + 3 * _D, id="mixed-long-short"),
        pytest.param("3d 2 hours", 3 * _D + 2 * _H, id="mixed-short-long"),
    ],
)
def test_parse_duration(text: str, expected: int | None) -> None:
    assert parse_duration(text) == expected


@pytest.mark.parametrize(
    "text, match",
    [
        pytest.param("asdf", "Duration format invalid", id="invalid-text"),
        # A bare integer with no unit is not a valid duration format
        pytest.param("42", "Duration format invalid", id="unitless-number"),
        # A unit letter with no preceding digit is not valid
        pytest.param("y", "Duration format invalid", id="unit-without-number"),
        # Unknown unit letter is not valid
        pytest.param("5x", "Duration format invalid", id="unknown-unit"),
        # Zero duration is not valid in either short or long format
        pytest.param("0d", "Duration format invalid", id="zero-duration-short"),
        pytest.param("0 days", "Duration format invalid", id="zero-duration-long"),
        # Negative durations are rejected
        pytest.param(
            "-1d", "Negative durations are not supported", id="negative-sign-rejected"
        ),
        # Decimal durations are rejected
        pytest.param(
            "1.5h",
            "Durations with decimals are not supported",
            id="decimal-rejected-short",
        ),
        pytest.param(
            "1.5 hours",
            "Durations with decimals are not supported",
            id="decimal-rejected-long",
        ),
        # Strings longer than 64 characters are rejected before any parsing
        pytest.param("9" * 64 + "y", "exceeds the maximum", id="string-too-long"),
        pytest.param("9999999999y", "exceeds the maximum", id="oversized-short"),
        pytest.param("9999999999 years", "exceeds the maximum", id="oversized-spaced"),
        # Each unit is within its individual limit, but the accumulated total overflows
        pytest.param("136y71d", "exceeds the maximum", id="oversized-accumulated"),
        # Unexpected characters mixed with valid tokens are rejected
        pytest.param("abc1y", "Duration format invalid", id="junk-prefix"),
        pytest.param("1ydef2d", "Duration format invalid", id="junk-between-units"),
        # A bare unit letter with no preceding digit is rejected by the strict parser
        pytest.param("d1h", "Duration format invalid", id="unit-before-number"),
        # Duplicate units are rejected
        pytest.param("1d3d", "Duplicate unit", id="duplicate-short"),
        pytest.param("1d 3 days", "Duplicate unit", id="duplicate-mixed"),
        pytest.param("1 day 3 days", "Duplicate unit", id="duplicate-long"),
    ],
)
def test_parse_duration_raises(text: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_duration(text)


def test_max_expires_in_is_accepted() -> None:
    # MAX_EXPIRES_IN seconds expressed as short seconds should be the boundary value
    assert parse_duration(f"{MAX_EXPIRES_IN}s") == MAX_EXPIRES_IN
