"""Farmedia çok dilli destek (i18n) modülü."""

from __future__ import annotations
from typing import Any

from services.insight_texts import EN as _INS_EN, TR as _INS_TR

TRANSLATIONS: dict[str, dict[str, str]] = {
    "tr": {
        # Hata Mesajları
        "error.internal": "Beklenmeyen bir iç hata oluştu.",
        "error.upstream_timeout": "Harici servis zamanında yanıt vermedi.",
        "error.upstream_failure": "Harici servis bir hata döndürdü veya geçersiz yanıt verdi.",
        "error.location_not_found": "İstenen konum bulunamadı: {query}",
        "error.invalid_input": "Girilen veriler geçersiz: {field}",
        
        # Don Tipleri
        "frost.type.white": "Beyaz Don (Işıma Donu)",
        "frost.type.black": "Kara Don (Black Frost)",
        "frost.type.advective": "Advektif Rüzgar Donu",
        "frost.type.none": "Don Riski Yok",

        # Risk Seviyeleri
        "risk.level.none": "Yok",
        "risk.level.low": "Düşük",
        "risk.level.moderate": "Orta",
        "risk.level.high": "Yüksek",
        "risk.level.critical": "Kritik",

        # Arayüz / Genel
        "app.title": "Farmedia Ziraî Don Analitiği",
        "app.welcome": "Farmedia API aktif ve çalışıyor.",
    },
    "en": {
        # Error Messages
        "error.internal": "An unexpected internal error occurred.",
        "error.upstream_timeout": "The upstream service did not respond in time.",
        "error.upstream_failure": "The upstream service returned an error or an invalid response.",
        "error.location_not_found": "The requested location could not be found: {query}",
        "error.invalid_input": "The provided input is invalid: {field}",
        
        # Frost Types
        "frost.type.white": "White Frost (Radiational Frost)",
        "frost.type.black": "Black Frost",
        "frost.type.advective": "Advective Wind Frost",
        "frost.type.none": "No Frost Risk",

        # Risk Levels
        "risk.level.none": "None",
        "risk.level.low": "Low",
        "risk.level.moderate": "Moderate",
        "risk.level.high": "High",
        "risk.level.critical": "Critical",

        # UI / General
        "app.title": "Farmedia Agricultural Frost Analytics",
        "app.welcome": "Farmedia API is active and running.",
    }
}

TRANSLATIONS["tr"].update(_INS_TR)
TRANSLATIONS["en"].update(_INS_EN)


def t(lang: str, key: str, **kwargs: Any) -> str:
    """Belirtilen dilde ve anahtarda çeviri metnini döndürür.
    
    Desteklenmeyen bir dil veya anahtar bulunursa varsayılan olarak Türkçe'ye (tr)
    fallback yapar. Metin içinde placeholder varsa kwargs ile doldurulur.
    """
    lang = lang.lower() if lang else "tr"
    if lang not in TRANSLATIONS:
        lang = "tr"
        
    lang_dict = TRANSLATIONS[lang]
    
    template = lang_dict.get(key)
    if not template:
        template = TRANSLATIONS["tr"].get(key, key)
        
    try:
        return template.format(**kwargs)
    except Exception:
        return template