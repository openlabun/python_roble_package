"""Demo de `roble` contra un proyecto real.

    python examples/demo.py

Sin credenciales hace una comprobación offline. Con credenciales ejecuta el
ciclo completo: registro, login, CRUD e inserción múltiple.

Variables de entorno:
    ROBLE_CONTRACT_ID   obligatoria
    ROBLE_EMAIL         obligatoria
    ROBLE_PASSWORD      obligatoria
    ROBLE_BASE_URL      opcional
    ROBLE_TABLE         opcional (por defecto "usuarios_test")
"""

from __future__ import annotations

import os
import sys

from roble import (
    MemoryStorage,
    RobleClient,
    RobleError,
    RobleHttpError,
    RoblePartialInsertError,
)

BASE_URL = os.environ.get(
    "ROBLE_BASE_URL", "https://roble-api.test-openlab.uninorte.edu.co"
)
CONTRACT_ID = os.environ.get("ROBLE_CONTRACT_ID")
EMAIL = os.environ.get("ROBLE_EMAIL")
PASSWORD = os.environ.get("ROBLE_PASSWORD")
TABLE = os.environ.get("ROBLE_TABLE", "usuarios_test")


def comprobacion_offline() -> None:
    print("Sin credenciales: comprobación offline.\n")

    # La configuración se valida al construir el cliente.
    try:
        RobleClient(base_url=BASE_URL, contract_id="tu_contrato")
    except ValueError as exc:
        print(f"  contrato sin configurar -> {exc}")

    err = RobleHttpError(401, "No autorizado")
    print(f"  errores                 -> {err}")
    print(f"  hereda de RobleError    -> {isinstance(err, RobleError)}")

    print("\nPara el ciclo completo define ROBLE_CONTRACT_ID, ROBLE_EMAIL y")
    print("ROBLE_PASSWORD.")


def ciclo_completo() -> None:
    # Sin `storage` la sesión vive solo en memoria; MemoryStorage explícito
    # deja claro que aquí no se escribe nada en disco.
    with RobleClient(
        base_url=BASE_URL,
        contract_id=CONTRACT_ID,  # type: ignore[arg-type]
        storage=MemoryStorage(),
    ) as db:
        print(f"Contrato : {CONTRACT_ID}")
        print(f"Tabla    : {TABLE}\n")

        user = db.login(email=EMAIL, password=PASSWORD)  # type: ignore[arg-type]
        print(f"Dentro como {user.name} ({user.user_id})")
        print(f"  extra      : {user.extra}")
        print(f"  is_logged_in: {db.is_logged_in}\n")

        try:
            crud(db)
            insercion_multiple(db)
        except RobleError as exc:
            print(f"\n(datos omitidos: {exc})")
            print(f'Crea la tabla "{TABLE}" o define ROBLE_TABLE.')

        db.logout()
        print(f"\nSesión cerrada. is_logged_in: {db.is_logged_in}")


def crud(db: RobleClient) -> None:
    print("=== CRUD ===\n")

    creado = db.create(TABLE, {"nombre": "Ana", "rol": "admin"})
    print(f"  creado   : {creado['_id']}")

    filas = db.read(TABLE)
    print(f"  leídos   : {len(filas)} registros")

    db.update(TABLE, creado["_id"], {"rol": "editor"})
    uno = db.get_by_id(TABLE, creado["_id"])
    print(f"  get_by_id: {uno['rol'] if uno else None}")

    db.delete(TABLE, creado["_id"])
    print("  eliminado")


def insercion_multiple(db: RobleClient) -> None:
    print("\n=== Inserción múltiple ===\n")

    # strict convierte el rechazo parcial en un error, en vez de algo que hay
    # que acordarse de comprobar.
    try:
        db.create_many(
            TABLE,
            [{"nombre": "Uno"}, {"columna_inexistente": 1}],
            strict=True,
        )
    except RoblePartialInsertError as exc:
        print(f"  rechazo parcial: {exc.message}")
        print(f"  sí se escribió : {len(exc.result.inserted)} fila(s)")
        for fila in exc.result.inserted:
            db.delete(TABLE, fila["_id"])
        print("  (limpiadas)")


def main() -> int:
    if not (CONTRACT_ID and EMAIL and PASSWORD):
        comprobacion_offline()
        return 0

    try:
        ciclo_completo()
    except RobleError as exc:
        print(f"\nError de roble: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
