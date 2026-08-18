"""Cliente Python para la plataforma ROBLE de Uninorte OpenLab.

Ejemplo::

    from roble import RobleClient

    db = RobleClient(
        base_url="https://roble-api.test-openlab.uninorte.edu.co",
        contract_id="mi_contrato_ab12",
    )
    user = db.login(email="ana@correo.com", password="MiClave!1")
    print(user.name)
"""

from .client import RobleClient
from .errors import (
    RobleAuthError,
    RobleError,
    RobleFormatError,
    RobleHttpError,
    RobleNetworkError,
    RoblePartialInsertError,
    RobleTimeoutError,
)
from .models import InsertResult, QueryResult, SkippedRecord, User
from .storage import FileStorage, MemoryStorage, TokenStorage

__version__ = "0.1.0"

__all__ = [
    "RobleClient",
    "RobleError",
    "RobleNetworkError",
    "RobleTimeoutError",
    "RobleHttpError",
    "RobleFormatError",
    "RobleAuthError",
    "RoblePartialInsertError",
    "InsertResult",
    "SkippedRecord",
    "QueryResult",
    "User",
    "TokenStorage",
    "MemoryStorage",
    "FileStorage",
    "__version__",
]
