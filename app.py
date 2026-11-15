import os
import gdown

# --- OTOMATİK DRIVE İNDİRME YAMASı ---
import os
import gdown
import streamlit as st

files = {
    "MOD13Q1.A2020097.h09v04.061.2020332100419.hdf": "1AUBcjJgitFUdlQPJuFQm-cDq-YMZmKPe",
    "SMAP_L3_SM_P_E_20200421_R19240_001.h5": "1_CsqYlqoHc_Jgee3girMowmzvMZ9nKpi",
    "NH_PROBABILISTIC_AM_FT_2020_day112.tif": "1Z3Lx2I84FrZLvu0_W4w4uD6gFrrvgA3G"
}

for filename, file_id in files.items():
    if not os.path.exists(filename):
        url = f"https://drive.google.com/uc?id={file_id}"
        with st.spinner(f"{filename} Google Drive'dan indiriliyor..."):
            gdown.download(url, filename, quiet=False)
# --- 3. TIF Dosyası (Uydu Haritası) ---
tif_filename = "NH_PROBABILISTIC_AM_FT_2020_day112.tif"
if not os.path.exists(tif_filename):
    tif_url = "https://drive.google.com/uc?id=1Z3Lx2I84FrZLvu0_W4w4uD6gFrrvgA3G"
    with st.spinner("Uydu TIF verisi Google Drive'dan indiriliyor..."):
        gdown.download(tif_url, tif_filename, quiet=False, fuzzy=True)
# -------------------------------------
import re
import time
import ssl
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

import html as html_lib

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from groq import Groq

# Opsiyonel kütüphaneler (yoksa uygulama yine çalışır)
try:
    import matplotlib.pyplot as plt
    MPL_AVAILABLE = True
except ImportError:
    MPL_AVAILABLE = False

try:
    import rasterio
    RASTERIO_AVAILABLE = True
except ImportError:
    RASTERIO_AVAILABLE = False

try:
    import h5py
    H5PY_AVAILABLE = True
except ImportError:
    H5PY_AVAILABLE = False

# --- 1. CONSTANTS ---
WELD_CENTER = (40.2827, -104.6872)          # (lat, lon)
WELD_BBOX = (-105.1, 40.0, -103.7, 41.0)    # west, south, east, north (approx.)
REFERENCE_SOIL_PCT = 14.2                   # used only when no readable SMAP file exists

CROPS = [
    "Corn", "Winter Wheat", "Spring Wheat", "Alfalfa", "Barley", "Sugar Beets",
    "Sorghum", "Soybeans", "Dry Beans", "Potatoes", "Oats", "Sunflowers", "Millet",
]
LAST_SEASON_OPTIONS = CROPS + ["Fallow (nothing planted)"]
LEGUMES = {"Alfalfa", "Soybeans", "Dry Beans"}

PAGES = [
    "1️⃣ Farmer Profile",
    "2️⃣ Weather & Crop Advice",
    "3️⃣ Soil Moisture",
    "4️⃣ Frost & Freeze/Thaw Map",
    "5️⃣ Plant Health",
    "6️⃣ Savings, Alerts & Sarp AI",
]

QUICK_PROMPTS = {
    "📈 NDVI chart": "Show me the plant greenness (NDVI) trend as a line chart.",
    "🥶 Frost risk": "Is there a frost risk for my crop right now? Show a frost chart.",
    "💧 Save water": "How can I save water and pumping costs this week?",
    "🔥 Temp heatmap": "Show the daily temperature as a heatmap.",
}

# --- 2. PAGE CONFIGURATION & STYLING ---
st.set_page_config(
    page_title="Weld County Drought Mitigation Assistant",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .stApp {
        background-color: #f4f7f5;
        font-family: 'Inter', sans-serif;
        color: #2c3e50;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f3d24 0%, #1b5e3b 100%);
        color: white;
    }
    [data-testid="stSidebar"] label, [data-testid="stSidebar"] .stMarkdown, [data-testid="stSidebar"] span {
        color: white !important;
    }
    div.stMetric {
        background: linear-gradient(135deg, #ffffff 0%, #f1f8f4 100%);
        padding: 18px;
        border-radius: 12px;
        box-shadow: 0 6px 12px rgba(15, 61, 36, 0.08);
        border-left: 6px solid #2e7d32;
        border-top: 1px solid #e2ece5;
    }
    h1, h2, h3, h4, h5, h6 {
        color: #0f3d24 !important;
        font-weight: 700 !important;
    }
    p, span, label, div {
        color: #2c3e50;
    }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] span {
        color: white !important;
    }
    .stAlert {
        background-color: #e8f5e9 !important;
        color: #0f3d24 !important;
        border-left: 5px solid #2e7d32 !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- 3. SESSION STATE ---
if "profile" not in st.session_state:
    st.session_state.profile = {
        "first_name": "",
        "last_name": "",
        "crop": "Corn",
        "last_crop": "Soybeans",
        "email": "",
        "county": "Weld County, CO (40.2827° N, -104.6872° W)",
        "submitted": False
    }
st.session_state.profile.setdefault("last_crop", "Soybeans")

if "ai_messages" not in st.session_state:
    st.session_state.ai_messages = [{
        "role": "assistant",
        "content": (
            "Hello! I'm **Sarp AI**, the smart farming assistant from Sarp Systems. "
            "Ask me about your fields, irrigation timing, frost risk or savings. "
            "I can also draw charts, for example: *\"Show soil moisture as a pie chart\"*."
        ),
        "charts": []
    }]


# --- 4. GENERAL HELPERS ---
def get_secret(name):
    """Önce .streamlit/secrets.toml, sonra ortam değişkeni."""
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name)


def ask_groq(system_prompt, history, retries=3):
    """Returns (reply, error). On failure, error holds the real reason."""
    api_key = get_secret("GROQ_API_KEY")
    if not api_key:
        return None, "GROQ_API_KEY not found. Please check your .streamlit/secrets.toml file."

    client = Groq(api_key=api_key)
    models = ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
    messages = [{"role": "system", "content": system_prompt}] + history[-8:]
    last_error = ""

    for model in models:
        for attempt in range(retries):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.4,
                    max_tokens=1500,
                    extra_body={"reasoning_effort": "low"},
                )
                text = resp.choices[0].message.content
                if text and text.strip():
                    return text, None
                last_error = f"{model} returned an empty answer."
                break
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                err = str(e).lower()
                if "401" in err or "invalid api key" in err:
                    return None, f"The API key is invalid or has been revoked. ({last_error})"
                if "429" in err or "rate" in err:
                    time.sleep(2 ** attempt)
                    continue
                break
    return None, last_error


def send_gmail_alert(recipient, sender, password, subject, body):
    try:
        clean_password = "".join(password.split())
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        context = ssl.create_default_context()
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls(context=context)
        server.login(sender, clean_password)
        server.send_message(msg)
        server.quit()
        return True, "✅ Alert email sent successfully!"
    except Exception as e:
        return False, f"❌ Could not send the email: {str(e)}"


def rotation_note(last_crop, crop):
    """Kısa, genel ekim nöbeti notu."""
    if not last_crop:
        return None
    if last_crop.startswith("Fallow"):
        return "The field was fallow last season, so it may have stored some soil moisture. Watch for early weeds."
    if last_crop == crop:
        return (f"{crop} was also grown last season. Planting the same crop again can build up pests and disease, "
                "so consider rotating if you can.")
    if last_crop in LEGUMES and crop not in LEGUMES:
        return (f"{last_crop} adds nitrogen to the soil, so you may need a little less nitrogen fertilizer for {crop}. "
                "A soil test will confirm.")
    return f"Moving from {last_crop} to {crop} is generally good for soil health and pest control."


def show_status(level, text):
    if level == "red":
        st.error(text)
    elif level == "orange":
        st.warning(text)
    elif level == "green":
        st.success(text)
    else:
        st.info(text)


