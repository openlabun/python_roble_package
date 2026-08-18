"""Pruebas sin red: validación, sesión y formas de respuesta."""

from __future__ import annotations

import json
from typing import Any

import pytest
import requests

from roble import (
    InsertResult,
    MemoryStorage,
    RobleClient,
    RobleHttpError,
    RoblePartialInsertError,
    RobleTimeoutError,
)

BASE = "https://fake.test"
CID = "proyecto_ab12"


class FakeSession:
    """`requests.Session` de mentira: devuelve respuestas guionizadas."""

    def __init__(self, respuestas: list[dict[str, Any]]) -> None:
        self.respuestas = respuestas
        self.llamadas: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        self.llamadas.append({"method": method, "url": url, **kwargs})
        guion = self.respuestas.pop(0)

        if guion.get("raise"):
            raise guion["raise"]

        resp = requests.Response()
        resp.status_code = guion.get("status", 200)
        cuerpo = guion.get("json", {})
        resp._content = json.dumps(cuerpo).encode()
        return resp

    def close(self) -> None:  # pragma: no cover
        pass


def cliente(respuestas: list[dict[str, Any]], **kwargs: Any) -> RobleClient:
    return RobleClient(
        base_url=BASE,
        contract_id=CID,
        session=FakeSession(respuestas),  # type: ignore[arg-type]
        storage=kwargs.pop("storage", MemoryStorage()),
        **kwargs,
    )


PERFIL = {
    "id": "1",
    "userId": "u1",
    "email": "ana@correo.com",
    "name": "Ana",
    "extra": {"rol": "admin"},
    "createdAt": "2026-01-01",
    "updatedAt": "2026-01-02",
}
TOKENS = {"accessToken": "at", "refreshToken": "rt"}


class TestValidacion:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"base_url": "roble", "contract_id": "abc"},
            {"base_url": BASE, "contract_id": ""},
            {"base_url": BASE, "contract_id": "   "},
            {"base_url": BASE, "contract_id": "tu_contrato"},
            {"base_url": BASE, "contract_id": "con espacio"},
        ],
    )
    def test_configuracion_invalida(self, kwargs: dict[str, str]) -> None:
        with pytest.raises(ValueError):
            RobleClient(**kwargs)  # type: ignore[arg-type]

    def test_urls_compuestas(self) -> None:
        db = RobleClient(base_url=BASE + "/", contract_id=CID)
        assert db.auth_url == f"{BASE}/auth/{CID}"
        assert db.data_url == f"{BASE}/database/{CID}"


class TestSesion:
    def test_login_devuelve_perfil(self) -> None:
        db = cliente([{"json": TOKENS}, {"json": PERFIL}])
        user = db.login(email="ana@correo.com", password="x")

        assert user.user_id == "u1"
        assert user.name == "Ana"
        assert user.extra == {"rol": "admin"}
        assert db.is_logged_in

    def test_tokens_no_expuestos(self) -> None:
        db = cliente([])
        for nombre in ("access_token", "refresh_token", "set_tokens", "clear_tokens"):
            assert not hasattr(db, nombre)

    def test_persiste_y_restaura(self) -> None:
        disco = MemoryStorage()
        a = cliente([{"json": TOKENS}, {"json": PERFIL}], storage=disco)
        a.login(email="ana@correo.com", password="x")

        # Cliente nuevo, mismo almacén: refresco + perfil.
        b = cliente([{"json": {"accessToken": "at2"}}, {"json": PERFIL}], storage=disco)
        assert b.restore_session() is True
        assert b.is_logged_in

    def test_persist_session_false_borra_lo_guardado(self) -> None:
        disco = MemoryStorage()
        a = cliente([{"json": TOKENS}, {"json": PERFIL}], storage=disco)
        a.login(email="ana@correo.com", password="x")

        b = cliente([{"json": TOKENS}, {"json": PERFIL}], storage=disco)
        b.login(email="ana@correo.com", password="x", persist_session=False)

        assert b.is_logged_in, "sigue usable en memoria"
        c = cliente([], storage=disco)
        assert c.restore_session() is False, "no debe quedar nada recuperable"

    def test_restore_sin_sesion(self) -> None:
        assert cliente([]).restore_session() is False

    def test_restore_con_refresh_invalido_limpia(self) -> None:
        disco = MemoryStorage()
        disco.set_item(
            f"roble.session.{CID}",
            json.dumps({"accessToken": "viejo", "refreshToken": "malo"}),
        )
        db = cliente([{"status": 400, "json": {"message": "expirado"}}], storage=disco)

        assert db.restore_session() is False
        assert db.is_logged_in is False
        assert disco.get_item(f"roble.session.{CID}") is None

    def test_fallo_de_red_no_borra_la_sesion(self) -> None:
        disco = MemoryStorage()
        disco.set_item(
            f"roble.session.{CID}",
            json.dumps({"accessToken": "at", "refreshToken": "rt"}),
        )
        db = cliente([{"raise": requests.Timeout()}], storage=disco)

        with pytest.raises(RobleTimeoutError):
            db.restore_session()
        assert disco.get_item(f"roble.session.{CID}") is not None


