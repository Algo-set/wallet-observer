"""Exact bounded arithmetic and machine-safe errors."""

from decimal import Context, Decimal, DecimalException, Inexact, localcontext

_CONTEXT = Context(prec=256)
_CONTEXT.traps[Inexact] = True


class ObserverError(ValueError):
    """A fixed error code; never an endpoint or upstream response."""


def integer(value: object, low: int = 0, high: int = 2**63 - 1) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ObserverError("invalid_integer")
    return value


def amount(value: object) -> Decimal:
    if not isinstance(value, (str, Decimal, int)) or isinstance(value, bool):
        raise ObserverError("invalid_decimal")
    try:
        if isinstance(value, str) and len(value) > 256:
            raise ValueError
        result = Decimal(value)
        if not result.is_finite() or result < 0:
            raise ValueError
        parts = result.as_tuple()
        if len(parts.digits) > 96 or not -56 <= parts.exponent <= 56:
            raise ValueError
        return result
    except (ValueError, DecimalException):
        raise ObserverError("invalid_decimal") from None


def calculate(left: Decimal, operation: str, right: Decimal) -> Decimal:
    try:
        with localcontext(_CONTEXT):
            if operation == "+":
                result = left + right
            elif operation == "-":
                result = max(Decimal(0), left - right)
            elif operation == "*":
                result = left * right
            else:
                raise ObserverError("invalid_operation")
            return amount(result)
    except DecimalException:
        raise ObserverError("decimal_overflow") from None


def unique(values: list[object]) -> None:
    if any(not isinstance(v, str) or not v.strip() for v in values):
        raise ObserverError("invalid_identifier")
    if len(set(values)) != len(values):
        raise ObserverError("duplicate_identifier")
