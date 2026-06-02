# Maximum expires duration in seconds
MAX_EXPIRES_IN: int = 2**32 - 1

# Canonical multipliers keyed by singular long name.
# Short (single-char) and plural forms are derived from these.
# Months are intentionally excluded, their length is ambiguous (28-31 days).
_MULTIPLIERS: dict[str, int] = {
    "year": 365 * 24 * 3600,
    "week": 7 * 24 * 3600,
    "day": 24 * 3600,
    "hour": 3600,
    "minute": 60,
    "second": 1,
}

_SHORT_TO_CANONICAL: dict[str, str] = {k[0]: k for k in _MULTIPLIERS}
_LONG_TO_CANONICAL: dict[str, str] = {
    form: canonical
    for canonical in _MULTIPLIERS
    for form in (canonical, canonical + "s")
}


def parse_duration(duration_str: str) -> int | None:
    """Parse a human-readable duration string into seconds.

    Reference the unit tests for accepted and rejected formats.
    """
    max_chars: int = 64
    string_len = len(duration_str)
    if string_len > max_chars:
        raise ValueError(
            f"Duration string length of {string_len} exceeds the maximum of {max_chars} characters"
        )

    s = duration_str.strip().lower()
    if not s or s == "never":
        return None

    if "-" in s:
        raise ValueError("Negative durations are not supported")

    if "." in s:
        raise ValueError("Durations with decimals are not supported")

    format_invalid_error = ValueError(f"Duration format invalid: {duration_str!r}")

    # Extract (number, canonical_unit) pairs from the string.
    # Each space-separated part is either a compact short token like "1y3d",
    # a bare number paired with the next word part ("1" "year"), or invalid.
    tokens: list[tuple[int, str]] = []
    parts = s.split()
    i = 0
    while i < len(parts):
        part = parts[i]
        if not part or not part[0].isdigit():
            raise format_invalid_error

        # Try to consume the entire part as one or more compact short tokens
        j = 0
        part_tokens: list[tuple[int, str]] = []
        while j < len(part):
            if not part[j].isdigit():
                break
            k = j + 1
            while k < len(part) and part[k].isdigit():
                k += 1
            if k < len(part) and part[k] in _SHORT_TO_CANONICAL:
                if k + 1 < len(part) and part[k + 1].isalpha():
                    break
                part_tokens.append((int(part[j:k]), _SHORT_TO_CANONICAL[part[k]]))
                j = k + 1
            else:
                break

        if j == len(part) and part_tokens:
            tokens.extend(part_tokens)
            i += 1
            continue

        # Not a compact short token, try bare number + next part as long unit
        if part.isdigit():
            num = int(part)
            if i + 1 < len(parts) and parts[i + 1] in _LONG_TO_CANONICAL:
                tokens.append((num, _LONG_TO_CANONICAL[parts[i + 1]]))
                i += 2
                continue

        raise format_invalid_error

    duration_exceeded_error = ValueError(
        f"Duration of {duration_str!r} exceeds the maximum of {MAX_EXPIRES_IN} seconds"
    )

    # Validate: no zero values, no duplicate units, no overflow.
    seen_units: set[str] = set()
    total_seconds = 0
    for num, unit in tokens:
        if num <= 0:
            raise format_invalid_error
        if unit in seen_units:
            raise ValueError(f"Duplicate unit in duration: {duration_str!r}")
        seen_units.add(unit)
        multiplier = _MULTIPLIERS[unit]
        if num > MAX_EXPIRES_IN // multiplier:
            raise duration_exceeded_error
        total_seconds += num * multiplier
        if total_seconds > MAX_EXPIRES_IN:
            raise duration_exceeded_error

    if total_seconds > 0:
        return total_seconds

    raise format_invalid_error