def soil_status(pct):
    """(label, level, advice). Genel pratik eşikler, toprak tipine göre değişir."""
    if pct < 15:
        return "Very dry", "red", "Plants are likely under water stress. Irrigate soon, ideally at night."
    if pct < 25:
        return "Getting dry", "orange", "Plan your next irrigation. Focus water on the most sensitive growth stages."
    if pct < 35:
        return "Healthy", "green", "Soil moisture looks good. No extra irrigation is needed right now."
    return "Very wet", "blue", "The soil is wet. Hold off on irrigation and watch for waterlogging."


def ndvi_status(value):
    """NDVI için sade açıklama."""
    if value < 0.2:
        return "Very sparse", "red", "Almost bare ground or very weak plant cover."
    if value < 0.4:
        return "Sparse / early growth", "orange", "Plants are small or growing slowly."
    if value < 0.6:
        return "Moderate", "blue", "Plants are growing steadily."
    return "Dense and healthy", "green", "Strong, green plant cover."


# --- 5. DATA LOADERS ---
def load_nasa_power_csv():
    csv_files = sorted(Path(".").glob("POWER_Point_Daily*.csv"))
    if not csv_files:
        return None, "No NASA weather file (POWER_Point_Daily*.csv) found in the app folder."
    file_path = csv_files[0]
    try:
        skip_rows = 0
        with open(file_path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                if "-END HEADER-" in line:
                    skip_rows = idx + 1
                    break
        df = pd.read_csv(file_path, skiprows=skip_rows)
        df = df.replace(-999, np.nan)  # NASA POWER eksik veri işareti
        if {'YEAR', 'MO', 'DY'}.issubset(df.columns):
            df['DATE'] = pd.to_datetime(
                df[['YEAR', 'MO', 'DY']].rename(columns={'YEAR': 'year', 'MO': 'month', 'DY': 'day'})
            )
        return df, file_path.name
    except Exception as e:
        return None, str(e)


def get_weather():
    """Hava verisinin özetini döndürür (dosya yoksa None)."""
    df, info = load_nasa_power_csv()
    if df is None:
        return None
    min_col = "T2M_MIN" if "T2M_MIN" in df.columns else ("T2M" if "T2M" in df.columns else None)
    out = {
        "df": df,
        "file": info,
        "min_col": min_col,
        "avg_temp": float(df["T2M"].mean()) if "T2M" in df.columns else None,
        "min_temp": float(df[min_col].min()) if min_col else None,
        "frost_nights": int((df[min_col] < 0).sum()) if min_col else None,
        "rain_total": float(df["PRECTOTCORR"].sum()) if "PRECTOTCORR" in df.columns else None,
    }
    for k in ("avg_temp", "min_temp", "rain_total"):
        if out[k] is not None and np.isnan(out[k]):
            out[k] = None
    return out


def get_temp_series(kind):
    """kind: 'min' (en soğuk) veya 'avg' (ortalama). DATE indeksli Series veya None."""
    w = get_weather()
    if w is None or "DATE" not in w["df"].columns:
        return None
    col = w["min_col"] if kind == "min" else ("T2M" if "T2M" in w["df"].columns else None)
    if col is None:
        return None
    return w["df"].set_index("DATE")[col]


def parse_smap_date(name):
    m = re.search(r"(\d{8})", name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").strftime("%B %d, %Y")
    except ValueError:
        return None


def read_smap_summary():
    """SMAP dosyasından toprak nemi özetini okur.
    Döner: None (dosya yok) | {"error":..., "file":...} | {"mean_pct":..., ...}"""
    files = sorted(Path(".").glob("SMAP*.h5"))
    if not files:
        return None
    path = files[0]
    if not H5PY_AVAILABLE:
        return {"error": "The h5py library is not installed (pip install h5py).", "file": path.name}
    try:
        with h5py.File(path, "r") as f:
            candidates = []

            def visitor(name, obj):
                if isinstance(obj, h5py.Dataset) and name.split("/")[-1] in ("soil_moisture", "soil_moisture_pm"):
                    candidates.append(name)

            f.visititems(visitor)
            if not candidates:
                return {"error": "No soil moisture layer found inside the file.", "file": path.name}
            candidates.sort(key=lambda n: n.split("/")[-1] != "soil_moisture")  # önce sabah geçişi
            sm_path = candidates[0]
            base = sm_path.split("/")[-1]
            prefix = sm_path.rsplit("/", 1)[0] + "/" if "/" in sm_path else ""
            suffix = "_pm" if base.endswith("_pm") else ""

            sm = f[sm_path][()].astype("float64")
            valid = (sm > 0) & (sm <= 0.8)  # cm3/cm3; -9999 eksik veriyi eler

            lat_key, lon_key = prefix + "latitude" + suffix, prefix + "longitude" + suffix
            area = "the region covered by the satellite file"
            vals = sm[valid]
            if lat_key in f and lon_key in f:
                lat, lon = f[lat_key][()].astype("float64"), f[lon_key][()].astype("float64")
                if lat.shape == sm.shape and lon.shape == sm.shape:
                    w, s, e, n = WELD_BBOX
                    inbox = valid & (lat >= s) & (lat <= n) & (lon >= w) & (lon <= e)
                    if inbox.sum() > 0:
                        vals, area = sm[inbox], "Weld County"
                    else:
                        area = "a wider region (no valid readings directly over Weld County in this file)"
            if vals.size == 0:
                return {"error": "The file has no valid soil moisture readings.", "file": path.name}

            return {
                "file": path.name,
                "date": parse_smap_date(path.name),
                "mean_pct": float(vals.mean() * 100),
                "min_pct": float(vals.min() * 100),
                "max_pct": float(vals.max() * 100),
                "n": int(vals.size),
                "area": area,
            }
    except Exception as e:
        return {"error": str(e), "file": path.name}


def inspect_smap_h5():
    """Uzmanlar için dosya içeriği tablosu."""
    files = sorted(Path(".").glob("SMAP*.h5"))
    if not files or not H5PY_AVAILABLE:
        return None
    try:
        rows = []
        with h5py.File(files[0], "r") as f:
            def visitor(name, obj):
                if isinstance(obj, h5py.Dataset):
                    rows.append((name, str(obj.shape), str(obj.dtype)))
            f.visititems(visitor)
        return pd.DataFrame(rows[:25], columns=["Layer", "Size", "Type"])
    except Exception:
        return None


def get_field_snapshot():
    """Yapay zeka ve e-posta için güncel saha özeti."""
    smap = read_smap_summary()
    if smap and "mean_pct" in smap:
        soil, soil_note = smap["mean_pct"], f"satellite reading, {smap.get('date') or 'date unknown'}"
    else:
        soil, soil_note = REFERENCE_SOIL_PCT, "reference baseline value (no readable satellite file)"
    w = get_weather()
    return {
        "soil_pct": soil,
        "soil_note": soil_note,
        "min_temp": w["min_temp"] if w and w["min_temp"] is not None else -2.0,
        "frost_nights": w["frost_nights"] if w else None,
        "avg_temp": w["avg_temp"] if w else None,
        "rain_total": w["rain_total"] if w else None,
    }


# --- 6. CHART ENGINE (Sarp AI + pages) ---
CHART_KEYS = ["ndvi", "weather", "frost", "soil", "savings"]

KEY_ALIASES = {
    "hava": "weather", "temperature": "weather", "temp": "weather", "rain": "weather",
    "don": "frost", "freeze": "frost",
    "nem": "soil", "moisture": "soil",
    "maliyet": "savings", "cost": "savings", "costs": "savings", "saving": "savings",
}

TYPE_ALIASES = {
    "line": "line", "trend": "line", "cizgi": "line", "çizgi": "line",
    "bar": "bar", "column": "bar", "sutun": "bar", "sütun": "bar", "cubuk": "bar", "çubuk": "bar",
    "area": "area", "alan": "area",
    "scatter": "scatter", "dot": "scatter", "dots": "scatter", "nokta": "scatter",
    "pie": "pie", "donut": "pie", "daire": "pie", "pasta": "pie",
    "heatmap": "heatmap", "heat": "heatmap", "calendar": "heatmap", "isi": "heatmap", "ısı": "heatmap",
}

CHART_WORDS = ["chart", "graph", "plot", "visual", "diagram", "heatmap", "heat map",
               "pie", "grafik", "çiz", "ciz"]
DATA_HINTS = [
    ("ndvi", ["ndvi", "evi", "vegetation", "greenness", "plant health", "bitki"]),
    ("frost", ["frost", "freez", "coldest", "cold night", "donma"]),
    ("soil", ["soil", "moisture", "smap", "toprak", "nem"]),
    ("weather", ["weather", "temperature", "temp", "rain", "precip", "sıcaklık", "sicaklik", "yağış", "yagis"]),
    ("savings", ["saving", "save", "cost", "pump", "electric", "water use", "irrigation", "maliyet", "tasarruf"]),
]
TYPE_HINTS = [
    ("heatmap", ["heatmap", "heat map", "calendar", "ısı haritası", "isi haritasi"]),
    ("pie", ["pie", "donut", "share", "daire", "pasta"]),
    ("area", ["area"]),
    ("scatter", ["scatter", "dot", "dots", "points", "nokta"]),
    ("bar", ["bar", "bars", "column", "columns", "sütun", "sutun", "çubuk"]),
    ("line", ["line", "trend", "çizgi", "cizgi"]),
]


def _has_word(text, words):
    pattern = r"\b(?:%s)\b" % "|".join(re.escape(w) for w in words)
    return re.search(pattern, text) is not None


def _has_prefix(text, words):
    pattern = r"\b(?:%s)" % "|".join(re.escape(w) for w in words)
    return re.search(pattern, text) is not None


def wants_chart(text):
    t = (text or "").lower()
    return any(w in t for w in CHART_WORDS)


def infer_type(text):
    t = (text or "").lower()
    for ctype, words in TYPE_HINTS:
        if _has_word(t, words):
            return ctype
    return None


def infer_charts(text):
    """Model etiketi unutursa, kullanıcının cümlesinden grafik çıkarır."""
    t = (text or "").lower()
    ctype = infer_type(t) or "line"
    charts = []
    for key, words in DATA_HINTS:
        if _has_prefix(t, words):
            charts.append({"key": key, "type": ctype})
    return charts[:2]


TAG_RE = re.compile(r"\[(?:CHART|GRAFIK)\s*:\s*([^\]]*)\]", re.IGNORECASE)


def split_reply_and_charts(text, user_prompt=""):
    """Cevaptaki [CHART: veri, tür] etiketlerini ayırır. (temiz_metin, grafik_listesi) döner."""
    text = text or ""
    user_type = infer_type(user_prompt)
    charts = []
    for m in TAG_RE.finditer(text):
        parts = [p.strip().lower() for p in re.split(r"[,;]", m.group(1))]
        key = KEY_ALIASES.get(parts[0], parts[0]) if parts and parts[0] else ""
        if len(parts) > 1 and parts[1]:
            ctype = TYPE_ALIASES.get(parts[1], "line")
        else:
            ctype = user_type or "line"
        item = {"key": key, "type": ctype}
        if key in CHART_KEYS and item not in charts:
            charts.append(item)
    clean = TAG_RE.sub("", text).strip()
    if not charts and wants_chart(user_prompt):
        charts = infer_charts(user_prompt)
    return clean, charts[:2]


def get_chart_data(chart_key):
    """Grafik verisi: {"df", "pie", "title", "note", "calendar"} veya {"error": ...}."""
    if chart_key == "ndvi":
        df = pd.DataFrame({
            'April 2020 (day)': [1, 8, 16, 24, 30],
            'NDVI (greenness)': [0.32, 0.30, 0.28, 0.31, 0.29],
            'EVI (canopy)': [0.22, 0.21, 0.19, 0.20, 0.19]
        }).set_index('April 2020 (day)')
        pie = df['NDVI (greenness)'].copy()
        pie.index = [f"Day {d}" for d in pie.index]
        return {"df": df, "pie": pie, "calendar": None,
                "title": "🌿 Plant greenness (NDVI and EVI), April 2020",
                "note": "Sample baseline values. Higher means greener, healthier plants."}

    if chart_key in ("weather", "frost"):
        w = get_weather()
        if w is None:
            return {"error": "The NASA weather file was not found, so this chart can't be drawn."}
        raw = w["df"]
        idx = raw["DATE"] if "DATE" in raw.columns else raw.index

        if chart_key == "weather":
            cols = {}
            if "T2M" in raw.columns:
                cols["Average temperature (°C)"] = raw["T2M"].values
            if "PRECTOTCORR" in raw.columns:
                cols["Rainfall (mm)"] = raw["PRECTOTCORR"].values
            if not cols:
                return {"error": "No temperature or rainfall columns were found in the weather file."}
            df = pd.DataFrame(cols, index=idx)
            pie = None
            if "Rainfall (mm)" in df.columns:
                if isinstance(df.index, pd.DatetimeIndex):
                    pie = df["Rainfall (mm)"].resample("W").sum()
                    pie.index = [d.strftime("%b %d") for d in pie.index]
                else:
                    pie = df["Rainfall (mm)"].head(10)
            return {"df": df, "pie": pie, "calendar": get_temp_series("avg"),
                    "title": "🌦️ Temperature and rainfall",
                    "note": "Pie chart shows how rainfall was split across weeks."}

        if w["min_col"] is None:
            return {"error": "No temperature columns were found in the weather file."}
        df = pd.DataFrame({
            "Coldest temperature of the day (°C)": raw[w["min_col"]].values,
        }, index=idx)
        df["Freezing point (0 °C)"] = 0.0
        frost = int((raw[w["min_col"]] < 0).sum())
        safe = int((raw[w["min_col"]] >= 0).sum())
        return {"df": df, "pie": pd.Series({"Frost nights": frost, "Frost-free nights": safe}),
                "calendar": get_temp_series("min"),
                "title": "🥶 Frost check: coldest temperature each day",
                "note": "Anything below the 0 °C line can damage young plants."}

    if chart_key == "soil":
        snap = get_field_snapshot()
        mean = snap["soil_pct"]
        smap = read_smap_summary()
        if smap and "mean_pct" in smap:
            lo, hi = smap["min_pct"], smap["max_pct"]
        else:
            lo, hi = mean, mean
        df = pd.DataFrame({
            "Soil moisture (%)": [lo, mean, hi],
            "Dry-soil warning level (15%)": [15, 15, 15],
        }, index=["Driest spot", "Average", "Wettest spot"])
        return {"df": df, "pie": pd.Series({"Water": mean, "Soil and air": max(100 - mean, 0)}),
                "calendar": None,
                "title": "💧 Soil moisture",
                "note": f"Source: {snap['soil_note']}."}

    if chart_key == "savings":
        df = pd.DataFrame({
            'Scenario': ['Water: normal', 'Water: 20% less', 'Pump energy: normal', 'Pump energy: night tariff'],
            'Cost index': [100, 80, 100, 65]
        }).set_index('Scenario')
        return {"df": df, "pie": df['Cost index'], "calendar": None,
                "title": "💰 Savings plan",
                "note": "Normal use = 100. Based on 20% less water and about 35% lower pump energy cost at night."}

    return {"error": "Unknown chart."}


def draw_calendar_heatmap(series, unit="°C"):
    """Günlük değerleri takvim biçiminde ısı haritası olarak çizer."""
    series = series.dropna()
    if series.empty:
        st.info("No temperature readings are available for a heatmap.")
        return
    from matplotlib.colors import TwoSlopeNorm

    first = series.index.min().normalize()
    offset = first.weekday()
    days = (series.index.max().normalize() - first).days + 1
    rows = (offset + days + 6) // 7
    grid = np.full((rows, 7), np.nan)
    for d, v in series.items():
        pos = offset + (d.normalize() - first).days
        grid[pos // 7, pos % 7] = v

    vmin, vmax = float(np.nanmin(grid)), float(np.nanmax(grid))
    norm = TwoSlopeNorm(vmin=vmin, vcenter=0, vmax=vmax) if vmin < 0 < vmax else None
    fig, ax = plt.subplots(figsize=(7, max(2.8, 0.85 * rows)))
    im = ax.imshow(grid, cmap="RdYlBu_r", norm=norm, aspect="auto")
    ax.set_xticks(range(7))
    ax.set_xticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    ax.xaxis.tick_top()
    ax.set_yticks(range(rows))
    ax.set_yticklabels([f"Week {i + 1}" for i in range(rows)])
    for r in range(rows):
        for c in range(7):
            v = grid[r, c]
            if np.isnan(v):
                continue
            day = (first + pd.Timedelta(days=r * 7 + c - offset)).day
            level = im.norm(v)
            color = "white" if (level < 0.2 or level > 0.8) else "black"
            ax.text(c, r, f"{day}\n{v:.0f}°", ha="center", va="center", fontsize=8, color=color)
    fig.colorbar(im, ax=ax, label=f"Temperature ({unit})")
    st.pyplot(fig)
    plt.close(fig)


def render_chart(chart_key, chart_type="line"):
    """Veriyi istenen türde çizer: line, bar, area, scatter, pie, heatmap."""
    data = get_chart_data(chart_key)
    if "error" in data:
        st.info(data["error"])
        return
    st.markdown(f"**{data['title']}**")
    if data.get("note"):
        st.caption(data["note"])
    df = data["df"]

    if chart_type == "heatmap":
        if data.get("calendar") is not None and MPL_AVAILABLE:
            draw_calendar_heatmap(data["calendar"])
            st.caption("Blue = freezing, red = warm. Each square shows the day of the month and the temperature.")
            return
        st.caption("A heatmap isn't available for this data, so a bar chart is shown instead.")
        chart_type = "bar"

    if chart_type == "bar":
        st.bar_chart(df)
    elif chart_type == "area":
        st.area_chart(df)
    elif chart_type == "scatter":
        if MPL_AVAILABLE:
            fig, ax = plt.subplots(figsize=(8, 4))
            for col in df.columns:
                ax.scatter(df.index, df[col], label=str(col), s=45)
            ax.legend()
            ax.grid(alpha=0.3)
            fig.autofmt_xdate()
            st.pyplot(fig)
            plt.close(fig)
        else:
            st.scatter_chart(df)
    elif chart_type == "pie":
        pie = data.get("pie")
        if pie is None or not MPL_AVAILABLE:
            st.warning("A pie chart needs matplotlib (pip install matplotlib) and numeric data.")
            return
        pie = pie[pie > 0]
        if pie.empty:
            st.info("There are no positive values to show in a pie chart.")
            return
        n = len(pie)
        colors = plt.cm.Greens([0.25 + 0.4 * i / max(n - 1, 1) for i in range(n)])
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.pie(pie.values, labels=[str(i) for i in pie.index], autopct="%1.1f%%",
               startangle=90, colors=colors)
        ax.axis("equal")
        st.pyplot(fig)
        plt.close(fig)
    else:
        st.line_chart(df)


# --- 7. FREEZE/THAW MAP ---
def build_freeze_thaw_map(tif_path):
    """NSIDC rasterından Weld County çevresini kesip ısı haritası üretir. (fig, bilgi) döner."""
    from rasterio.warp import transform, transform_bounds
    from rasterio.windows import Window, bounds as window_bounds

    with rasterio.open(tif_path) as src:
        data, extent, marker, weld_value = None, None, None, None
        region = "the full map"
        if src.crs is not None:
            try:
                w, s, e, n = WELD_BBOX
                buf = 4.0
                b = transform_bounds("EPSG:4326", src.crs, w - buf, s - buf, e + buf, n + buf, densify_pts=21)
                win = src.window(*b)
                col0, row0 = max(int(np.floor(win.col_off)), 0), max(int(np.floor(win.row_off)), 0)
                col1 = min(int(np.ceil(win.col_off + win.width)), src.width)
                row1 = min(int(np.ceil(win.row_off + win.height)), src.height)
                if col1 - col0 >= 2 and row1 - row0 >= 2:
                    win = Window(col0, row0, col1 - col0, row1 - row0)
                    data = src.read(1, window=win, masked=True)
                    left, bottom, right, top = window_bounds(win, src.transform)
                    extent = (left, right, bottom, top)
                    xs, ys = transform("EPSG:4326", src.crs, [WELD_CENTER[1]], [WELD_CENTER[0]])
                    marker = (xs[0], ys[0])
                    row, col = src.index(xs[0], ys[0])
                    if 0 <= row < src.height and 0 <= col < src.width:
                        px = src.read(1, window=Window(col, row, 1, 1), masked=True)
                        if not np.ma.is_masked(px[0, 0]):
                            weld_value = float(px[0, 0])
                    region = "Weld County and its surroundings"
            except Exception:
                data, extent, marker, weld_value = None, None, None, None
                region = "the full map"
        if data is None:
            data = src.read(1, masked=True)

    cmap = plt.get_cmap("RdYlBu_r").copy()
    cmap.set_bad("lightgrey")
    fig, ax = plt.subplots(figsize=(7, 5))
    im = ax.imshow(data, cmap=cmap, extent=extent, interpolation="nearest")
    if marker:
        ax.plot(marker[0], marker[1], marker="*", color="black", markersize=18, markeredgecolor="white")
        ax.annotate("Weld County", marker, textcoords="offset points", xytext=(10, 10),
                    fontweight="bold", bbox=dict(boxstyle="round", fc="white", alpha=0.8))
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("Satellite freeze/thaw heatmap")
    fig.colorbar(im, ax=ax, label="Map value (see the note below)")
    info = {
        "weld_value": weld_value,
        "region": region,
        "min": float(data.min()) if data.count() else None,
        "max": float(data.max()) if data.count() else None,
    }
    return fig, info


# --- 7b. WEATHER HERO CARD (Page 2) ---
HERO_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Inter,"Segoe UI",system-ui,-apple-system,sans-serif;background:transparent;color:#fff}
.hero{position:relative;overflow:hidden;border-radius:26px;height:560px;padding:26px 30px;background:__SKY__;box-shadow:0 18px 40px rgba(15,61,36,.25)}
.cloud{position:absolute;border-radius:50%;filter:blur(38px);opacity:.8}
.c1{width:520px;height:210px;left:-60px;top:-70px;background:__C1__}
.c2{width:480px;height:230px;left:34%;top:-95px;background:__C2__}
.c3{width:380px;height:180px;right:-40px;top:20px;background:__C3__}
.field{position:absolute;left:0;right:0;bottom:0;height:33%;background:#3f6b36;background:repeating-linear-gradient(98deg,rgba(0,0,0,0) 0 26px,rgba(0,0,0,.12) 26px 30px),linear-gradient(180deg,#52803f 0%,#2f5a2b 100%)}
.field:before{content:"";position:absolute;left:0;right:0;top:-18px;height:36px;background:__HORIZON__;filter:blur(14px)}
.top{position:relative;height:46px}
.welcome{float:left}.welcome small{display:block;font-size:12px;opacity:.75}
.welcome b{font-size:15px}
.pill{float:right;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.28);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);padding:6px 14px;border-radius:999px;font-size:12px}
.grid{position:static}
.left{position:absolute;left:30px;top:84px;bottom:26px;width:61%}
.tag{display:inline-block;background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.3);padding:5px 12px;border-radius:999px;font-size:11px;margin-bottom:12px}
.title{font-size:46px;line-height:1.04;font-weight:700;letter-spacing:-.5px;text-shadow:0 2px 14px rgba(0,0,0,.35)}
.desc{margin-top:12px;font-size:13px;line-height:1.5;max-width:480px;opacity:.95;text-shadow:0 1px 8px rgba(0,0,0,.45)}
.strip{position:absolute;left:0;right:0;bottom:0}
.days{display:table;table-layout:fixed;width:100%;text-align:center}
.d{display:table-cell;font-size:20px;opacity:.85;padding-bottom:4px;text-shadow:0 1px 8px rgba(0,0,0,.4)}
.d .ic{font-size:13px;margin-left:3px}
.d.hl{opacity:1;font-weight:700;font-size:26px}
svg{display:block;width:100%;height:auto}
.labels{display:table;table-layout:fixed;width:100%;text-align:center;font-size:12px;opacity:.9;margin-top:2px;text-shadow:0 1px 6px rgba(0,0,0,.5)}
.labels div{display:table-cell}.labels .hl{font-weight:700}
.cap{font-size:10px;opacity:.75;margin-top:8px;text-shadow:0 1px 6px rgba(0,0,0,.5)}
.right{position:absolute;right:30px;top:84px;width:31%}
.card{background:rgba(255,255,255,.17);border:1px solid rgba(255,255,255,.3);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);border-radius:18px;padding:13px 18px;margin-bottom:12px;box-shadow:0 8px 24px rgba(0,0,0,.18)}
.big{padding:16px 20px}
.loc{font-size:13px;opacity:.92}
.temp{font-size:56px;font-weight:600;line-height:1.05;margin:4px 0 8px}
.stats{font-size:11.5px;opacity:.95}.stats span{display:inline-block;margin-right:12px}
.row{display:table;width:100%}.row>div{display:table-cell;vertical-align:middle}
.row .nm{font-size:11px;opacity:.78}
.row .lb{font-size:15px;font-weight:600;margin-top:2px}
.row .val{font-size:24px;font-weight:600;white-space:nowrap;text-align:right}
@media (max-width:760px){.hero{height:auto;min-height:560px}.left,.right{position:static;width:auto}.strip{position:static;margin-top:20px}.right{margin-top:16px}.title{font-size:34px}}
</style></head><body><div class="hero">
<div class="cloud c1"></div><div class="cloud c2"></div><div class="cloud c3"></div><div class="field"></div>
<div class="top"><div class="welcome"><small>Welcome</small><b>__NAME__</b></div><div class="pill">📍 Weld County, Colorado</div></div>
<div class="grid">
<div class="left">
<div class="tag">Field Weather Snapshot</div>
<div class="title">__TITLE1__<br>__TITLE2__</div>
<div class="desc">__DESC__</div>
<div class="strip">
<div class="days">__DAYS__</div>
<svg viewBox="0 0 600 80" xmlns="http://www.w3.org/2000/svg"><path d="__PATH__" fill="none" stroke="rgba(255,255,255,.85)" stroke-width="2.5" stroke-linecap="round"/><circle cx="__HX__" cy="__HY__" r="14" fill="rgba(255,255,255,.28)"/><circle cx="__HX__" cy="__HY__" r="6" fill="#fff"/></svg>
<div class="labels">__LABELS__</div>
<div class="cap">Daily average temperature, last __N__ days in your weather file. Highlighted day = coldest.</div>
</div></div>
<div class="right">
<div class="card big"><div class="loc">📍 Weld County, CO · latest day</div><div class="temp">__TEMP__° C</div>
<div class="stats"><span>💧 __SOIL__% soil</span><span>🌧️ __RAIN__ mm rain</span><span>❄️ __FROST__ frost day(s)</span></div></div>
<div class="card"><div class="row"><div><div class="nm">Soil Moisture</div><div class="lb">__SOIL_LABEL__</div></div><div class="val">__SOIL__%</div></div></div>
<div class="card"><div class="row"><div><div class="nm">Plant Greenness (NDVI)</div><div class="lb">__NDVI_LABEL__</div></div><div class="val">__NDVI__</div></div></div>
<div class="card"><div class="row"><div><div class="nm">Best Irrigation Time</div><div class="lb">Night, 10 PM to 6 AM</div></div><div class="val">−35%</div></div></div>
</div></div></div></body></html>"""

HERO_SKIES = {
    # (gökyüzü, bulut1, bulut2, bulut3, ufuk ışığı)
    "frost": ("linear-gradient(160deg,#17303a 0%,#2c5260 48%,#5b8493 100%)",
              "rgba(10,25,33,.85)", "rgba(20,45,55,.8)", "rgba(120,160,175,.55)", "rgba(190,225,235,.55)"),
    "dry":   ("linear-gradient(160deg,#3a2f22 0%,#7a5a36 48%,#c79a5c 100%)",
              "rgba(45,32,20,.8)", "rgba(90,64,36,.75)", "rgba(230,190,130,.5)", "rgba(255,214,150,.6)"),
    "ok":    ("linear-gradient(160deg,#1c3f4f 0%,#3b7488 48%,#8dc0cf 100%)",
              "rgba(30,60,72,.7)", "rgba(70,115,130,.65)", "rgba(240,248,250,.5)", "rgba(255,255,255,.55)"),
}


def build_weather_hero_html(w, snap, name):
    """Hava dosyası + saha verilerinden 'hero' hava kartının HTML'ini üretir (veri yoksa None)."""
    df = w["df"].copy()
    temp_col = "T2M" if "T2M" in df.columns else w["min_col"]
    if temp_col is None:
        return None
    min_col = w["min_col"] or temp_col
    df = df.dropna(subset=[temp_col]).tail(6)
    if df.empty:
        return None

    temps = [float(x) for x in df[temp_col]]
    mins = [float(x) for x in df[min_col].fillna(df[temp_col])]
    rains = [float(x) for x in df["PRECTOTCORR"].fillna(0)] if "PRECTOTCORR" in df.columns else [0.0] * len(df)
    if "DATE" in df.columns:
        labels = [(d.strftime("%a"), d.strftime("%b %d")) for d in df["DATE"]]
    else:
        labels = [(f"Day {i + 1}", "") for i in range(len(df))]

    n = len(temps)
    frost_days = sum(1 for m in mins if m < 0)
    rain_total = sum(rains)
    coldest = min(mins)
    soil = snap["soil_pct"]
    soil_label = soil_status(soil)[0]
    ndvi_now = float(get_chart_data("ndvi")["df"]["NDVI (greenness)"].iloc[-1])
    ndvi_label = ndvi_status(ndvi_now)[0]

    # Başlık ve açıklama: önce don, sonra kuru toprak, sonra iyi durum
    if frost_days > 0:
        state, t1, t2 = "frost", "Frost Risk", "for Young Plants"
        desc = (f"The coldest reading in the last {n} days was {coldest:.0f}°C, with {frost_days} freezing day(s). "
                f"Protect seedlings and delay frost-sensitive planting. Soil moisture is {soil:.1f}% ({soil_label.lower()}).")
    elif soil < 15:
        state, t1, t2 = "dry", "Dry Conditions", "Irrigate Tonight"
        desc = (f"Soil moisture is only {soil:.1f}%, so plants are likely short of water. "
                f"Irrigate at night (10 PM to 6 AM) to lose less water to evaporation. Rain in the last {n} days: {rain_total:.1f} mm.")
    elif soil < 25:
        state, t1, t2 = "dry", "Getting Dry", "Plan Your Watering"
        desc = (f"Soil moisture is {soil:.1f}% and falling toward the dry zone. Plan the next irrigation in the coming days. "
                f"Rain in the last {n} days: {rain_total:.1f} mm.")
    else:
        state, t1, t2 = "ok", "Good Field", "Conditions"
        desc = (f"No freezing days and soil moisture looks healthy at {soil:.1f}%. "
                f"No extra irrigation is needed right now. Rain in the last {n} days: {rain_total:.1f} mm.")

    # Sıcaklık eğrisi (SVG)
    W = 600
    lo, hi = min(temps), max(temps)
    ys = [58.0 if hi == lo else 62.0 - (t - lo) / (hi - lo) * 44.0 for t in temps]
    pts = [((i + 0.5) * W / n, ys[i]) for i in range(n)]
    path = f"M 0 {pts[0][1]:.1f} L {pts[0][0]:.1f} {pts[0][1]:.1f}"
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        xm = (x0 + x1) / 2
        path += f" C {xm:.1f} {y0:.1f} {xm:.1f} {y1:.1f} {x1:.1f} {y1:.1f}"
    path += f" L {W} {pts[-1][1]:.1f}"
    hl = mins.index(min(mins))  # en soğuk gün vurgulanır

    day_html, label_html = "", ""
    for i in range(n):
        icon = "❄️" if mins[i] < 0 else ("🌧️" if rains[i] > 1 else "☀️")
        cls = "d hl" if i == hl else "d"
        day_html += f'<div class="{cls}">{temps[i]:.0f}°<span class="ic">{icon}</span></div>'
        cls2 = ' class="hl"' if i == hl else ""
        label_html += f"<div{cls2}>{labels[i][0]}<br>{labels[i][1]}</div>"

    sky, c1, c2, c3, horizon = HERO_SKIES[state]
    values = {
        "__SKY__": sky, "__C1__": c1, "__C2__": c2, "__C3__": c3, "__HORIZON__": horizon,
        "__N__": str(n), "__NAME__": html_lib.escape(name),
        "__TITLE1__": t1, "__TITLE2__": t2, "__DESC__": html_lib.escape(desc),
        "__DAYS__": day_html, "__LABELS__": label_html, "__PATH__": path,
        "__HX__": f"{pts[hl][0]:.1f}", "__HY__": f"{pts[hl][1]:.1f}",
        "__TEMP__": f"{temps[-1]:.0f}", "__SOIL__": f"{soil:.1f}", "__RAIN__": f"{rain_total:.1f}",
        "__FROST__": str(frost_days), "__SOIL_LABEL__": soil_label,
        "__NDVI__": f"{ndvi_now:.2f}", "__NDVI_LABEL__": ndvi_label,
    }
    out = HERO_TEMPLATE
    for key, val in values.items():
        out = out.replace(key, val)
    return out


