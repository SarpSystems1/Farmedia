"""Rule-based recommendations / things-to-avoid from weather + farm profile."""

from __future__ import annotations

from typing import Any

from services.frost_engine import analyze_frost_risk
from services.i18n import t

SEVERITY_ORDER = {"danger": 0, "warning": 1, "info": 2, "good": 3}


def _num(v: Any, default: float = 0.0) -> float:
    return float(v) if isinstance(v, (int, float)) else default


def _fmt(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def build_insights(
    forecast: dict[str, Any],
    *,
    lang: str,
    role: str,
    farm_size: float | None,
    crops_last: list[dict[str, Any]],
    crops_current: list[dict[str, Any]],
    crops_next: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cur = forecast.get("current", {})
    daily = forecast.get("daily", {})
    hourly = forecast.get("hourly", {})

    def day(key: str, n: int) -> list[float]:
        return [_num(x) for x in (daily.get(key) or [])[:n] if x is not None]

    mins3 = day("temperature_2m_min", 3)
    maxs3 = day("temperature_2m_max", 3)
    min3 = min(mins3) if mins3 else _num(cur.get("temperature_2m"), 15)
    max3 = max(maxs3) if maxs3 else _num(cur.get("temperature_2m"), 20)
    rain3 = sum(day("precipitation_sum", 3))
    rain_today = (day("precipitation_sum", 1) or [0.0])[0]
    prob_today = (day("precipitation_probability_max", 1) or [0])[0]
    wind_max = max([*day("wind_speed_10m_max", 2), _num(cur.get("wind_speed_10m"))])
    gusts = _num(cur.get("wind_gusts_10m"))
    temp = _num(cur.get("temperature_2m"), (min3 + max3) / 2)
    hum = _num(cur.get("relative_humidity_2m"), 50)
    precip_now = _num(cur.get("precipitation"))
    wind_now = _num(cur.get("wind_speed_10m"))

    frost = analyze_frost_risk(
        {
            "time": (hourly.get("time") or [])[:72],
            "temperature_2m": (hourly.get("temperature_2m") or [])[:72],
            "dew_point_2m": (hourly.get("dew_point_2m") or [])[:72],
            "wind_speed_10m": (hourly.get("wind_speed_10m") or [])[:72],
        }
    )
    frost_name = t(lang, frost["frost_type"])
    hobby = role == "hobby"

    out: list[dict[str, Any]] = []

    def add(kind: str, name: str, icon: str, severity: str, text_key: str | None = None, **p: Any) -> None:
        text_key = text_key or f"ins.{name}.text"
        out.append(
            {
                "id": name,
                "type": kind,  # "recommend" | "avoid"
                "icon": icon,
                "severity": severity,
                "title": t(lang, f"ins.{name}.title"),
                "text": t(lang, text_key, **p),
            }
        )

    # ---- Weather-driven (everyone) ----
    frosty = min3 <= 0
    if frosty:
        add("avoid", "frost_avoid", "❄️", "danger", temp=_fmt(min3), frost=frost_name)
        if hobby:
            add("recommend", "frost_rec_hobby", "🧺", "warning")
        else:
            add("recommend", "frost_rec", "🧯", "warning")
    elif min3 <= 3:
        add("avoid", "frost_watch", "🌡️", "warning", temp=_fmt(min3))

    if max3 >= 35:
        add("avoid", "heat_avoid", "🔥", "danger", temp=_fmt(max3))
        add("recommend", "heat_rec", "💧", "warning")

    rainy = prob_today >= 60 or rain_today >= 5 or precip_now > 0
    if rainy:
        add("avoid", "rain_avoid", "🌧️", "warning", prob=int(prob_today), mm=_fmt(rain_today))
        add("recommend", "rain_rec", "🚰", "info")

    if max(wind_max, gusts) >= 30:
        add("avoid", "wind_avoid", "💨", "warning", wind=_fmt(max(wind_max, gusts)))
        add("recommend", "wind_rec", "🏗️", "info")

    if hum >= 85 and 8 <= temp <= 26:
        add("avoid", "fungal_avoid", "🍄", "warning", hum=int(hum), temp=_fmt(temp))
        add("recommend", "fungal_rec", "🔍", "info")

    dry = rain3 < 1 and max3 >= 22 and not rainy
    if dry:
        if not hobby and farm_size:
            add("recommend", "dry_rec", "🚿", "warning", "ins.dry_rec_farm.text",
                mm=_fmt(rain3), temp=_fmt(max3), size=_fmt(farm_size))
        else:
            add("recommend", "dry_rec", "🚿", "warning", mm=_fmt(rain3), temp=_fmt(max3))

    if not rainy and wind_now < 12 and wind_max < 20 and 10 <= temp <= 28 and prob_today < 30:
        add("recommend", "spray_rec", "🧪", "good", wind=_fmt(wind_now), temp=_fmt(temp))

    # ---- Crop-driven ----
    def names(crops: list[dict[str, Any]]) -> str:
        return ", ".join(c["name"] for c in crops)

    watched = crops_current or (crops_next if hobby else [])
    if watched:
        frost_hit = [c for c in watched if min3 <= c["frost_c"] + 1]
        if frost_hit:
            add("avoid", "crop_frost", "🌱", "danger", crops=names(frost_hit), temp=_fmt(min3))
        heat_hit = [c for c in watched if max3 >= c["heat_c"]]
        if heat_hit:
            add("avoid", "crop_heat", "🥵", "warning", crops=names(heat_hit), temp=_fmt(max3))
        if rain3 < 3 and not rainy:
            thirsty = [c for c in watched if c["water"] == "high"]
            if thirsty:
                add("recommend", "crop_water", "🪣", "warning", crops=names(thirsty))

    if not hobby:
        families_prev = {c["family"] for c in crops_last} | {c["family"] for c in crops_current}
        repeat = [c for c in crops_current if c["family"] in {x["family"] for x in crops_last}]
        repeat += [c for c in crops_next if c["family"] in families_prev and c not in repeat]
        # exclude legumes/cereals-after-legume? keep simple: every repeat is flagged
        if repeat:
            add("avoid", "rotation_avoid", "🔁", "warning", crops=names(repeat))
        elif (crops_last or crops_current or crops_next) and not any(
            c["family"] == "legume" for c in [*crops_current, *crops_next]
        ):
            add("recommend", "rotation_rec", "🫘", "info")

    if not any(i["type"] == "recommend" for i in out) and 10 <= temp <= 30 and not rainy and wind_max < 25:
        add("recommend", "good_rec", "🌤️", "good", temp=_fmt(temp))

    out.sort(key=lambda i: SEVERITY_ORDER.get(i["severity"], 9))
    return out
