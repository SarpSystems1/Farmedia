"""Ziraî don analitiği ve risk hesaplama motoru."""

from __future__ import annotations
from typing import Any


def analyze_frost_risk(hourly_data: dict[str, Any]) -> dict[str, Any]:
    """Open-Meteo saatlik verilerini analiz ederek şafak öncesi don riski ve tipi hesaplar.
    
    Özellikle 00:00 - 08:00 saat aralığına odaklanır.
    """
    times = hourly_data.get("time", [])
    temps = hourly_data.get("temperature_2m", [])
    dew_points = hourly_data.get("dew_point_2m", [])
    winds = hourly_data.get("wind_speed_10m", [])
    
    if not temps or not times:
        return {
            "risk_score": 0,
            "risk_level": "risk.level.none",
            "frost_type": "frost.type.none",
            "min_temp": 0.0,
            "details": "Yetersiz hava durumu verisi."
        }

    # Şafak öncesi (00:00 - 08:00) saatleri filtrele
    dawn_temps = []
    dawn_winds = []
    
    for t_str, temp, wind in zip(times, temps, winds):
        # Örn format: "2026-06-06T04:00"
        try:
            hour = int(t_str.split("T")[1].split(":")[0])
            if 0 <= hour <= 8:
                dawn_temps.append(temp)
                dawn_winds.append(wind if wind is not None else 0.0)
        except (IndexError, ValueError):
            continue

    # Eğer filtrelenen saat bulunamazsa genel verilere bak
    if not dawn_temps:
        dawn_temps = temps[:8]
        dawn_winds = winds[:8] if winds else [0.0] * len(dawn_temps)

    min_temp = min(dawn_temps)
    avg_wind = sum(dawn_winds) / len(dawn_winds) if dawn_winds else 0.0

    # Don Tipi ve Risk Puanı Hesaplama Mantığı
    if min_temp > 2.0:
        risk_score = 0
        risk_level = "risk.level.none"
        frost_type = "frost.type.none"
    elif 0.0 < min_temp <= 2.0:
        risk_score = 30
        risk_level = "risk.level.low"
        frost_type = "frost.type.white"
    else:
        # Sıcaklık 0 ve altındaysa
        # Sıcaklık ne kadar düşükse risk o kadar artar (-5 derece ve altı kritik)
        temp_factor = min(100.0, abs(min_temp) * 15.0)
        
        if avg_wind >= 15.0:
            # Şiddetli rüzgar varsa Advektif (Hava kütlesi hareketi) donu
            frost_type = "frost.type.advective"
            risk_score = int(min(100, temp_factor * 1.1))
        elif avg_wind < 4.0 and min_temp <= -2.0:
            # Düşük rüzgar ve kuru soğuk -> Kara Don (Black Frost)
            frost_type = "frost.type.black"
            risk_score = int(min(100, temp_factor * 1.2))
        else:
            # Standart Işıma Donu -> Beyaz Don
            frost_type = "frost.type.white"
            risk_score = int(min(100, temp_factor))

        # Risk Seviyesi Belirleme
        if risk_score >= 80:
            risk_level = "risk.level.critical"
        elif risk_score >= 60:
            risk_level = "risk.level.high"
        elif risk_score >= 30:
            risk_level = "risk.level.moderate"
        else:
            risk_level = "risk.level.low"

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "frost_type": frost_type,
        "min_temp": round(min_temp, 1),
        "avg_wind_speed": round(avg_wind, 1),
    }