# --- 8. SIDEBAR ---
with st.sidebar:
    st.markdown("## 🌾 Sarp Systems")
    st.caption("Smart Farming Assistant · Weld County")
    st.divider()

    selected = st.radio("Where would you like to go?", PAGES)

    st.divider()
    p = st.session_state.profile
    if p["submitted"]:
        st.markdown(f"👤 **{p['first_name']} {p['last_name']}**")
        st.markdown(f"🌱 This season: **{p['crop']}**")
        st.markdown(f"🕒 Last season: **{p['last_crop']}**")
        st.divider()
    st.info(
        "**Area:** Weld County, Colorado, USA\n\n"
        "📍 **Location:** 40.2827° N, 104.6872° W\n\n"
        "🌱 **Reference period:** April 2020 drought"
    )

# --- 9. PAGE 1: FARMER PROFILE ---
if selected == PAGES[0]:
    st.title("🌾 Weld County Drought Mitigation & Smart Irrigation Assistant")
    st.markdown("### Step 1: Tell us about your farm")
    st.write("Fill in your details so the app can give crop-specific advice and send you alert emails when you are away from the field.")

    with st.expander("ℹ️ How to use this app"):
        st.markdown("""
        1. **Farmer Profile:** enter your name, email and crops (this page).
        2. **Weather & Crop Advice:** temperature, rainfall and what to plant.
        3. **Soil Moisture:** how wet your soil is and whether to irrigate.
        4. **Frost & Freeze/Thaw Map:** which nights were freezing, plus a satellite map.
        5. **Plant Health:** how green and healthy your plants look from space.
        6. **Savings, Alerts & Sarp AI:** ways to cut costs, email alerts, and a chat assistant that can draw charts.
        """)

    p = st.session_state.profile
    with st.form("onboarding_form"):
        c1, c2 = st.columns(2)
        with c1:
            fname = st.text_input("First name", value=p["first_name"])
            crop_type = st.selectbox(
                "Crop you are growing this season", CROPS,
                index=CROPS.index(p["crop"]) if p["crop"] in CROPS else 0,
                help="The main crop in your field right now."
            )
        with c2:
            lname = st.text_input("Last name", value=p["last_name"])
            last_crop = st.selectbox(
                "Crop you grew last season", LAST_SEASON_OPTIONS,
                index=LAST_SEASON_OPTIONS.index(p["last_crop"]) if p["last_crop"] in LAST_SEASON_OPTIONS else 0,
                help="Knowing last year's crop helps with rotation advice. Choose 'Fallow' if nothing was planted."
            )
        email = st.text_input("Gmail address (for alerts)", value=p["email"])
        st.text_input("Your area (fixed)", value=p["county"], disabled=True)

        submitted = st.form_submit_button("Save and open my dashboard 🚀")
        if submitted:
            if fname and lname and email:
                st.session_state.profile.update({
                    "first_name": fname, "last_name": lname, "crop": crop_type,
                    "last_crop": last_crop, "email": email, "submitted": True
                })
                st.success("✅ Profile saved! Now open step 2 from the menu on the left.")
            else:
                st.error("⚠️ Please fill in your first name, last name and Gmail address.")

    if st.session_state.profile["submitted"]:
        p = st.session_state.profile
        st.divider()
        st.info(f"👤 **{p['first_name']} {p['last_name']}**  |  🌱 This season: **{p['crop']}**  |  "
                f"🕒 Last season: **{p['last_crop']}**  |  📧 Alerts go to `{p['email']}`")
        note = rotation_note(p["last_crop"], p["crop"])
        if note:
            st.success(f"🔄 **Crop rotation tip:** {note}")

