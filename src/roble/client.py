"""Cliente HTTP de la plataforma Roble."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import requests

from .errors import (
    RobleAuthError,
    RobleError,
    RobleFormatError,
    RobleHttpError,
    RobleNetworkError,
    RoblePartialInsertError,
    RobleTimeoutError,
)
from .models import InsertResult, QueryResult, User
from .storage import MemoryStorage, TokenStorage

__all__ = ["RobleClient"]

_PLACEHOLDERS = {"tu_contrato", "mi_contrato", "your_contract"}


class RobleClient:
    """Cliente de Roble: autenticación y CRUD sobre PostgreSQL.

    Los tokens **no se exponen**: el cliente los guarda, los adjunta a cada
    petición, los renueva ante un ``401`` y los borra al cerrar sesión. Lo
    único que se consulta desde fuera es :attr:`is_logged_in`.

    Ejemplo::

        db = RobleClient(
            base_url="https://roble-api.test-openlab.uninorte.edu.co",
            contract_id="mi_contrato_ab12",
        )
        user = db.login(email="ana@correo.com", password="MiClave!1")
        print(user.name, user.user_id)

    Args:
        base_url: Host de la API. Una barra final se ignora.
        contract_id: Identificador del proyecto en la consola de Roble.
        storage: Dónde persistir la sesión. Por defecto solo memoria; usa
            :class:`~roble.storage.FileStorage` para que sobreviva entre
            ejecuciones.
        timeout: Segundos máximos por petición.
        session: ``requests.Session`` propia, útil en pruebas.

    Raises:
        ValueError: Si ``base_url`` no es una URL, o si ``contract_id`` está
            vacío o sigue siendo un valor de ejemplo.
    """

    DEFAULT_TIMEOUT = 30.0

    def __init__(
        self,
        *,
        base_url: str,
        contract_id: str,
        storage: TokenStorage | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
    ) -> None:
        # Fallar aquí, y no con un 500 críptico en la primera petición.
        if not base_url or not base_url.startswith("http"):
            raise ValueError(
                f"base_url inválida: {base_url!r}. Debe empezar por http:// o https://"
            )

        cid = (contract_id or "").strip()
        if not cid:
            raise ValueError(
                "contract_id no puede estar vacío. Es el identificador del "
                "proyecto en la consola de Roble, algo como "
                '"miproyecto_ab12cd34ef"'
            )
        if cid in _PLACEHOLDERS or " " in cid:
            raise ValueError(
                f"contract_id {contract_id!r} no parece un contrato real. "
                "Cópialo de la consola de Roble"
            )

        host = base_url.rstrip("/")
        self.contract_id = cid
        self.auth_url = f"{host}/auth/{cid}"
        self.data_url = f"{host}/database/{cid}"
        self.timeout = timeout
        self.storage: TokenStorage = storage if storage is not None else MemoryStorage()

        self._session = session or requests.Session()
        self._storage_key = f"roble.session.{cid}"
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._persist_tokens = True

    # ------------------------------------------------------------------
    # Sesión
    # ------------------------------------------------------------------

    @property
    def is_logged_in(self) -> bool:
        """``True`` si hay una sesión iniciada en este cliente.

        No dice si el servidor la sigue aceptando: para eso está
        :meth:`restore_session`.
        """
        return bool(self._access_token)

    def restore_session(self, *, verify: bool = True) -> bool:
        """Restaura la sesión guardada y comprueba que siga siendo válida.

        Llámalo al arrancar, antes de usar nada que requiera sesión.

        Args:
            verify: Si es ``True`` renueva el access token contra el servidor,
                así que un ``True`` significa que la sesión sirve de verdad.
                Con ``False`` solo lee el almacenamiento: más rápido, pero la
                sesión puede estar caducada.

        Returns:
            ``True`` si la sesión sirve. ``False`` si no había nada guardado o
            el refresh token ya no vale, en cuyo caso limpia la sesión.

        Raises:
            RobleNetworkError: Sin conexión. **No borra la sesión**, para poder
                distinguir "sesión caducada" de "sin conexión".
            RobleTimeoutError: Ídem.
        """
        if not self._refresh_token:
            self._load_stored_session()
        if not self._refresh_token:
            return False

        # Si la sesión venía del almacén, se sigue persistiendo.
        self._persist_tokens = True

        if not verify:
            return True

        # Renovar es la única forma de saber si el refresh token sigue vivo.
        try:
            self._refresh_access_token()
            return True
        except (RobleNetworkError, RobleTimeoutError):
            raise
        except RobleError:
            self._clear_tokens()
            return False

    def _update_access_token(self, token: str | None) -> None:
        self._access_token = token
        # Único punto por el que pasan login, refresco, logout y restauración.
        self._persist_session()

    def _clear_tokens(self) -> None:
        self._refresh_token = None
        self._update_access_token(None)

    def _forget_stored_session(self) -> None:
        try:
            self.storage.remove_item(self._storage_key)
        except Exception:  # noqa: BLE001 - el almacén nunca rompe la petición
            pass

    def _load_stored_session(self) -> None:
        try:
            raw = self.storage.get_item(self._storage_key)
            if not raw:
                return
            data = json.loads(raw)
            access, refresh = data.get("accessToken"), data.get("refreshToken")
            if not access or not refresh:
                return
            self._refresh_token = refresh
            self._update_access_token(access)
        except Exception:  # noqa: BLE001 - sesión corrupta: se empieza de cero
            pass

    def _persist_session(self) -> None:
        try:
            if self._access_token and self._refresh_token:
                if not self._persist_tokens:
                    return  # la sesión vive solo en memoria
                self.storage.set_item(
                    self._storage_key,
                    json.dumps(
                        {
                            "accessToken": self._access_token,
                            "refreshToken": self._refresh_token,
                        }
                    ),
                )
            else:
                # Al cerrar sesión se limpia siempre.
                self.storage.remove_item(self._storage_key)
        except Exception:  # noqa: BLE001 - el almacén nunca rompe la petición
            pass

    # ------------------------------------------------------------------
    # Transporte
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        body: Any = None,
        params: Mapping[str, Any] | None = None,
        is_auth: bool = False,
        skip_auth: bool = False,
        _retry: bool = True,
    ) -> Any:
        base = self.auth_url if is_auth else self.data_url
        url = f"{base}/{endpoint}" if endpoint else base

        headers = {"Content-Type": "application/json"}
        if not skip_auth and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        try:
            response = self._session.request(
                method,
                url,
                headers=headers,
                params=params,
                data=json.dumps(body) if body is not None else None,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise RobleTimeoutError("Tiempo de espera agotado") from exc
        except requests.RequestException as exc:
            raise RobleNetworkError("Sin conexión a internet") from exc

        if 200 <= response.status_code < 300:
            if not response.content:
                return None
            try:
                return response.json()
            except ValueError:
                return response.text

        # 401 en datos: refrescamos y reintentamos una sola vez.
        if (
            response.status_code == 401
            and _retry
            and not is_auth
            and not skip_auth
            and self._refresh_token
        ):
            try:
                self._refresh_access_token()
            except RobleError as exc:
                raise RobleAuthError(
                    f"Token expirado y no se pudo refrescar: {exc}"
                ) from exc
            return self._request(
                method,
                endpoint,
                body=body,
                params=params,
                is_auth=is_auth,
                skip_auth=skip_auth,
                _retry=False,
            )

        raise RobleHttpError(
            response.status_code, self._error_message(response, is_auth)
        )

    def _error_message(self, response: requests.Response, is_auth: bool) -> str:
        if not response.content:
            message = "El servidor respondió sin cuerpo"
        else:
            try:
                data = response.json()
                detail = (
                    data.get("message") or data.get("error")
                    if isinstance(data, dict)
                    else None
                )
                message = str(detail) if detail else response.text
            except ValueError:
                message = response.text

        # Un 500 en autenticación es lo que devuelve Roble cuando el contrato
        # no existe; sin esta pista el mensaje no ayuda a diagnosticarlo.
        if is_auth and response.status_code == 500:
            message += f" — revisa que el contract_id sea correcto ({self.contract_id})"
        return message

    # ------------------------------------------------------------------
    # Autenticación
    # ------------------------------------------------------------------

    def register(
        self,
        *,
        email: str,
        password: str,
        name: str,
        extra: dict[str, Any] | None = None,
        auto_login: bool = False,
        persist_session: bool = True,
    ) -> Any:
        """Registra un usuario sin verificación por correo.

        La cuenta queda activa de inmediato (``POST /signup-direct``).

        Args:
            email: Correo del usuario.
            password: Mínimo 8 caracteres, con mayúscula, minúscula, número y
                un símbolo de ``! @ # $ _ - .``
            name: Nombre visible.
            extra: Campos adicionales que el backend guarda con el usuario y
                devuelve luego en :meth:`login` y :meth:`current_user`.
            auto_login: Si es ``True``, inicia sesión al terminar el registro.
            persist_session: Solo se aplica con ``auto_login``. Igual que en
                :meth:`login`.

        Returns:
            Con ``auto_login=False``, el mensaje del servidor
            (``{"message": ...}``). Con ``auto_login=True``, el :class:`User`,
            lo mismo que devuelve :meth:`login`.

        Raises:
            RobleHttpError: ``400`` si el correo ya existe o la contraseña no
                cumple las reglas; ``500`` si el registro falla en el servidor.

        Note:
            Si el registro funciona pero el login automático falla, la cuenta
            **ya está creada**: el error se propaga y :attr:`is_logged_in`
            sigue en ``False``, así que basta con reintentar :meth:`login`.
        """
        body: dict[str, Any] = {
            "email": email,
            "password": password,
            "name": name,
        }
        if extra is not None:
            body["extra"] = extra

        result = self._request("POST", "signup-direct", body=body, is_auth=True)

        if auto_login:
            return self.login(
                email=email, password=password, persist_session=persist_session
            )
        return result

    def register_with_verification(
        self,
        *,
        email: str,
        password: str,
        name: str,
        extra: dict[str, Any] | None = None,
    ) -> Any:
        """Registra un usuario y envía un código de 6 dígitos por correo.

        ``POST /signup``. La cuenta no queda activa hasta llamar a
        :meth:`verify_email`, por eso este método no admite ``auto_login``.
        """
        body: dict[str, Any] = {
            "email": email,
            "password": password,
            "name": name,
        }
        if extra is not None:
            body["extra"] = extra
        return self._request("POST", "signup", body=body, is_auth=True)

    def verify_email(self, *, email: str, code: str) -> Any:
        """Confirma el correo con el código recibido (``POST /verify-email``).

        Raises:
            RobleHttpError: ``400`` si el código es inválido o expiró.
        """
        return self._request(
            "POST",
            "verify-email",
            body={"email": email, "code": code},
            is_auth=True,
        )

    def resend_code(self, *, email: str) -> Any:
        """Reenvía el código de verificación (``POST /resend-code``)."""
        return self._request("POST", "resend-code", body={"email": email}, is_auth=True)

    def login(self, *, email: str, password: str, persist_session: bool = True) -> User:
        """Inicia sesión y devuelve el perfil del usuario.

        Hace ``POST /login`` y, con el token ya guardado, ``GET /me``.

        Args:
            email: Correo.
            password: Contraseña.
            persist_session: Si la sesión debe sobrevivir al proceso. Es el
                clásico "recordarme". Con ``False`` vive solo en memoria y
                **borra además la sesión guardada antes**, para no dejar una
                sesión anterior recuperable.

        Returns:
            El :class:`User` autenticado.

        Raises:
            RobleHttpError: ``401`` si las credenciales no son correctas.

        Note:
            Si ``/login`` funciona pero ``/me`` falla, la sesión **sigue
            activa**: el error se propaga pero :attr:`is_logged_in` ya es
            ``True``, así que se puede distinguir un fallo de credenciales de
            uno de perfil y reintentar con :meth:`current_user`.
        """
        data = self._request(
            "POST",
            "login",
            body={"email": email, "password": password},
            is_auth=True,
        )

        self._persist_tokens = persist_session
        if not persist_session:
            self._forget_stored_session()

        if isinstance(data, dict):
            self._refresh_token = data.get("refreshToken")
            self._update_access_token(data.get("accessToken"))

        return self.current_user()

    def current_user(self) -> User:
        """Perfil del usuario autenticado (``GET /me``).

        Raises:
            RobleHttpError: ``401`` si no hay sesión válida.
        """
        data = self._request("GET", "me", is_auth=True)
        if not isinstance(data, dict):
            raise RobleFormatError("Respuesta inesperada al obtener el usuario")
        return User.from_json(data)

    def logout(self) -> None:
        """Cierra la sesión en el servidor y borra los tokens.

        Raises:
            RobleAuthError: Si no hay sesión activa.
        """
        if not self.is_logged_in:
            raise RobleAuthError("No hay token activo para cerrar sesión")
        self._request("POST", "logout", is_auth=True)
        self._clear_tokens()

    def forgot_password(self, *, email: str) -> Any:
        """Envía el correo de restablecimiento (``POST /forgot-password``)."""
        return self._request(
            "POST", "forgot-password", body={"email": email}, is_auth=True
        )

    def reset_password(self, *, token: str, new_password: str) -> Any:
        """Restablece la contraseña con el token del correo.

        ``POST /reset-password``.

        Raises:
            RobleHttpError: ``400`` si el token es inválido o expiró.
        """
        return self._request(
            "POST",
            "reset-password",
            body={"token": token, "newPassword": new_password},
            is_auth=True,
        )

    def delete_account(self) -> None:
        """Elimina la cuenta autenticada de forma permanente.

        ``DELETE /account``. **No se puede deshacer**: pide confirmación antes
        de llamarla.

        Raises:
            RobleAuthError: Si no hay sesión activa.
        """
        if not self.is_logged_in:
            raise RobleAuthError("No hay sesión activa para eliminar la cuenta")
        self._request("DELETE", "account", is_auth=True)
        self._clear_tokens()

    def _refresh_access_token(self) -> None:
        if not self._refresh_token:
            raise RobleAuthError("No hay refresh token disponible")

        data = self._request(
            "POST",
            "refresh-token",
            body={"refreshToken": self._refresh_token},
            is_auth=True,
        )
        if not isinstance(data, dict) or not data.get("accessToken"):
            raise RobleAuthError("Respuesta inválida al refrescar el token")

        # Hoy el servidor solo devuelve accessToken, pero si algún día rota el
        # refresh token no hay que perderlo.
        if data.get("refreshToken"):
            self._refresh_token = data["refreshToken"]
        self._update_access_token(data["accessToken"])

    # ------------------------------------------------------------------
    # Datos
    # ------------------------------------------------------------------

    def create(self, table: str, data: dict[str, Any]) -> dict[str, Any]:
        """Inserta un registro y devuelve la fila creada, con su ``_id``.

        ``POST /insert-one``.

        Raises:
            RobleHttpError: ``400`` si algún campo no existe en la tabla;
                ``500`` si la tabla no existe.
        """
        result = self._request(
            "POST", "insert-one", body={"tableName": table, "record": data}
        )
        if not isinstance(result, dict):
            raise RobleFormatError("No se pudo insertar el registro")
        return result

    def create_many(
        self,
        table: str,
        records: Sequence[dict[str, Any]],
        *,
        strict: bool = False,
    ) -> InsertResult:
        """Inserta varios registros (``POST /insert``).

        El servidor responde ``200`` aunque rechace parte de los registros, así
        que el resultado expone :attr:`~roble.models.InsertResult.skipped`.

        Args:
            table: Nombre de la tabla.
            records: Filas a insertar.
            strict: Si es ``True``, un rechazo parcial deja de ser algo que
                haya que recordar mirar y se convierte en un error.

        Raises:
            RoblePartialInsertError: Con ``strict=True`` y filas rechazadas. La
                excepción conserva el resultado completo, así que se sabe qué
                sí llegó a escribirse.
        """
        raw = self._request(
            "POST",
            "insert",
            body={"tableName": table, "records": list(records)},
        )
        if not isinstance(raw, dict):
            raise RobleFormatError("Respuesta inesperada al insertar registros")

        result = InsertResult.from_json(raw)
        if strict and result.has_skipped:
            raise RoblePartialInsertError(result)
        return result

    def read(
        self, table: str, filters: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Lee registros de una tabla (``GET /read``).

        Cada entrada de ``filters`` viaja como query param y **solo admite
        igualdad**: no hay ``LIKE``, rangos, orden ni paginación. Para eso está
        :meth:`execute_query`.

        Raises:
            RobleHttpError: ``400`` si la tabla o una columna no existen.
        """
        params: dict[str, Any] = {"tableName": table}
        if filters:
            params.update({k: str(v) for k, v in filters.items()})

        result = self._request("GET", "read", params=params)
        return self._as_rows(result)

    def get_by_id(self, table: str, record_id: Any) -> dict[str, Any] | None:
        """Devuelve el registro con ese ``_id``, o ``None`` si no existe."""
        rows = self.read(table, {"_id": record_id})
        return rows[0] if rows else None

    def update(
        self, table: str, record_id: Any, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Actualiza el registro cuyo ``_id`` coincida (``PUT /update``).

        Las claves ``_id`` e ``id`` se eliminan del cuerpo automáticamente.

        Raises:
            RobleHttpError: ``404`` si el registro no existe.
        """
        updates = {k: v for k, v in data.items() if k not in ("_id", "id")}
        result = self._request(
            "PUT",
            "update",
            body={
                "tableName": table,
                "idColumn": "_id",
                "idValue": record_id,
                "updates": updates,
            },
        )
        return result if isinstance(result, dict) else {}

    def delete(self, table: str, record_id: Any) -> dict[str, Any]:
        """Elimina el registro cuyo ``_id`` coincida (``DELETE /delete``)."""
        result = self._request(
            "DELETE",
            "delete",
            body={"tableName": table, "idColumn": "_id", "idValue": record_id},
        )
        return result if isinstance(result, dict) else {}

    def public_read(
        self, table: str, filters: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Lee una tabla marcada como pública, **sin autenticación**.

        ``GET /public-read``.

        Raises:
            RobleHttpError: ``403`` si la tabla no está configurada como
                pública en la consola. Es configuración de la tabla, no un
                problema de token.
        """
        params: dict[str, Any] = {"tableName": table}
        if filters:
            params.update({k: str(v) for k, v in filters.items()})

        result = self._request("GET", "public-read", params=params, skip_auth=True)
        return self._as_rows(result)

    def execute_query(
        self, query_id: str, params: Sequence[Any] | None = None
    ) -> QueryResult:
        """Ejecuta una consulta guardada en la consola de Roble.

        ``POST /execute-query``. Es la vía para joins, agregados, orden y
        paginación, que :meth:`read` no admite.
        """
        body: dict[str, Any] = {"id": query_id}
        if params is not None:
            body["params"] = list(params)

        raw = self._request("POST", "execute-query", body=body)
        if not isinstance(raw, dict):
            raise RobleFormatError("Respuesta inesperada al ejecutar la consulta")
        return QueryResult.from_json(raw)

    @staticmethod
    def _as_rows(result: Any) -> list[dict[str, Any]]:
        if isinstance(result, list):
            return [r for r in result if isinstance(r, dict)]
        if isinstance(result, dict) and isinstance(result.get("data"), list):
            return [r for r in result["data"] if isinstance(r, dict)]
        return []

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Cierra la sesión HTTP subyacente."""
        self._session.close()

    def __enter__(self) -> RobleClient:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        estado = "con sesión" if self.is_logged_in else "sin sesión"
        return f"<RobleClient {self.contract_id} ({estado})>"