class TestRegistro:
    def test_sin_auto_login(self) -> None:
        db = cliente([{"json": {"message": "Usuario registrado correctamente."}}])
        res = db.register(email="a@b.co", password="x", name="Ana")

        assert res["message"].startswith("Usuario registrado")
        assert db.is_logged_in is False

    def test_con_auto_login_devuelve_perfil(self) -> None:
        db = cliente([{"json": {"message": "ok"}}, {"json": TOKENS}, {"json": PERFIL}])
        user = db.register(email="a@b.co", password="x", name="Ana", auto_login=True)

        assert user.user_id == "u1"
        assert db.is_logged_in

    def test_extra_viaja_en_el_cuerpo(self) -> None:
        sesion = FakeSession([{"json": {"message": "ok"}}])
        db = RobleClient(
            base_url=BASE,
            contract_id=CID,
            session=sesion,  # type: ignore[arg-type]
        )
        db.register(
            email="a@b.co", password="x", name="Ana", extra={"rol": "estudiante"}
        )

        enviado = json.loads(sesion.llamadas[0]["data"])
        assert enviado["extra"] == {"rol": "estudiante"}


class TestDatos:
    def test_create_many_devuelve_rechazos(self) -> None:
        db = cliente(
            [
                {
                    "json": {
                        "inserted": [{"_id": "1"}],
                        "skipped": [{"index": 1, "reason": "Columnas inválidas"}],
                    }
                }
            ]
        )
        res = db.create_many("t", [{"a": 1}, {"b": 2}])

        assert isinstance(res, InsertResult)
        assert res.has_skipped
        assert res.skipped[0].index == 1

    def test_create_many_strict_lanza_y_conserva(self) -> None:
        db = cliente(
            [
                {
                    "json": {
                        "inserted": [{"_id": "1"}],
                        "skipped": [{"index": 1, "reason": "mal"}],
                    }
                }
            ]
        )
        with pytest.raises(RoblePartialInsertError) as exc:
            db.create_many("t", [{"a": 1}, {"b": 2}], strict=True)

        assert exc.value.result.inserted == [{"_id": "1"}]
        assert "1 de 2" in exc.value.message

    def test_update_quita_id_del_cuerpo(self) -> None:
        sesion = FakeSession([{"json": {}}])
        db = RobleClient(
            base_url=BASE,
            contract_id=CID,
            session=sesion,  # type: ignore[arg-type]
        )
        db.update("t", "abc", {"_id": "abc", "id": 1, "rol": "editor"})

        enviado = json.loads(sesion.llamadas[0]["data"])
        assert enviado["updates"] == {"rol": "editor"}

    def test_get_by_id_sin_resultados(self) -> None:
        assert cliente([{"json": []}]).get_by_id("t", "x") is None

    def test_public_read_no_manda_authorization(self) -> None:
        sesion = FakeSession([{"json": TOKENS}, {"json": PERFIL}, {"json": []}])
        db = RobleClient(
            base_url=BASE,
            contract_id=CID,
            session=sesion,  # type: ignore[arg-type]
        )
        db.login(email="a@b.co", password="x")
        db.public_read("t")

        assert "Authorization" not in sesion.llamadas[-1]["headers"]


class TestErrores:
    def test_pista_en_500_de_auth(self) -> None:
        db = cliente([{"status": 500, "json": {"message": "Error inesperado"}}])

        with pytest.raises(RobleHttpError) as exc:
            db.login(email="a@b.co", password="x")

        assert exc.value.status_code == 500
        assert "contract_id" in exc.value.message

    def test_401_refresca_y_reintenta_una_vez(self) -> None:
        disco = MemoryStorage()
        sesion = FakeSession(
            [
                {"json": TOKENS},
                {"json": PERFIL},
                {"status": 401, "json": {"message": "expirado"}},
                {"json": {"accessToken": "at2"}},
                {"json": [{"_id": "1"}]},
            ]
        )
        db = RobleClient(
            base_url=BASE,
            contract_id=CID,
            session=sesion,  # type: ignore[arg-type]
            storage=disco,
        )
        db.login(email="a@b.co", password="x")

        filas = db.read("t")
        assert filas == [{"_id": "1"}]
        assert sesion.llamadas[-1]["headers"]["Authorization"] == "Bearer at2"

    def test_timeout_se_traduce(self) -> None:
        db = cliente([{"raise": requests.Timeout()}])
        with pytest.raises(RobleTimeoutError):
            db.read("t")


def test_context_manager() -> None:
    with cliente([]) as db:
        assert db.is_logged_in is False


def test_file_storage(tmp_path: Any) -> None:
    from roble import FileStorage

    almacen = FileStorage(path=tmp_path / "sesion.json")
    assert almacen.get_item("k") is None

    almacen.set_item("k", "v")
    assert almacen.get_item("k") == "v"

    # Un almacén nuevo sobre el mismo fichero lo lee.
    assert FileStorage(path=tmp_path / "sesion.json").get_item("k") == "v"

    almacen.remove_item("k")
    assert almacen.get_item("k") is None


def test_file_storage_corrupto_no_revienta(tmp_path: Any) -> None:
    from roble import FileStorage

    ruta = tmp_path / "sesion.json"
    ruta.write_text("{no es json", encoding="utf-8")
    assert FileStorage(path=ruta).get_item("k") is None


class TestModelos:
    def test_insert_result_tolera_basura(self) -> None:
        res = InsertResult.from_json({"inserted": None, "skipped": "nope"})
        assert res.inserted == []
        assert res.has_skipped is False

    def test_user_from_json_incompleto(self) -> None:
        from roble import User

        user = User.from_json({"userId": "u1"})
        assert user.user_id == "u1"
        assert user.extra is None
        assert user.name == ""


def test_optional_storage_type() -> None:
    """MemoryStorage cumple el Protocol sin heredarlo."""
    from roble import TokenStorage

    assert isinstance(MemoryStorage(), TokenStorage)
