"""Errores del cliente Roble.

Todos heredan de :class:`RobleError`, así que un ``except RobleError`` sirve de
red de seguridad para cualquier fallo del paquete.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .models import InsertResult

__all__ = [
    "RobleError",
    "RobleNetworkError",
    "RobleTimeoutError",
    "RobleHttpError",
    "RobleFormatError",
    "RobleAuthError",
    "RoblePartialInsertError",
]


class RobleError(Exception):
    """Error base del cliente Roble."""

    def __init__(self, message: str, code: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class RobleNetworkError(RobleError):
    """Sin conexión, DNS no resuelto o el servidor no responde."""


class RobleTimeoutError(RobleError):
    """La petición superó el ``timeout`` configurado."""


class RobleHttpError(RobleError):
    """El servidor respondió con un código fuera de 2xx."""

    def __init__(self, status_code: int, message: str, code: Any | None = None) -> None:
        super().__init__(message, code)
        self.status_code = status_code

    def __str__(self) -> str:
        return f"[{self.status_code}] {self.message}"


class RobleFormatError(RobleError):
    """La respuesta no tiene la forma esperada."""


class RobleAuthError(RobleError):
    """No hay sesión, o el refresco del token falló."""


class RoblePartialInsertError(RobleError):
    """El servidor aceptó la petición pero rechazó parte de los registros.

    Solo la lanza ``create_many(..., strict=True)``. Conserva el resultado
    completo en :attr:`result` para poder saber **qué sí se escribió**, algo
    necesario si hay que deshacer la operación.
    """

    def __init__(self, result: InsertResult) -> None:
        total = len(result.inserted) + len(result.skipped)
        detalle = "; ".join(f"fila {s.index} ({s.reason})" for s in result.skipped)
        super().__init__(
            f"El servidor rechazó {len(result.skipped)} de {total} registros: {detalle}"
        )
        self.result = result
