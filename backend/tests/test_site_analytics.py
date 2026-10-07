from datetime import datetime, timezone
from app.models import SiteView
from app.routers.stats import _site_view_stats
from tests.conftest import TestSessionLocal


def test_site_view_stats_groups_in_tehran_and_ranks_content():
    db = TestSessionLocal()
    try:
        # 23:59 Tehran on Oct 6, then 00:01 and 12:30 on Oct 7.
        db.add_all([
            SiteView(path='/', content_type='home', created_at=datetime(2026, 10, 6, 20, 29, tzinfo=timezone.utc)),
            SiteView(path='/catalog/demo', content_type='product', content_slug='demo', created_at=datetime(2026, 10, 6, 20, 31, tzinfo=timezone.utc)),
            SiteView(path='/catalog/demo', content_type='product', content_slug='demo', created_at=datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)),
        ])
        db.commit()

        stats = _site_view_stats(db, now=datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc))

        assert stats['site_views_today'] == 2
        assert stats['site_views_total'] == 3
        assert stats['site_views_daily'][-1]['views'] == 2
        assert stats['site_top_content'][0] == {
            'path': '/catalog/demo', 'content_type': 'product', 'content_slug': 'demo', 'views': 2,
        }
    finally:
        db.close()


def test_public_view_endpoint_rejects_admin_paths_and_accepts_public_path(client):
    assert client.post('/api/v1/analytics/view', json={'path': '/dashboard'}).status_code == 422
    assert client.post('/api/v1/analytics/view', json={'path': '/admin/posts'}).status_code == 422
    assert client.post('/api/v1/analytics/view', json={'path': '/catalog/demo'}).status_code == 204


def test_stats_endpoint_includes_site_views(client, auth_headers):
    # Record view
    rec = client.post('/api/v1/analytics/view', json={'path': '/catalog/sample-3d'})
    assert rec.status_code == 204

    # Fetch stats as staff/admin
    resp = client.get('/api/v1/stats', headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert 'site_views_today' in data
    assert 'site_views_week' in data
    assert 'site_views_total' in data
    assert 'site_views_daily' in data
    assert 'site_views_weekly' in data
    assert 'site_top_content' in data
    assert data['site_views_today'] >= 1
