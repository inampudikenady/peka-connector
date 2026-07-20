from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import SPAStaticFiles


def test_serves_frontend_and_spa_routes_without_masking_missing_assets(tmp_path) -> None:
    (tmp_path / "index.html").write_text("<h1>PEKA Connector</h1>", encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('peka')", encoding="utf-8")
    static_app = FastAPI()
    static_app.mount("/", SPAStaticFiles(directory=tmp_path, html=True))
    client = TestClient(static_app)

    assert client.get("/").status_code == 200
    assert "PEKA Connector" in client.get("/sources/example").text
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/api/unknown").status_code == 404
