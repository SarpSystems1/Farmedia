"""Farmedia FastAPI Ana Sunucu Modülü."""

from __future__ import annotations

import os
from typing import Literal, Optional
from fastapi import FastAPI, Header, Request, Query, Response, status
from pathlib import Path

from dotenv import load_dotenv
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictBool

from services.errors import AuthenticationError, BaseFarmediaError, InvalidInputError
from services import accounts
from services.i18n import t
from services.weather_service import get_coordinates, get_forecast, get_weather_data
from services.geocoding import geocode_location
from services.crops import parse_crops
from services.insights import build_insights
from services.frost_engine import analyze_frost_risk
from services.sarp_ai import get_sarp_ai_advice
from services.suppliers import build_search_links, find_suppliers, radius_for_precision
from services.regions import country_name, resolve_code

COOP_URL = "https://www.tarimkredi.org.tr"  # Turkish cooperative network: shown for Turkey only
from services.cost_insights import build_cost_insights

load_dotenv()  # before reading APP_ENV below; services/ also load it, this is idempotent
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"

app = FastAPI(
    title="Farmedia Agricultural Intelligence API",
    version="2.0.0",
    description="Scalable FastAPI backend for agricultural frost risk analysis and AI advisory.",
    # In production the interactive API docs are not published.
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

app.add_middleware(GZipMiddleware, minimum_size=1024)

# Content-Security-Policy. The page has no inline scripts or styles; Chart.js comes from cdnjs.
# 'unsafe-inline' for styles is needed because the UI sets some element styles at run time.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://cdnjs.cloudflare.com",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    headers = response.headers
    headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    headers.setdefault("Permissions-Policy", "camera=(), microphone=(), payment=(), usb=()")
    if IS_PRODUCTION:
        headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


class FarmContext(BaseModel):
    """The user's farm profile, sent only when they agreed to share it with Sarp AI."""
    role: Optional[Literal["hobby", "farm"]] = None
    farm_size: Optional[float] = Field(None, ge=0, le=1_000_000)  # decares
    crops_last: Optional[str] = Field(None, max_length=300)
    crops_current: Optional[str] = Field(None, max_length=300)
    crops_next: Optional[str] = Field(None, max_length=300)


class SarpAIRequest(BaseModel):
    question: str = Field(..., max_length=2000)
    city: Optional[str] = Field(None, max_length=100)
    lang: Literal["tr", "en"] = "tr"
    farm_context: Optional[FarmContext] = None


@app.exception_handler(BaseFarmediaError)
async def farmedia_error_handler(request: Request, exc: BaseFarmediaError):
    """Farmedia özel hatalarını yakalayıp seçilen dilde JSON formatında döndürür."""
    lang = request.query_params.get("lang", "tr")
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(lang, t),
    )


STATIC_DIR = Path(__file__).parent / "static"


class NoCacheStaticFiles(StaticFiles):
    """Static files the browser must revalidate on every use.

    StaticFiles sends ETag and Last-Modified but no Cache-Control, so a browser may reuse an
    old copy without asking the server, and edits look "not applied". "no-cache" keeps the
    ETag check, so an unchanged file costs only a small 304 response.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


@app.get("/", include_in_schema=False)
async def index():
    """Serve the single-page web UI."""
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/health", summary="Ana Sayfa / Sağlık Kontrolü")
async def root(lang: str = Query("tr", description="Dil seçimi (tr / en)")):
    """API'nin ayakta olduğunu ve çalıştığını gösterir."""
    return {
        "status": "online",
        "title": t(lang, "app.title"),
        "message": t(lang, "app.welcome"),
    }


@app.get("/api/analyze", summary="Şehir Bazlı Don Analizi")
async def analyze_city(
    city: str = Query(..., description="Analiz yapılacak şehir adı (örn: Bursa, Ankara)"),
    lang: str = Query("tr", description="Dil seçimi (tr / en)"),
):
    """Bir şehir adı alır, koordinatlarını bulur, hava durumunu çeker ve don analizi yapar."""
    if not city.strip():
        raise InvalidInputError("City name cannot be empty.", field="city")

    # 1. Adım: Şehir adını koordinatlara çevir
    location = await get_coordinates(city)

    # 2. Adım: Koordinatlara göre hava durumu verilerini çek
    weather_json = await get_weather_data(
        latitude=location["latitude"],
        longitude=location["longitude"]
    )

    # 3. Adım: Saatlik verileri don analiz motorundan geçir
    hourly_data = weather_json.get("hourly", {})
    analysis_result = analyze_frost_risk(hourly_data)

    # 4. Adım: Sonuçlardaki i18n anahtarlarını seçilen dile çevir
    analysis_result["risk_level_text"] = t(lang, analysis_result["risk_level"])
    analysis_result["frost_type_text"] = t(lang, analysis_result["frost_type"])

    return {
        "location": location,
        "analysis": analysis_result,
    }