# --- 10. PAGE 2: WEATHER & CROP ADVICE ---
elif selected == PAGES[1]:
    st.title("🌦️ Weather & Crop Advice")
    st.caption("What the weather has been like and what that means for your planting decisions.")

    _hero_w = get_weather()
    if _hero_w is not None:
        _hero = build_weather_hero_html(
            _hero_w, get_field_snapshot(), st.session_state.profile["first_name"] or "Farmer"
        )
        if _hero:
            components.html(_hero, height=590)

    st.error("🚨 **April 2020 reference status: severe drought.** Use deficit irrigation across the Weld County basin "
             "(this means applying less water, only at the growth stages when plants need it most).")

    w = get_weather()
    if w is not None:
        m1, m2, m3 = st.columns(3)
        if w["avg_temp"] is not None:
            m1.metric("Average temperature", f"{w['avg_temp']:.1f} °C")
        if w["min_temp"] is not None:
            m2.metric("Coldest day", f"{w['min_temp']:.1f} °C",
                      delta="Frost risk" if w["min_temp"] < 0 else "No frost",
                      delta_color="inverse")
        if w["rain_total"] is not None:
            m3.metric("Total rainfall", f"{w['rain_total']:.1f} mm")

        if w["frost_nights"]:
            st.warning(f"🥶 There were **{w['frost_nights']} freezing day(s)** in this period. "
                       "Young plants can be damaged below 0 °C, so protect seedlings or delay planting.")

        st.divider()
        p = st.session_state.profile
        note = rotation_note(p["last_crop"], p["crop"]) if p["submitted"] else None
        if note:
            st.success(f"🔄 **Rotation tip for your field:** {note}")

        st.subheader("🌱 What to plant and what to avoid")
        col_rec1, col_rec2 = st.columns(2)
        with col_rec1:
            st.success("### ✅ Good choices")
            st.markdown("""
            * **Winter wheat and barley:** handle cold April nights well.
            * **Alfalfa:** deep roots reach water when the surface is dry.
            """)
        with col_rec2:
            st.error("### ⛔ Better to avoid")
            st.markdown("""
            * **Early planting of frost-sensitive crops:** young corn and warm-season vegetables can be hurt by late frost.
            * **Watering in the heat of the day:** much of the water evaporates before plants can use it.
            """)

        st.divider()
        st.subheader("📈 Daily temperature and rainfall")
        render_chart("weather", "line")
    else:
        st.warning("⚠️ The NASA weather file was not found in the app folder, so weather numbers can't be shown.")

