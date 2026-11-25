"""Indicative farming input costs and cost-saving tips, by country.

The benchmark ranges are Turkish planning figures in TRY per decare, per season. They are NOT live
market prices, and they are shown only for Turkey. For other countries no figures are invented:
the response says so, and the user is pointed to local dealers. Review the TRY ranges against current
Turkish dealer prices before relying on them.
"""

from __future__ import annotations

from typing import Any

from services.regions import currency_info

BENCHMARK_COUNTRY = "TR"   # the only country with benchmark figures
BENCHMARK_CURRENCY = "TRY"

ESTIMATES: tuple[dict[str, Any], ...] = (
    {"id": "seed", "icon": "🌾", "min": 400, "max": 700,
     "label": {"tr": "Tohum", "en": "Seed"}},
    {"id": "fertilizer", "icon": "🧪", "min": 150, "max": 350,
     "label": {"tr": "Gübre (NPK, üre)", "en": "Fertilizer (NPK, urea)"}},
    {"id": "crop_protection", "icon": "🛡️", "min": 100, "max": 300,
     "label": {"tr": "İlaçlama (fungisit, insektisit)", "en": "Crop protection (fungicide, insecticide)"}},
    {"id": "irrigation", "icon": "💧", "min": 80, "max": 250,
     "label": {"tr": "Sulama (su, elektrik, mazot)", "en": "Irrigation (water, power, diesel)"}},
    {"id": "machinery", "icon": "🚜", "min": 300, "max": 700,
     "label": {"tr": "Makine hizmeti (sürüm, ekim, hasat)", "en": "Machinery services (tillage, sowing, harvest)"}},
)

# scope: "any" = valid everywhere; "tr" = refers to Turkish institutions, shown for Turkey only.
TIPS: tuple[dict[str, Any], ...] = (
    {"id": "coop", "icon": "🤝", "scope": "any",
     "tr": ("Ortak alım yapın", "Kooperatifler veya komşularla toplu alım, birim fiyatı düşürür. Tohum ve gübrede toplu alım en belirgin tasarrufu sağlar."),
     "en": ("Buy together", "Bulk orders through a cooperative or with neighbours lower the unit price. Seed and fertiliser show the clearest savings.")},
    {"id": "soil", "icon": "🧫", "scope": "any",
     "tr": ("Gübreden önce toprak analizi", "Toprak analizi, neyin eksik olduğunu gösterir. Gereksiz gübre almak en sık görülen gider kalemidir. Bir toprak analiz laboratuvarına veya ziraat danışmanına başvurun."),
     "en": ("Test soil before fertilising", "A soil test shows what is actually missing. Unneeded fertiliser is one of the most common avoidable costs. A soil lab or agronomy adviser can test it.")},
    {"id": "seed_rate", "icon": "🌱", "scope": "any",
     "tr": ("Önerilen ekim sıklığına uyun", "Fazla tohum sarf etmek parayı boşa harcar. Sertifikalı tohum daha pahalıdır ama çimlenme oranı yüksek olduğu için yeniden ekim riskini azaltır."),
     "en": ("Stick to the recommended seeding rate", "Over-seeding wastes money. Certified seed costs more but germinates reliably, which reduces the risk of re-sowing.")},
    {"id": "share_machines", "icon": "🚜", "scope": "any",
     "tr": ("Makineyi kiralayın veya paylaşın", "Her işe kendi makineniz gerekmez. Makine kooperatifleri ve hizmet veren çiftçiler dekar başına ücret karşılığı çalışır; yılda az kullanılan makineler için genelde daha ucuzdur."),
     "en": ("Rent or share machinery", "You rarely need to own every machine. Machinery cooperatives and custom operators charge per unit area, which is usually cheaper for equipment used only a few times a year.")},
    {"id": "spray_window", "icon": "🧪", "scope": "any",
     "tr": ("İlacı doğru pencerede uygulayın", "Rüzgârsız ve yağmursuz bir pencerede ilaçlama, ilacın boşa gitmesini ve tekrar uygulamayı önler. Panodaki 'ilaçlama için uygun pencere' uyarısını takip edin."),
     "en": ("Spray in the right window", "Spraying in calm, dry weather avoids drift and repeat passes. Follow the 'good spraying window' alert on the dashboard.")},
    {"id": "water", "icon": "💧", "scope": "any",
     "tr": ("Suyu verimli kullanın", "Malç, damla sulama ve sabah erken ya da akşam sulama, su ve pompa yakıtını azaltır. Yağış beklenen günlerde sulamayı erteleyin."),
     "en": ("Use water efficiently", "Mulch, drip irrigation and watering early morning or evening cut both water and pump fuel. Postpone irrigation when rain is forecast.")},
    {"id": "subsidies", "icon": "📋", "scope": "tr",
     "tr": ("Destek programlarını kontrol edin", "Mazot, gübre ve sigorta destekleri yıllara göre değişir. Güncel programlar için il tarım müdürlüğüne veya kooperatifinize danışın."),
     "en": ("Check support programmes", "Diesel, fertiliser and insurance support changes from year to year. Ask your provincial directorate or cooperative for current programmes.")},
    {"id": "compare", "icon": "🏷️", "scope": "any",
     "tr": ("Fiyatları karşılaştırın, sezon dışında alın", "En az iki-üç bayiden fiyat alın. Girdiler çoğu zaman yoğun sezon öncesinde daha ucuzdur; kuru ve serin bir yerde saklayın."),
     "en": ("Compare prices and buy off-peak", "Get quotes from two or three dealers. Inputs are often cheaper before the peak season; store them dry and cool.")},
)


def build_cost_insights(lang: str, farm_size: float | None, country_code: str | None) -> dict[str, Any]:
    lang = lang if lang in ("tr", "en") else "en"
    has_benchmarks = country_code == BENCHMARK_COUNTRY
    # Region-neutral tips everywhere; Turkish-institution tips only for Turkey.
    tips = [
        {"id": tip["id"], "icon": tip["icon"], "title": tip[lang][0], "text": tip[lang][1]}
        for tip in TIPS
        if tip["scope"] == "any" or has_benchmarks
    ]
    info = currency_info(country_code)
    if not has_benchmarks:
        # No figures for this country. The currency is still shown, so any price the user enters
        # or sees on a dealer site is read correctly.
        return {
            "benchmarks": False,
            "currency": info,
            "estimates": [],
            "total": None,
            "tips": tips,
        }

    estimates: list[dict[str, Any]] = []
    total_min = total_max = 0.0
    for e in ESTIMATES:
        row: dict[str, Any] = {
            "id": e["id"],
            "icon": e["icon"],
            "label": e["label"][lang],
            "min_per_decare": e["min"],
            "max_per_decare": e["max"],
        }
        if farm_size:
            row["total_min"] = round(e["min"] * farm_size)
            row["total_max"] = round(e["max"] * farm_size)
            total_min += row["total_min"]
            total_max += row["total_max"]
        estimates.append(row)

    return {
        "benchmarks": True,
        "currency": info or {"code": BENCHMARK_CURRENCY, "symbol": "₺", "locale": "tr-TR"},
        "estimates": estimates,
        "total": {"min": round(total_min), "max": round(total_max)} if farm_size else None,
        "tips": tips,
    }
