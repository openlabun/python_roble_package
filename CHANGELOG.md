# Changelog

## 0.1.0

Primera versión. Cliente Python para ROBLE, con la misma superficie pública que
el paquete Dart/Flutter `roble` y el de JS/TS `roble-client`, adaptada a las
convenciones de Python: `snake_case`, argumentos por palabra clave y excepciones
terminadas en `Error`.

### Añadido

- **`RobleClient`**, síncrono sobre `requests`. Se configura con `base_url` y
  `contract_id`, y valida ambos al construir en lugar de fallar con un `500`
  críptico en la primera petición.
- **Autenticación** (10 métodos): `register()`, `register_with_verification()`,
  `verify_email()`, `resend_code()`, `login()`, `current_user()`, `logout()`,
  `forgot_password()`, `reset_password()` y `delete_account()`.
  `login()` y `current_user()` devuelven el perfil del usuario (`GET /me`),
  incluido el `extra` del registro.
- **Datos** (8 métodos): `create()`, `create_many()`, `read()`, `get_by_id()`,
  `update()`, `delete()`, `public_read()` y `execute_query()`.
- **La sesión no es manipulable desde fuera.** No hay `access_token`,
  `refresh_token` ni forma de fijarlos: el cliente los guarda, los adjunta, los
  renueva ante un `401` y los borra al cerrar sesión. Lo único que se consulta
  es `is_logged_in`.
- **`restore_session(verify=True)`** para arrancar la aplicación: carga la
  sesión guardada y comprueba contra el servidor que siga viva. Si el refresh
  token caducó, limpia y devuelve `False`; un fallo de red se propaga en lugar
  de borrarla.
- **Persistencia opcional** vía el `Protocol` `TokenStorage`. Por defecto
  `MemoryStorage` —un script no debería escribir tokens en disco sin pedirlo—,
  con `FileStorage` como alternativa: escritura atómica, permisos `0600` y ruta
  por plataforma.
- **`register(auto_login=True)`** inicia sesión al terminar y devuelve el
  perfil. `register_with_verification` no lo admite: hasta validar el código del
  correo la cuenta no puede entrar.
- **`login(persist_session=False)`** mantiene la sesión solo en memoria y borra
  la que hubiera guardada, para no dejar una sesión anterior recuperable.
- **`create_many(strict=True)`** lanza `RoblePartialInsertError` si el servidor
  rechaza alguna fila. La excepción conserva el resultado completo, así que se
  sabe qué sí llegó a escribirse.
- **Jerarquía de errores** bajo `RobleError`: `RobleNetworkError`,
  `RobleTimeoutError`, `RobleHttpError` (con `status_code`), `RobleFormatError`,
  `RobleAuthError` y `RoblePartialInsertError`.
- **Pista en el `500` de autenticación**: es lo que devuelve Roble cuando el
  contrato no existe, así que el mensaje lo sugiere.
- Modelos tipados `User`, `InsertResult`, `SkippedRecord` y `QueryResult`, y
  marcador `py.typed`.

### Todavía no

- **Realtime.** Existe en el backend, pero aún no en este paquete, igual que en
  los otros dos.