# --- 11. PAGE 3: SOIL MOISTURE ---
elif selected == PAGES[2]:
    st.title("💧 Soil Moisture")
    st.caption("How wet the soil is in your area, measured from space by NASA's SMAP satellite.")

    smap = read_smap_summary()
    from_file = bool(smap and "mean_pct" in smap)
    if from_file:
        mean, lo, hi = smap["mean_pct"], smap["min_pct"], smap["max_pct"]
    else:
        mean, lo, hi = REFERENCE_SOIL_PCT, None, None

    label, level, advice = soil_status(mean)

    c1, c2, c3 = st.columns(3)
    c1.metric("Average soil moisture", f"{mean:.1f}%")
    if lo is not None:
        c2.metric("Driest spot", f"{lo:.1f}%")
        c3.metric("Wettest spot", f"{hi:.1f}%")
    else:
        c2.metric("Condition", label)

    st.progress(float(min(max(mean / 50, 0.0), 1.0)), text="Scale: 0% (bone dry) to 50% or more (waterlogged)")
    show_status(level, f"**{label}.** {advice}")

    if from_file:
        st.caption(f"📅 Reading date: {smap.get('date') or 'unknown'}  ·  📍 Area: {smap['area']}  ·  "
                   f"🛰️ Based on {smap['n']} satellite readings")
    else:
        st.info("No readable satellite file was found, so the app is showing the April 2020 reference value "
                f"({REFERENCE_SOIL_PCT}%)." + (f" Reason: {smap['error']}" if smap and "error" in smap else ""))

    crop = st.session_state.profile["crop"]
    st.markdown(f"#### What this means for your {crop}")
    tips = {
        "red": ["Irrigate soon. Night irrigation (10 PM to 6 AM) loses less water to evaporation.",
                "Give water first to the most sensitive growth stages: germination, flowering and grain or pod fill.",
                "Keep crop residue on the soil as mulch to slow evaporation."],
        "orange": ["Plan your next irrigation within the next few days.",
                   "Check a few spots in the field by hand: if soil crumbles dry a few inches down, water.",
                   "Avoid unnecessary tillage that dries the soil."],
        "green": ["No extra irrigation is needed right now.",
                  "Re-check after a few hot or windy days.",
                  "This is a good time to work on other tasks like weed control."],
        "blue": ["Pause irrigation until the soil dries a little.",
                 "Check low spots for standing water.",
                 "Wet soil can slow field work, so avoid heavy machinery if possible."],
    }
    for tip in tips[level]:
        st.markdown(f"- {tip}")

    st.divider()
    st.subheader("📊 See it as a chart")
    chart_choice = st.radio("Chart type", ["Bar", "Pie", "Line"], horizontal=True)
    render_chart("soil", {"Bar": "bar", "Pie": "pie", "Line": "line"}[chart_choice])

    with st.expander("📘 How to read these numbers"):
        st.markdown("""
        * **Soil moisture %** is the share of the soil's volume that is filled with water.
        * The satellite only senses the **top 5 cm (about 2 inches)** of soil, so deeper roots may have more or less water than shown.
        * The color-coded levels (under 15% very dry, 15-25% getting dry, 25-35% healthy, over 35% very wet) are **general rules of thumb**.
          Sandy soils hold less water than clay soils, so use them as a guide, not a rule.
        """)

    with st.expander("🔬 For specialists: what's inside the satellite file"):
        tech = inspect_smap_h5()
        if tech is not None:
            st.dataframe(tech)
        else:
            st.write("File contents are not available (file missing or h5py not installed).")

