"""Farmedia FastAPI Ana Sunucu Modülü."""

from __future__ import annotations

from typing import Optional
from fastapi import FastAPI, Request, Query, status
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from services.errors import BaseFarmediaError, InvalidInputError
from services.i18n import t
from services.weather_service import get_coordinates, get_forecast, get_weather_data
from services.geocoding import geocode_location
from services.crops import parse_crops
from services.insights import build_insights
from services.frost_engine import analyze_frost_risk
from services.sarp_ai import get_sarp_ai_advice

app = FastAPI(
    title="Farmedia Agricultural Intelligence API",
    version="2.0.0",
    description="Scalable FastAPI backend for agricultural frost risk analysis and AI advisory.",
)


# Pydantic Model for Sarp AI Request
class AskRequest(BaseModel):
    question: str
    city: Optional[str] = None
    lang: Optional[str] = "tr"


@app.exception_handler(BaseFarmediaError)
async def farmedia_error_handler(request: Request, exc: BaseFarmediaError):
    """Farmedia özel hatalarını yakalayıp seçilen dilde JSON formatında döndürür."""
    lang = request.query_params.get("lang", "tr")
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(lang, t),
    )


STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
async def index():
    """Serve the single-page web UI."""
    return FileResponse(STATIC_DIR / "index.html")


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


@app.post("/api/ask", summary="Sarp AI Ziraî Danışman")
async def ask_sarp_ai(request: AskRequest):
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
        weather_context=weather_context
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


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
