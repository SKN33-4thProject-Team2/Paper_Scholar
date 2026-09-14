"""모델 생성 옵션에 공통으로 사용하는 검증 함수."""

from __future__ import annotations


def resolve_float(
    name: str,
    value: object,
    *,
    minimum: float,
    maximum: float | None = None,
) -> float:
    """실수 옵션의 타입과 범위를 검증한다."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}은(는) 숫자여야 합니다.")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} 범위가 올바르지 않습니다.")
    return float(value)


def resolve_positive_int(name: str, value: object) -> int:
    """1 이상의 정수 옵션을 검증한다."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name}은(는) 1 이상의 정수여야 합니다.")
    return value


def resolve_nonnegative_int(name: str, value: object) -> int:
    """0 이상의 정수 옵션을 검증한다."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name}은(는) 0 이상의 정수여야 합니다.")
    return value
