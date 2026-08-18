"""Modelos de respuesta del paquete."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["SkippedRecord", "InsertResult", "QueryResult", "User"]


@dataclass(frozen=True)
class SkippedRecord:
    """Registro que el servidor rechazó durante un ``POST /insert``."""

    index: int
    reason: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SkippedRecord:
        try:
            index = int(data.get("index", -1))
        except (TypeError, ValueError):
            index = -1
        return cls(index=index, reason=str(data.get("reason", "sin motivo")))


@dataclass(frozen=True)
class InsertResult:
    """Resultado de :meth:`RobleClient.create_many`.

    El endpoint responde ``200`` aunque haya rechazado registros, así que
    conviene revisar :attr:`skipped` antes de dar la escritura por buena. Con
    ``strict=True`` esa comprobación se convierte en un error.
    """

    inserted: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[SkippedRecord] = field(default_factory=list)

    @property
    def has_skipped(self) -> bool:
        """``True`` si el servidor rechazó al menos un registro."""
        return bool(self.skipped)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> InsertResult:
        raw_inserted = data.get("inserted")
        raw_skipped = data.get("skipped")
        return cls(
            inserted=[r for r in raw_inserted if isinstance(r, dict)]
            if isinstance(raw_inserted, list)
            else [],
            skipped=[
                SkippedRecord.from_json(s) for s in raw_skipped if isinstance(s, dict)
            ]
            if isinstance(raw_skipped, list)
            else [],
        )


@dataclass(frozen=True)
class QueryResult:
    """Resultado de :meth:`RobleClient.execute_query`."""

    success: bool = False
    command: str | None = None
    row_count: int = 0
    rows: list[Any] = field(default_factory=list)
    fields: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> QueryResult:
        try:
            row_count = int(data.get("rowCount", 0))
        except (TypeError, ValueError):
            row_count = 0
        rows = data.get("rows")
        fields_ = data.get("fields")
        return cls(
            success=data.get("success") is True,
            command=data.get("command"),
            row_count=row_count,
            rows=list(rows) if isinstance(rows, list) else [],
            fields=[f for f in fields_ if isinstance(f, dict)]
            if isinstance(fields_, list)
            else [],
        )


@dataclass(frozen=True)
class User:
    """Perfil del usuario autenticado, devuelto por ``GET /me``."""

    id: str
    user_id: str
    email: str
    name: str
    extra: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> User:
        extra = data.get("extra")
        return cls(
            id=str(data.get("id", "")),
            user_id=str(data.get("userId", "")),
            email=str(data.get("email", "")),
            name=str(data.get("name", "")),
            extra=extra if isinstance(extra, dict) else None,
            created_at=data.get("createdAt"),
            updated_at=data.get("updatedAt"),
            raw=dict(data),
        )