# --- 12. PAGE 4: FROST & FREEZE/THAW MAP ---
elif selected == PAGES[3]:
    st.title("❄️ Frost & Freeze/Thaw Map")
    st.caption("Which days were freezing, and what the satellite sees on the ground around Weld County.")

    st.subheader("🌡️ Coldest temperature each day")
    w = get_weather()
    series_min = get_temp_series("min")
    if w is not None and series_min is not None:
        c1, c2 = st.columns(2)
        c1.metric("Freezing days", f"{w['frost_nights']}" if w["frost_nights"] is not None else "n/a")
        c2.metric("Coldest reading", f"{w['min_temp']:.1f} °C" if w["min_temp"] is not None else "n/a")
        if MPL_AVAILABLE:
            draw_calendar_heatmap(series_min)
            st.caption("Blue squares = freezing days, red = warm days. Each square shows the day of the month and the coldest temperature.")
        else:
            render_chart("frost", "line")
        if w["frost_nights"]:
            st.warning("Frost can damage young plants. Cover seedlings or wait to plant frost-sensitive crops.")
        else:
            st.success("No freezing days in this period.")
    else:
        st.warning("⚠️ The NASA weather file (with dates) was not found, so the temperature calendar can't be drawn.")

    st.divider()
    st.subheader("🗺️ Satellite freeze/thaw heatmap")
    tif_files = sorted(Path(".").glob("*.tif"))
    if not tif_files:
        st.warning("⚠️ No satellite map file (.tif) was found in the app folder.")
    elif not (RASTERIO_AVAILABLE and MPL_AVAILABLE):
        st.warning("⚠️ This map needs two libraries: pip install rasterio matplotlib")
    else:
        try:
            fig, info = build_freeze_thaw_map(tif_files[0])
            st.pyplot(fig)
            plt.close(fig)

            m1, m2, m3 = st.columns(3)
            m1.metric("Value at Weld County", f"{info['weld_value']:.0f}" if info["weld_value"] is not None else "No data")
            m2.metric("Lowest value on map", f"{info['min']:.0f}" if info["min"] is not None else "n/a")
            m3.metric("Highest value on map", f"{info['max']:.0f}" if info["max"] is not None else "n/a")
            st.caption(f"Map area shown: {info['region']}. The black star marks Weld County. Grey areas have no data.")
            st.info("These maps from NSIDC classify the ground as frozen or thawed using satellite microwave readings. "
                    "Colors show the map value; check the NSIDC product guide for the exact meaning of each value.")

            with st.expander("🔬 For specialists: file details"):
                with rasterio.open(tif_files[0]) as src:
                    st.write({
                        "File": tif_files[0].name, "Width (px)": src.width, "Height (px)": src.height,
                        "Projection": str(src.crs) if src.crs else "Lat/Lon grid", "Data type": src.dtypes[0],
                    })
        except Exception as e:
            st.error(f"The satellite map could not be drawn: {e}")

