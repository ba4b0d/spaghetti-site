"""
Category CRUD API tests.
"""
import time


def test_list_categories(client, auth_headers):
    """GET /categories returns a list of categories (requires auth)."""
    resp = client.get("/api/v1/categories", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_create_category(client, auth_headers):
    """POST /categories creates a new category."""
    unique_name = f"TestCat-{int(time.time())}"
    resp = client.post("/api/v1/categories", json={
        "name": unique_name,
    }, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == unique_name
    assert "id" in data


def test_update_category(client, auth_headers):
    """PUT /categories/{id} updates a category."""
    # Create
    unique_name = f"UpdCat-{int(time.time())}"
    create_resp = client.post("/api/v1/categories", json={
        "name": unique_name,
    }, headers=auth_headers)
    cat_id = create_resp.json()["id"]

    # Update
    resp = client.put(f"/api/v1/categories/{cat_id}", json={
        "name": f"{unique_name}-v2",
        "description": "Updated desc",
    }, headers=auth_headers)
    assert resp.status_code == 200


def test_delete_category(client, auth_headers):
    """DELETE /categories/{id} removes a category."""
    unique_name = f"DelCat-{int(time.time())}"
    create_resp = client.post("/api/v1/categories", json={
        "name": unique_name,
    }, headers=auth_headers)
    cat_id = create_resp.json()["id"]

    resp = client.delete(f"/api/v1/categories/{cat_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert "حذف شد" in resp.json()["message"]


def test_deleted_category_is_not_recreated_from_legacy_product_text(client, auth_headers, monkeypatch):
    """A deleted category must stay deleted after the application restarts."""
    from app.database import get_db
    from app.models import Category, Product
    from app.main import lifespan
    import app.main as main_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # Make the startup migration use the isolated database created by the fixture.
    engine = create_engine("sqlite:///tests/test.db", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)

    unique_name = f"LegacyCat-{int(time.time())}"
    create_resp = client.post("/api/v1/categories", json={"name": unique_name}, headers=auth_headers)
    cat_id = create_resp.json()["id"]

    db = next(client.app.dependency_overrides[get_db]())
    try:
        db.add(Product(name=f"Product-{unique_name}", category=unique_name))
        db.commit()
    finally:
        db.close()

    delete_resp = client.delete(f"/api/v1/categories/{cat_id}", headers=auth_headers)
    assert delete_resp.status_code == 200

    async def restart_app():
        async with lifespan(client.app):
            pass

    import asyncio
    asyncio.run(restart_app())

    db = next(client.app.dependency_overrides[get_db]())
    try:
        assert db.query(Category).filter(Category.name == unique_name).first() is None
    finally:
        db.close()