@app.post("/api/sarp-ai", summary="Sarp AI Ziraî Danışman (Groq, llama-3.3-70b-versatile)")
async def ask_sarp_ai(request: SarpAIRequest):
    """
    Kullanıcının tarımla ilgili sorusunu yanıtlar.
    Eğer şehir belirtilirse, o şehrin anlık hava/don verilerini de bağlam olarak kullanır.
    """
    if not request.question.strip():
        raise InvalidInputError("Question cannot be empty.", field="question")

    weather_context = ""
    
    # Eğer şehir verildiyse, arka planda don verilerini çekip yapay zekaya bağlam verelim
    if request.city and request.city.strip():
        try:
            location = await get_coordinates(request.city)
            weather_json = await get_weather_data(
                latitude=location["latitude"],
                longitude=location["longitude"]
            )
            analysis_result = analyze_frost_risk(weather_json.get("hourly", {}))
            weather_context = (
                f"Şehir: {request.city}, "
                f"Don Risk Seviyesi: {analysis_result.get('risk_level')}, "
                f"Minimum Sıcaklık: {analysis_result.get('min_temp')}°C"
            )
        except Exception:
            weather_context = f"Şehir: {request.city} (Hava/Don verisi alınamadı, genel tavsiye ver.)"

    # Sarp AI servisinden yanıtı al
    ai_answer = await get_sarp_ai_advice(
        question=request.question,
        weather_context=weather_context,
        lang=request.lang,
        farm_context=request.farm_context.model_dump() if request.farm_context else None,
    )

    return {
        "question": request.question,
        "city": request.city,
        "sarp_ai_answer": ai_answer
    }


@app.get("/api/geocode", summary="Profil konumundan koordinat bul (Nominatim)")
async def geocode(
    country: str = Query(...),
    state: str = "",
    city: str = "",
    district: str = "",
    lang: str = "tr",
):
    return await geocode_location(country, state, city, district, lang=lang)


class CropsRequest(BaseModel):
    text: str = ""
    lang: str = "tr"


@app.post("/api/parse-crops", summary="Serbest metinden ürünleri ayrıştır")
async def parse_crops_endpoint(req: CropsRequest):
    return parse_crops(req.text, req.lang)


class DashboardRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    lang: str = "tr"
    role: str = "hobby"  # "hobby" | "farm"
    farm_size: Optional[float] = Field(None, ge=0)
    crops_last: str = ""
    crops_current: str = ""
    crops_next: str = ""


@app.post("/api/dashboard", summary="Hava durumu + öneriler")
async def dashboard(req: DashboardRequest):
    forecast = await get_forecast(req.latitude, req.longitude)
    is_farm = req.role == "farm"
    parsed = {
        k: parse_crops(getattr(req, f"crops_{k}") if is_farm or k == "current" else "", req.lang)
        for k in ("last", "current", "next")
    }
    insights = build_insights(
        forecast,
        lang=req.lang,
        role="farm" if is_farm else "hobby",
        farm_size=req.farm_size if is_farm else None,
        crops_last=parsed["last"]["crops"],
        crops_current=parsed["current"]["crops"],
        crops_next=parsed["next"]["crops"],
    )
    return {
        "forecast": {
            "current": forecast.get("current", {}),
            "current_units": forecast.get("current_units", {}),
            "daily": forecast.get("daily", {}),
            "timezone": forecast.get("timezone"),
            "elevation": forecast.get("elevation"),
        },
        "insights": insights,
        "crops": parsed,
    }


@app.get("/api/market", summary="Yerel tohumcu/makine bayileri ve girdi maliyet önerileri")
async def market(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    precision: Literal["district", "city", "state", "country"] = Query("city"),
    radius_km: Optional[float] = Query(None, gt=0, le=300),
    lang: str = Query("tr"),
    farm_size: Optional[float] = Query(None, ge=0),
    city: str = Query("", max_length=100),
    state: str = Query("", max_length=100),
    country: str = Query("", max_length=100),
    country_code: str = Query("", max_length=2),
):
    """Suppliers and cost estimates around the user's chosen place.

    The search centre is the geocoded coordinate of the place the user selected, and the radius
    follows how precise that place is. Region data (currency, cooperative link, benchmarks) is
    used only for a country we know; an unknown country gets none of it.
    """
    lang = "tr" if lang == "tr" else "en"
    code = resolve_code(country_code, country)
    radius = radius_km if radius_km is not None else radius_for_precision(precision)
    try:
        suppliers = {"status": "ok", "items": await find_suppliers(latitude, longitude, radius)}
    except BaseFarmediaError:
        suppliers = {"status": "unavailable", "items": []}
    place = [city, state, country_name(code, lang) or country]
    return {
        "suppliers": suppliers,
        "radius_km": radius,
        "country_code": code,
        "coop_url": COOP_URL if code == "TR" else None,
        "search_links": build_search_links(lang, place),
        "costs": build_cost_insights(lang, farm_size, code),
    }


# ---------- Accounts (Supabase Auth + RLS-protected profile) ----------

