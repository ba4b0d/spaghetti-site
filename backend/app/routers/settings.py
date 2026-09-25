from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Settings
from app.schemas import SettingsUpdate, SettingsBulkUpdate, SettingsResponse
from app.cache import invalidate_settings_cache
from app.routers.stats import invalidate_stats

from app.routers.auth import require_admin, limiter

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


ALLOWED_PUBLIC_KEYS = {
    "favicon_url",
    "logo_url",
    "site_name",
    "site_title",
    "enable_blog",
    "contact_brand",
    "contact_phone",
    "contact_telegram",
    "contact_whatsapp",
    "contact_instagram",
    "contact_bale",
    "contact_hours",
    "contact_city",
    "contact_note",
}


SENSITIVE_SETTING_KEYS = {"gdrive_credentials_json", "telegram_bot_token"}


from app.routers.auth import get_current_user


@router.get("")
def get_all_settings(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Return all settings as a flat key-value dict. Masks sensitive keys for non-admin roles."""
    settings = db.query(Settings).all()
    is_admin = user.get("role") == "admin"
    result = {}
    for s in settings:
        if not is_admin and s.key in SENSITIVE_SETTING_KEYS:
            continue
        result[s.key] = {
            "value": s.value,
            "description": s.description,
            "id": s.id,
            "string_value": s.string_value or "",
        }
    return result


@router.get("/public")
def get_public_settings(db: Session = Depends(get_db)):
    """Public settings route — /api/v1/brand."""
    settings = db.query(Settings).filter(Settings.key.in_(ALLOWED_PUBLIC_KEYS)).all()
    result = {}
    for s in settings:
        if s.key == "enable_blog":
            result[s.key] = bool(s.value and s.value > 0)
        else:
            result[s.key] = s.string_value or ""
    return result


@router.put("")
@limiter.limit("20/minute")
def update_settings(request: Request, payload: SettingsBulkUpdate, user=Depends(require_admin), db: Session = Depends(get_db)):
    """Update one or more settings by key."""
    updated = []
    for item in payload.settings:
        setting = db.query(Settings).filter(Settings.key == item.key).first()
        if setting:
            setting.value = item.value
            if hasattr(item, 'string_value') and item.string_value is not None:
                setting.string_value = item.string_value
            if item.description is not None:
                setting.description = item.description
            updated.append(setting.key)
        else:
            sv = getattr(item, 'string_value', None) or ""
            new_setting = Settings(key=item.key, value=item.value, string_value=sv, description=item.description or "")
            db.add(new_setting)
            updated.append(item.key)
    db.commit()
    invalidate_settings_cache()
    invalidate_stats()
    return {"updated": updated}


import os
import uuid

BRANDING_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads", "branding")
os.makedirs(BRANDING_UPLOAD_DIR, exist_ok=True)


def _is_valid_image_header(contents: bytes, ext: str) -> bool:
    """Validate file binary header against declared image format extension."""
    if ext in (".png",):
        return contents.startswith(b"\x89PNG\r\n\x1a\n")
    elif ext in (".jpg", ".jpeg"):
        return contents.startswith(b"\xff\xd8\xff")
    elif ext in (".gif",):
        return contents.startswith(b"GIF87a") or contents.startswith(b"GIF89a")
    elif ext in (".webp",):
        return b"WEBP" in contents[:16]
    elif ext in (".ico",):
        return contents.startswith(b"\x00\x00\x01\x00") or contents.startswith(b"\x00\x00\x02\x00")
    elif ext in (".svg",):
        snippet = contents.decode("utf-8", errors="ignore").lower()
        if "<svg" not in snippet[:1000]:
            return False
        # Reject executable scripts or event handlers in SVG to prevent Stored XSS
        disallowed = ("<script", "javascript:", "onload=", "onerror=", "onclick=", "onmouseover=", "onfocus=")
        return not any(tag in snippet for tag in disallowed)
    return False


@router.post("/upload/{key}")
@limiter.limit("10/minute")
async def upload_branding_asset(request: Request, key: str, file: UploadFile = File(...), user=Depends(require_admin), db: Session = Depends(get_db)):
    """Upload a favicon or logo image and store its URL in settings (admin only)."""
    if key not in ("favicon_url", "logo_url"):
        raise HTTPException(status_code=400, detail="Invalid key. Must be 'favicon_url' or 'logo_url'")

    # Validate extension
    allowed_ext = {".png", ".jpg", ".jpeg", ".svg", ".ico", ".webp"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"فرمت فایل مجاز نیست. مجاز: {', '.join(allowed_ext)}")

    # Validate size (max 2MB)
    contents = await file.read()
    if len(contents) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="حجم فایل نباید بیشتر از ۲ مگابایت باشد")

    # Validate magic bytes / image header
    if not _is_valid_image_header(contents, ext):
        raise HTTPException(status_code=400, detail="محتوای فایل با پسوند تصویر مطابقت ندارد")

    # Save with UUID filename
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(BRANDING_UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(contents)

    # Store URL in settings
    url = f"/uploads/branding/{filename}"
    setting = db.query(Settings).filter(Settings.key == key).first()
    if setting:
        setting.string_value = url
    else:
        setting = Settings(key=key, value=0, string_value=url, description=f"Branding asset for {key}")
        db.add(setting)
    db.commit()
    invalidate_settings_cache()
    return {"url": url, "key": key}


CONTACT_KEYS = [
    "contact_brand",
    "contact_phone",
    "contact_telegram",
    "contact_whatsapp",
    "contact_instagram",
    "contact_bale",
    "contact_hours",
    "contact_city",
    "contact_note",
]


def get_contact_info(db: Session = Depends(get_db)):
    """Return public contact info as a flat JSON dict (no auth required)."""
    settings = db.query(Settings).filter(Settings.key.in_(CONTACT_KEYS)).all()
    result = {s.key: s.string_value or "" for s in settings}
    # Fill missing keys with empty strings so every key is always present
    for key in CONTACT_KEYS:
        result.setdefault(key, "")
    return result
