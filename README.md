# roble

Cliente Python para la plataforma [ROBLE](https://roble.openlab.uninorte.edu.co)
de Uninorte OpenLab: autenticación y CRUD sobre PostgreSQL.

Es el equivalente en Python de los paquetes
[`roble`](https://pub.dev/packages/roble) (Dart/Flutter) y
[`roble-client`](https://www.npmjs.com/package/roble-client) (JS/TS): la misma
superficie pública, con nombres idiomáticos de Python (`snake_case`, argumentos
por palabra clave, excepciones terminadas en `Error`).

- Síncrono, sobre `requests`. Sin `async`.
- Los tokens **no se exponen**: el cliente los guarda, los adjunta, los renueva
  ante un `401` y los borra al cerrar sesión.
- Tipado completo (`py.typed`), sin dependencias más allá de `requests`.

## Instalación

```bash
pip install roble
```

Requiere Python 3.10 o superior.

## Empezar

```python
from roble import RobleClient

db = RobleClient(
    base_url="https://roble-api.test-openlab.uninorte.edu.co",
    contract_id="miproyecto_ab12cd34ef",
)

user = db.login(email="ana@correo.com", password="MiClave!1")
print(user.name, user.user_id)

filas = db.read("tareas", {"completada": False})
db.create("tareas", {"titulo": "Escribir el informe"})
```

El `contract_id` es el identificador del proyecto en la consola de Roble. Es el
único dato que cambia entre proyectos: la librería compone con él tanto
`/auth/{contract_id}` como `/database/{contract_id}`.

### Constructor

```python
RobleClient(
    *,
    base_url: str,
    contract_id: str,
    storage: TokenStorage | None = None,
    timeout: float = 30.0,
    session: requests.Session | None = None,
)
```

| Parámetro | Descripción |
| --- | --- |
| `base_url` | Host de la API. Una barra final se ignora. |
| `contract_id` | Identificador del proyecto en la consola de Roble. |
| `storage` | Dónde persistir la sesión. Por defecto solo memoria. |
| `timeout` | Segundos máximos por petición. |
| `session` | `requests.Session` propia, útil en pruebas. |

Todos los argumentos son **por palabra clave**. La configuración se valida al
construir, no en la primera petición:

```python
RobleClient(base_url="roble", contract_id="abc")
# ValueError: base_url inválida: 'roble'. Debe empezar por http:// o https://

RobleClient(base_url=BASE, contract_id="tu_contrato")
# ValueError: contract_id 'tu_contrato' no parece un contrato real.
#             Cópialo de la consola de Roble
```

`RobleClient` sirve como gestor de contexto y cierra la sesión HTTP al salir:

```python
with RobleClient(base_url=BASE, contract_id=CID) as db:
    ...
```

---

## Sesión

### `is_logged_in -> bool`

`True` si hay una sesión iniciada **en este cliente**. No dice si el servidor la
sigue aceptando; para eso está `restore_session()`.

### `restore_session(*, verify=True) -> bool`

Recupera la sesión guardada por `storage`. Es lo que se llama al arrancar la
aplicación.

| Parámetro | Descripción |
| --- | --- |
| `verify` | Con `True` (por defecto) renueva el access token contra el servidor, así que el `True` que devuelve significa que la sesión sigue viva. Con `False` solo lee el almacenamiento. |

**Devuelve** `True` si quedó una sesión utilizable.

Si el refresh token caducó, limpia la sesión y devuelve `False`. Un fallo de red
**se propaga** en vez de borrarla: no se pierde la sesión por estar sin
cobertura.

```python
db = RobleClient(base_url=BASE, contract_id=CID, storage=FileStorage())

if db.restore_session():
    print("de vuelta como", db.current_user().name)
else:
    db.login(email=..., password=...)
```

### Persistencia

Por defecto la sesión vive **solo en memoria**: se pierde al terminar el
proceso. Es lo razonable para un script o un servidor, donde escribir tokens en
disco sin pedirlo sería una sorpresa desagradable.

Para conservarla entre ejecuciones (una CLI, una app de escritorio):

```python
from roble import FileStorage, RobleClient

db = RobleClient(base_url=BASE, contract_id=CID, storage=FileStorage())
```

`FileStorage` escribe en `~/.config/roble/session.json` (en Windows, bajo
`%APPDATA%`) con permisos `0600` y escritura atómica. Acepta `path=` para elegir
otra ruta.

Cualquier objeto con `get_item`, `set_item` y `remove_item` sirve como
almacenamiento — es un `Protocol`, no hace falta heredar de nada:

```python
from roble import TokenStorage


class RedisStorage:
    def get_item(self, key: str) -> str | None: ...
    def set_item(self, key: str, value: str) -> None: ...
    def remove_item(self, key: str) -> None: ...


isinstance(RedisStorage(), TokenStorage)  # True
```

---

## Autenticación

### `register(*, email, password, name, extra=None, auto_login=False, persist_session=True)`

Registra un usuario **sin verificación por correo** (`POST /signup-direct`): la
cuenta queda activa de inmediato.

| Parámetro | Descripción |
| --- | --- |
| `email` | Correo del usuario. |
| `password` | Mínimo 8 caracteres, con mayúscula, minúscula, número y un símbolo de `! @ # $ _ - .` |
| `name` | Nombre visible. |
| `extra` | Campos adicionales que el backend guarda con el usuario y devuelve luego en `login()` y `current_user()`. |
| `auto_login` | Si es `True`, inicia sesión al terminar. |
| `persist_session` | Solo con `auto_login`. Igual que en `login()`. |

**Devuelve** el mensaje del servidor (`{"message": ...}`), o un `User` si
`auto_login=True`.

**Errores:** `RobleHttpError` `400` si el correo ya existe o la contraseña no
cumple las reglas; `500` si el registro falla en el servidor.

Si el registro funciona pero el login automático falla, la cuenta **ya está
creada**: el error se propaga, `is_logged_in` sigue en `False` y basta con
reintentar `login()`.

```python
user = db.register(
    email="ana@correo.com",
    password="MiClave!1",
    name="Ana",
    extra={"rol": "estudiante", "semestre": 5},
    auto_login=True,
)
print(user.extra)  # {'rol': 'estudiante', 'semestre': 5}
```

### `register_with_verification(*, email, password, name, extra=None)`

Igual, pero envía un código al correo (`POST /signup`). La cuenta no existe
hasta llamar a `verify_email()`. No admite `auto_login`: hasta validar el código
la cuenta no puede entrar.

### `verify_email(*, email, code)`

Confirma el código recibido y crea la cuenta.
**Errores:** `RobleHttpError` `400` si el código es incorrecto o caducó.

### `resend_code(*, email)`

Reenvía el código de verificación.

### `login(*, email, password, persist_session=True) -> User`

Inicia sesión (`POST /login`) y **devuelve el perfil del usuario**, no los
tokens.

| Parámetro | Descripción |
| --- | --- |
| `persist_session` | Con `False` la sesión vive solo en memoria y además **borra la que hubiera guardada**, para no dejar una sesión anterior recuperable. Se respeta también en los refrescos posteriores. |

**Errores:** `RobleHttpError` `401` con credenciales incorrectas; `500` cuando
el contrato no existe — el mensaje lo sugiere explícitamente:

```
Error inesperado al autenticar — revisa que el contract_id sea correcto (no_existe)
```

Si la llamada al perfil falla, la sesión **sigue activa**: el error se propaga
pero `is_logged_in` ya es `True`, así que se distingue un fallo de credenciales
de uno de perfil y se puede reintentar con `current_user()`.

### `current_user() -> User`

Devuelve el perfil del usuario en sesión (`GET /me`): `user_id`, `email`,
`name`, el `extra` del registro y las fechas. En `raw` queda la respuesta
completa del servidor.

**Errores:** `RobleAuthError` si no hay sesión; `RobleHttpError` `401` si el
token ya no vale y no se pudo renovar.

### `logout()`

Cierra la sesión en el servidor y borra los tokens, incluidos los guardados. No
falla si el servidor rechaza la petición: local siempre queda limpio.

### `forgot_password(*, email)`

Envía al correo un enlace de recuperación.

### `reset_password(*, token, new_password)`

Establece una contraseña nueva con el token del correo.
**Errores:** `RobleHttpError` `400` si el token caducó o la contraseña no cumple
las reglas.

### `delete_account()`

Borra la cuenta del usuario en sesión y limpia los tokens.
**Errores:** `RobleAuthError` si no hay sesión.

---

## Datos

### `create(table, data) -> dict`

Inserta un registro y devuelve la fila creada, con su `_id`
(`POST /insert-one`).

**Errores:** `RobleHttpError` `400` si algún campo no existe en la tabla; `500`
si la tabla no existe.

```python
fila = db.create("tareas", {"titulo": "Escribir el informe", "completada": False})
print(fila["_id"])
```

### `create_many(table, records, *, strict=False) -> InsertResult`

Inserta varios registros (`POST /insert`). El servidor responde `200` aunque
rechace parte de ellos, así que el resultado expone `skipped`.

| Parámetro | Descripción |
| --- | --- |
| `strict` | Con `True`, un rechazo parcial deja de ser algo que haya que recordar mirar y se convierte en un error. |

**Devuelve** un `InsertResult` con `inserted`, `skipped` y `has_skipped`.

**Errores:** `RoblePartialInsertError` con `strict=True` y filas rechazadas. La
excepción conserva el resultado completo en `.result`, así que se sabe qué sí
llegó a escribirse:

```
El servidor rechazó 1 de 2 registros: fila 1 (Columnas inválidas)
```

```python
from roble import RoblePartialInsertError

try:
    db.create_many("tareas", filas, strict=True)
except RoblePartialInsertError as exc:
    print(exc.message)
    for rechazada in exc.result.skipped:
        print(rechazada.index, rechazada.reason)
```

Sin `strict`, hay que comprobarlo a mano:

```python
res = db.create_many("tareas", filas)
if res.has_skipped:
    ...
```

### `read(table, filters=None) -> list[dict]`

Lee registros (`GET /read`). Cada entrada de `filters` viaja como query param y
**solo admite igualdad**: no hay `LIKE`, rangos, orden ni paginación. Para eso
está `execute_query()`.

**Errores:** `RobleHttpError` `400` si la tabla o una columna no existen.

```python
db.read("tareas")
db.read("tareas", {"completada": False, "asignada_a": user.user_id})
```

### `get_by_id(table, record_id) -> dict | None`

Devuelve el registro con ese `_id`, o `None` si no existe.

### `update(table, record_id, data) -> dict`

Actualiza el registro cuyo `_id` coincida (`PUT /update`). Las claves `_id` e
`id` se eliminan del cuerpo automáticamente, así que se puede pasar una fila
completa recién leída.

**Errores:** `RobleHttpError` `400` si algún campo no existe en la tabla.

### `delete(table, record_id) -> dict`

Elimina el registro cuyo `_id` coincida (`DELETE /delete`).

### `public_read(table, filters=None) -> list[dict]`

Lee una tabla marcada como pública, **sin autenticación** (`GET /public-read`).
Funciona sin haber iniciado sesión.

**Errores:** `RobleHttpError` `403` si la tabla no está configurada como pública
en la consola — es configuración de la tabla, no un problema de token.

### `execute_query(query_id, params=None) -> QueryResult`

Ejecuta una consulta **guardada en la consola de Roble**
(`POST /execute-query`). Es la vía para joins, agregados, orden y paginación,
que `read()` no admite.

| Parámetro | Descripción |
| --- | --- |
| `query_id` | UUID de la consulta, tal como aparece en la consola. No es SQL. |
| `params` | Parámetros posicionales de la consulta. |

**Errores:** `RobleHttpError` `500` con `invalid input syntax for type uuid` si
se pasa SQL en vez del identificador.

### `close()`

Cierra la sesión HTTP subyacente. Innecesario si se usa como gestor de contexto.

---

## Modelos

Todos son `dataclass` inmutables.

### `User`

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `user_id` | `str` | Identificador del usuario. |
| `email` | `str` | |
| `name` | `str` | |
| `extra` | `dict \| None` | Lo que se pasó en `extra` al registrarse. |
| `created_at`, `updated_at` | `str` | |
| `raw` | `dict` | La respuesta completa del servidor. |

### `InsertResult`

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `inserted` | `list[dict]` | Filas que sí se escribieron. |
| `skipped` | `list[SkippedRecord]` | Filas rechazadas. |
| `has_skipped` | `bool` | |

### `SkippedRecord`

`index` (posición en la lista enviada) y `reason` (motivo del servidor).

### `QueryResult`

`rows` y `raw`.

---

## Errores

Todos derivan de `RobleError`, que expone `message` y `code`.

| Excepción | Cuándo |
| --- | --- |
| `RobleError` | Base. Captúrala para tratar cualquier fallo de la librería. |
| `RobleNetworkError` | No hubo respuesta: sin red, DNS, conexión rechazada. |
| `RobleTimeoutError` | Se agotó `timeout`. |
| `RobleHttpError` | El servidor respondió con error. Trae `status_code`. |
| `RobleFormatError` | La respuesta no tenía la forma esperada. |
| `RobleAuthError` | Se necesitaba sesión y no la había. |
| `RoblePartialInsertError` | `create_many(strict=True)` con filas rechazadas. Trae `result`. |

```python
from roble import RobleError, RobleHttpError, RobleTimeoutError

try:
    db.read("tareas")
except RobleTimeoutError:
    ...  # reintentar
except RobleHttpError as exc:
    if exc.status_code == 403:
        ...  # permisos
    else:
        print(exc.message)
except RobleError as exc:
    print("fallo de roble:", exc)
```

Un `401` no llega aquí: la librería renueva el token y reintenta la petición una
vez. Solo se propaga si la renovación también falla.

---

## Qué no está

- **Realtime.** Existe en el backend, pero todavía no en este paquete.
- **Los tokens.** No hay `access_token`, `refresh_token`, `set_tokens()` ni
  `clear_tokens()`. Toda la lógica de autenticación es interna.

## Ejemplo

`examples/demo.py` ejecuta el ciclo completo contra un proyecto real:

```bash
export ROBLE_CONTRACT_ID=miproyecto_ab12cd34ef
export ROBLE_EMAIL=ana@correo.com
export ROBLE_PASSWORD='MiClave!1'
python examples/demo.py
```

Sin credenciales hace una comprobación offline.

## Desarrollo

```bash
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
mypy src
```

## Licencia

MIT