# --- 13. PAGE 5: PLANT HEALTH ---
elif selected == PAGES[4]:
    st.title("🌿 Plant Health")
    st.caption("How green and healthy your crops look from space (NASA MODIS satellite).")

    veg = get_chart_data("ndvi")["df"]
    ndvi_now = float(veg["NDVI (greenness)"].iloc[-1])
    ndvi_change = ndvi_now - float(veg["NDVI (greenness)"].iloc[0])
    evi_now = float(veg["EVI (canopy)"].iloc[-1])
    label, level, meaning = ndvi_status(ndvi_now)

    c1, c2, c3 = st.columns(3)
    c1.metric("Greenness score (NDVI)", f"{ndvi_now:.2f}", delta=f"{ndvi_change:+.2f} since early April")
    c2.metric("Canopy score (EVI)", f"{evi_now:.2f}")
    c3.metric("Plant cover", label)
    show_status(level, f"**{label}.** {meaning} Slow green-up in April is consistent with the dry conditions.")

    st.divider()
    st.subheader("📈 Greenness over April 2020")
    chart_choice = st.radio("Chart type", ["Line", "Bar", "Area"], horizontal=True, key="veg_chart_type")
    render_chart("ndvi", {"Line": "line", "Bar": "bar", "Area": "area"}[chart_choice])

    with st.expander("📘 How to read these scores"):
        st.markdown("""
        * **NDVI** is a greenness score from 0 to 1. Bare soil is around 0.1, while dense, healthy crops reach 0.6 to 0.9.
        * **EVI** is similar, but works better where plants are thick and leafy.
        * Scores that stay low or drop over time can mean plants are short of water or growing slowly.
        * The values on this page are sample April 2020 baseline numbers.
        """)

    with st.expander("🛰️ Satellite file status"):
        hdf_files = sorted(Path(".").glob("*.hdf"))
        if hdf_files:
            size_mb = hdf_files[0].stat().st_size / (1024 * 1024)
            st.success(f"MODIS satellite file found: `{hdf_files[0].name}` ({size_mb:.1f} MB)")
        else:
            st.warning("No MODIS satellite file (.hdf) was found in the app folder.")

