"""Dónde persistir la sesión entre ejecuciones.

Por defecto el paquete **no escribe nada en disco**: la sesión vive en memoria
y se pierde al terminar el proceso. Es lo correcto en un servidor, donde dejar
el refresh token en el disco compartido sería un problema.

En un script o una CLI, donde sí interesa no reautenticarse en cada ejecución,
basta con activar :class:`FileStorage`.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = ["TokenStorage", "MemoryStorage", "FileStorage"]


@runtime_checkable
class TokenStorage(Protocol):
    """Almacén de la sesión. Tres métodos, nada más."""

    def get_item(self, key: str) -> str | None: ...

    def set_item(self, key: str, value: str) -> None: ...

    def remove_item(self, key: str) -> None: ...


class MemoryStorage:
    """Guarda la sesión en un diccionario. Es el almacén por defecto."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get_item(self, key: str) -> str | None:
        return self._values.get(key)

    def set_item(self, key: str, value: str) -> None:
        self._values[key] = value

    def remove_item(self, key: str) -> None:
        self._values.pop(key, None)


class FileStorage:
    """Guarda la sesión en un fichero JSON de la carpeta de config del usuario.

    ``~/.config/roble/session.json`` en Linux y macOS, ``%APPDATA%\roble`` en
    Windows. El fichero se crea con permisos de solo-propietario donde el
    sistema lo permite.

    ⚠️ El refresh token queda **en texto plano**. Úsalo en tu máquina, no en un
    servidor compartido.

    ```python
    db = RobleClient(base_url=..., contract_id=..., storage=FileStorage())
    ```
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self._default_path()

    @staticmethod
    def _default_path() -> Path:
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        return base / "roble" / "session.json"

    def _read(self) -> dict[str, str]:
        try:
            with self.path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            # Fichero ausente o corrupto: se empieza de cero.
            return {}

    def _write(self, values: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Escritura atómica: un fallo a medias no deja la sesión corrupta.
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(values, fh)
            os.replace(tmp, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass  # Windows y algunos sistemas de ficheros no lo admiten.
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def get_item(self, key: str) -> str | None:
        return self._read().get(key)

    def set_item(self, key: str, value: str) -> None:
        values = self._read()
        values[key] = value
        self._write(values)

    def remove_item(self, key: str) -> None:
        values = self._read()
        if values.pop(key, None) is not None:
            self._write(values)