class RegisterRequest(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., min_length=6, max_length=128)  # product rule; see accounts.PASSWORD_MIN
    first_name: str = Field(..., max_length=60)
    last_name: str = Field(..., max_length=60)
    country: str = Field(..., min_length=2, max_length=2)   # ISO 3166-1 alpha-2, decides the regime
    locale: str = "en"                                       # "tr" | "en"
    terms_version: str = Field(..., max_length=32)           # must match the current published version
    privacy_version: str = Field(..., max_length=32)
    # Explicit acceptances (the user must tick each box; these are never assumed).
    # StrictBool: "false", 0 or "yes" are rejected instead of being coerced to a boolean.
    terms_accepted: StrictBool = False
    privacy_accepted: StrictBool = False
    kvkk_explicit: StrictBool = False
    kvkk_transfer: StrictBool = False
    alert_email: StrictBool = False
    alert_sms: StrictBool = False
    marketing_email: StrictBool = False
    do_not_sell: StrictBool = False


class LoginRequest(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=128)


class ProfileUpdate(BaseModel):
    first_name: Optional[str] = Field(None, max_length=60)
    last_name: Optional[str] = Field(None, max_length=60)
    role: Optional[Literal["hobby", "farm"]] = None
    farm_size: Optional[float] = Field(None, ge=0)
    location: Optional[dict] = None
    crops: Optional[dict] = None
    preferences: Optional[dict] = None  # validated by accounts._checked_preferences
    alert_email_consent: Optional[StrictBool] = None
    alert_sms_consent: Optional[StrictBool] = None
    marketing_email_consent: Optional[StrictBool] = None
    do_not_sell: Optional[StrictBool] = None


def _bearer(authorization: Optional[str]) -> str:
    """Extract the access token from an 'Authorization: Bearer <token>' header."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError()
    token = authorization[7:].strip()
    if not token:
        raise AuthenticationError()
    return token


@app.get("/api/legal/requirements", summary="Ülkeye ve dile göre gerekli onaylar ve güncel belgeler")
async def legal_requirements(country: str = Query(..., min_length=2, max_length=2),
                             locale: str = Query("en")):
    return await accounts.legal_requirements(country, locale)


@app.post("/api/auth/register", status_code=201, summary="Kayıt (ülkeye göre zorunlu onaylar)")
async def register(req: RegisterRequest):
    return await accounts.register(
        email=req.email,
        password=req.password,
        first_name=req.first_name,
        last_name=req.last_name,
        country=req.country,
        locale=req.locale,
        terms_version=req.terms_version,
        privacy_version=req.privacy_version,
        consents={
            "terms": req.terms_accepted,
            "privacy_policy": req.privacy_accepted,
            "kvkk_explicit": req.kvkk_explicit,
            "kvkk_transfer": req.kvkk_transfer,
            "alert_email": req.alert_email,
            "alert_sms": req.alert_sms,
            "marketing_email": req.marketing_email,
            "do_not_sell": req.do_not_sell,
        },
    )


@app.post("/api/auth/login", summary="Giriş (e-posta + şifre)")
async def login(req: LoginRequest):
    return await accounts.login(req.email, req.password)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1, max_length=512)


@app.post("/api/auth/refresh", summary="Oturumu yenile (refresh token)")
async def refresh(req: RefreshRequest):
    return await accounts.refresh_session(req.refresh_token)


@app.post("/api/auth/logout", status_code=204, summary="Bu cihazdaki oturumu kapat")
async def logout(authorization: Optional[str] = Header(None)):
    await accounts.logout(_bearer(authorization))
    return Response(status_code=204)


@app.get("/api/auth/me", summary="Oturumdaki kullanıcı ve profili")
async def me(authorization: Optional[str] = Header(None)):
    return await accounts.get_current_user(_bearer(authorization))


@app.patch("/api/profile", summary="Profil ve uyarı izinlerini güncelle")
async def patch_profile(req: ProfileUpdate, authorization: Optional[str] = Header(None)):
    token = _bearer(authorization)
    await accounts.get_current_user(token)  # validates the token; the DB applies RLS to the update
    updated = await accounts.update_profile(token, req.model_dump(exclude_none=True))
    return {"profile": updated}


@app.get("/api/profile/export", summary="Kişisel verilerinizin taşınabilir (JSON) kopyası")
async def export_profile(authorization: Optional[str] = Header(None)):
    data = await accounts.export_user_data(_bearer(authorization))
    return JSONResponse(content=data, headers={
        "Content-Disposition": 'attachment; filename="farmedia-export.json"',
        "Cache-Control": "no-store",  # contains personal data; must not be cached by a proxy
    })


class DeleteAccountRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)  # re-entered to confirm


@app.delete("/api/account", status_code=204, summary="Hesabı ve kişisel verileri kalıcı olarak sil")
async def delete_account(req: DeleteAccountRequest, authorization: Optional[str] = Header(None)):
    await accounts.delete_account(_bearer(authorization), req.password)
    return Response(status_code=204)


app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")