# --- 14. PAGE 6: SAVINGS, ALERTS & SARP AI ---
elif selected == PAGES[5]:
    st.title("💰 Savings, Alerts & Sarp AI")
    st.caption("Your money-saving plan, emergency email alerts and a smart assistant, all in one place.")

    st.success("💡 **Main idea:** use about **20% less water** this week. This lowers pump and electricity costs "
               "while protecting your yield during the drought.")

    col_o1, col_o2 = st.columns(2)
    with col_o1:
        st.markdown("### 💧 Irrigation plan")
        st.write("""
        1. **Water only when it matters most:** focus on the key growth stages (deficit irrigation).
        2. **Pump at night:** run irrigation between 10 PM and 6 AM when electricity is cheaper. This can cut energy costs by about 35%.
        3. **Disturb the soil less:** less tillage keeps moisture in the ground.
        """)
    with col_o2:
        st.markdown("### 🧪 Fertilizer and inputs")
        st.write("""
        * **Use less nitrogen:** scale it back in line with the reduced water.
        * **Keep crop residue on the field:** it lowers soil temperature by 3-5 °C and slows evaporation.
        """)
    render_chart("savings", "bar")

    # --- Email alerts ---
    st.divider()
    st.subheader("📧 Email alerts")
    st.write("When severe frost or drought stress is detected, the system can email you so you don't miss it while away.")

    target_email = st.session_state.profile["email"] or "Not set yet (add it in step 1)"
    st.info(f"**Alerts will be sent to:** `{target_email}`")

    with st.expander("⚙️ Email settings and test alert"):
        sender_gmail = st.text_input("Sender Gmail", value=get_secret("GMAIL_SENDER") or "Sarpsystems.test@gmail.com")
        app_pass = st.text_input("Gmail app password", type="password", value=get_secret("GMAIL_APP_PASSWORD") or "")

        if st.button("🚀 Send a test alert now"):
            if not st.session_state.profile["email"]:
                st.warning("⚠️ Please add your Gmail address in step 1 first.")
            elif not app_pass:
                st.warning("⚠️ The Gmail app password is empty. Please check your secrets.toml file.")
            else:
                snap = get_field_snapshot()
                crop_name = st.session_state.profile["crop"]
                farmer = st.session_state.profile["first_name"] or "Farmer"
                subject = f"SARP AI ALERT: Drought and frost risk for your {crop_name}"
                body = (
                    f"Hello {farmer},\n\n"
                    f"Our latest data for Weld County shows water stress and frost risk for your {crop_name} fields.\n"
                    f"- Soil moisture: {snap['soil_pct']:.1f}%\n"
                    f"- Coldest day: {snap['min_temp']:.1f} °C\n\n"
                    f"What to do: use less water, irrigate at night (10 PM to 6 AM), and protect young plants from frost.\n\n"
                    f"Sarp AI Assistant, Sarp Holdings"
                )
                ok, msg = send_gmail_alert(st.session_state.profile["email"], sender_gmail, app_pass, subject, body)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)

    # --- Sarp AI chat ---
    st.divider()
    st.subheader("🤖 Ask Sarp AI")
    st.write("Ask anything about your fields. Sarp AI answers in plain language and can draw line, bar, area, scatter, "
             "pie and heatmap charts. Try one of these:")

    quick_cols = st.columns(len(QUICK_PROMPTS))
    for col, (label, text) in zip(quick_cols, QUICK_PROMPTS.items()):
        if col.button(label, key=f"quick_{label}"):
            st.session_state.pending_prompt = text

    for message in st.session_state.ai_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            for ch in message.get("charts", []):
                render_chart(ch["key"], ch["type"])

    typed = st.chat_input("Ask about your fields, weather, soil or savings...")
    prompt = typed or st.session_state.pop("pending_prompt", None)

    if prompt:
        st.session_state.ai_messages.append({"role": "user", "content": prompt, "charts": []})
        with st.chat_message("user"):
            st.markdown(prompt)

        profile = st.session_state.profile
        crop = profile["crop"]
        last_crop = profile["last_crop"]
        snap = get_field_snapshot()
        soil_label = soil_status(snap["soil_pct"])[0]

        extra = ""
        if snap["frost_nights"] is not None:
            extra += f"\n        - Freezing days in the weather file: {snap['frost_nights']}"
        if snap["avg_temp"] is not None:
            extra += f"\n        - Average temperature: {snap['avg_temp']:.1f} °C"
        if snap["rain_total"] is not None:
            extra += f"\n        - Total rainfall: {snap['rain_total']:.1f} mm"

        data_context = f"""
        [CURRENT FIELD AND SATELLITE DATA]
        - Crop this season: {crop}
        - Crop last season: {last_crop}
        - Location: Weld County, Colorado, USA (40.2827° N, 104.6872° W)
        - Reference period: April 2020 drought crisis
        - Surface soil moisture (NASA SMAP, top 5 cm): {snap['soil_pct']:.1f}% ({soil_label}); source: {snap['soil_note']}
        - Plant greenness (MODIS NDVI, sample baseline): 0.28 to 0.32 (low, slow early growth)
        - Coldest day: {snap['min_temp']:.1f} °C{extra}
        - Savings plan: irrigate at night (10 PM to 6 AM) to cut pump energy cost by about 35%, and use about 20% less water.
        """

        system_prompt = f"""
        You are Sarp AI, the smart farming assistant of Sarp Holdings.
        Use the field and satellite data below to answer the farmer's questions clearly and accurately:

        {data_context}

        RULES:
        1. ALWAYS answer in English, even if the user writes in another language.
        2. Use simple, friendly language a farmer understands. Avoid technical jargon, and explain any number you use.
        3. Keep answers short: 2 to 4 sentences. Use the real numbers above when asked about weather, frost, soil moisture, NDVI, irrigation timing or costs.
        4. If the question is not about farming, politely connect it back to the {crop} field in Weld County.
        5. CHARTS: if the user asks for a chart, graph, plot or visual, add up to two tags at the very END of your answer, in this format:
           [CHART: data, type]
           data must be one of: ndvi (plant greenness), weather (temperature and rainfall), frost (coldest temperature and frost nights),
           soil (soil moisture), savings (water and energy savings).
           type must be one of: line, bar, area, scatter, pie, heatmap.
           heatmap works only for weather and frost. If the user does not name a type, use line.
           Example: [CHART: soil, pie]
           Never mention these tags in your text, and do not add a tag if the user did not ask for a chart.
        """

        history = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.ai_messages
            if m["role"] in ("user", "assistant")
        ]

        with st.spinner("Sarp AI is thinking..."):
            ai_reply, error = ask_groq(system_prompt, history)

        if error:
            st.error(f"AI service error: {error}")
            ai_reply = (
                f"I couldn't reach the AI service just now, but here is your latest data: "
                f"soil moisture is {snap['soil_pct']:.1f}% and the coldest day was {snap['min_temp']:.1f} °C."
            )

        clean_reply, charts = split_reply_and_charts(ai_reply, prompt)

        st.session_state.ai_messages.append({
            "role": "assistant",
            "content": clean_reply,
            "charts": charts
        })
        with st.chat_message("assistant"):
            st.markdown(clean_reply)
            for ch in charts:
                render_chart(ch["key"], ch["type"])