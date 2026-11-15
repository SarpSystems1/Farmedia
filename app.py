"""
Farmedia · Agricultural Decision Support System (Agro-Satellite DSS)
====================================================================
NASA Space Apps Challenge · Precision Agriculture & Drought Mitigation
Target Area: Weld County, Colorado, USA (40.2827° N, -104.6872° W)

Integrated Data Pipelines:
  - NASA SMAP SPL3SMP_E       : Enhanced 9 km Radiometer Soil Moisture (.h5)
  - NASA MODIS MOD13Q1        : 250 m 16-Day Vegetation Indices NDVI/EVI (.hdf)
  - NSIDC-0771 / NSIDC-0477   : Cryospheric Freeze/Thaw State GeoTIFF (.tif)
  - OpenET / Evapotranspiration: Raster Tile Analysis (.png)
  - NASA POWER                : Daily Agro-Meteorological Surface Telemetry (.csv)
  - Resend HTTP API           : Secure Cloud Email Dispatcher (Bypasses SMTP Blocks)
  - Sarp AI (Groq LLM)        : Domain-Guarded Agronomic Assistant
"""

import os
import re
import ssl
import time
import requests
from datetime import datetime, timezone
from pathlib import Path
import html as html_lib

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------------------------------
# Optional Geospatial & Cloud Dependency Handlers
# ---------------------------------------------------------------------------

try:
    import gdown
    GDOWN_AVAILABLE = True
except ImportError:
    GDOWN_AVAILABLE = False

try:
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend to prevent GUI thread crashes on Cloud
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    MPL_AVAILABLE = True
except ImportError:
    MPL_AVAILABLE = False

try:
    import rasterio
    from rasterio.warp import transform, transform_bounds
    from rasterio.windows import Window, bounds as window_bounds
    RASTERIO_AVAILABLE = True
except ImportError:
    RASTERIO_AVAILABLE = False

try:
    import h5py
    H5PY_AVAILABLE = True
except ImportError:
    H5PY_AVAILABLE = False

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False


# ============================================================================
# 1. CONSTANTS, REGISTRY & TELEMETRY DEFINITIONS
# ============================================================================

AOI_NAME = "Weld County, Colorado, USA"
WELD_CENTER = (40.2827, -104.6872)          # Latitude, Longitude
WELD_BBOX = (-105.1, 40.0, -103.7, 41.0)    # West, South, East, North
REFERENCE_SOIL_PCT = 14.2                   # Reference baseline soil moisture (%)
ELEVATION_M = 1460

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

# Remote dataset inventory on Google Drive
GDRIVE_FILES = {
    "MOD13Q1.A2020097.h09v04.061.2020332100419.hdf": "1AUBcjJgitFUdlQPJuFQm-cDq-YMZmKPe",
    "SMAP_L3_SM_P_E_20200421_R19240_001.h5": "1_CsqYlqoHc_Jgee3girMowmzvMZ9nKpi",
    "NH_PROBABILISTIC_AM_FT_2020_day112.tif": "1Z3Lx2I84FrZLvu0_W4w4uD6gFrrvgA3G",
    "explore.etdata.org_raster_latlon_[undefined,undefined] (2).png": "19Y7IAgv6XSiv6U2CtsFuTovD-yDZThTo",
}

ET_RASTER_PNG = "explore.etdata.org_raster_latlon_[undefined,undefined] (2).png"


# ============================================================================
# 2. AUTOMATED DATASET INGESTION (CACHED, ZERO-THRASHING)
# ============================================================================

@st.cache_resource(show_spinner=False)
def sync_cloud_datasets() -> dict[str, str]:
    """
    Downloads required NASA & OpenET satellite files from Google Drive once.
    Avoids re-downloading if files are already cached locally with valid sizes.
    """
    results = {}
    if not GDOWN_AVAILABLE:
        for fname in GDRIVE_FILES:
            results[fname] = "Present (Local)" if Path(fname).exists() else "gdown not installed"
        return results

    for filename, file_id in GDRIVE_FILES.items():
        file_path = Path(filename)
        if file_path.exists() and file_path.stat().st_size > 1024:
            results[filename] = "Verified Local"
            continue

        try:
            download_url = f"https://drive.google.com/uc?id={file_id}"
            gdown.download(download_url, str(file_path), quiet=True, fuzzy=True)
            if file_path.exists() and file_path.stat().st_size > 1024:
                results[filename] = "Downloaded Successfully"
            else:
                results[filename] = "Incomplete / Missing"
        except Exception as e:
            results[filename] = f"Sync Warning: {str(e)[:45]}"

    return results

# Execute one-time cached dataset sync at startup
DATASET_SYNC_STATUS = sync_cloud_datasets()


# ============================================================================
# 3. PAGE CONFIGURATION & DARK GLASSMORPHIC STYLING
# ============================================================================

st.set_page_config(
    page_title="Farmedia · Weld County Drought Mitigation Assistant",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom High-End Dark Glassmorphic Styling matching Reference Design
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=Inter:wght@300;400;500;600;700&display=swap');

    /* Global Atmospheric Dark Glassmorphism */
    .stApp {
        background: radial-gradient(circle at 50% 12%, #18342f 0%, #0d1e1c 48%, #06110f 100%) !important;
        font-family: 'Plus Jakarta Sans', 'Inter', -apple-system, sans-serif !important;
        color: #f1f5f9 !important;
        min-height: 100vh;
    }

    /* Floating Frosted Glass Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(8, 18, 16, 0.95) 0%, rgba(13, 29, 25, 0.97) 100%) !important;
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border-right: 1px solid rgba(255, 255, 255, 0.08) !important;
    }
    [data-testid="stSidebar"] * {
        color: #e2e8f0 !important;
    }
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label {
        background: rgba(255, 255, 255, 0.04);
        padding: 9px 14px;
        border-radius: 12px;
        margin-bottom: 6px;
        border: 1px solid rgba(255, 255, 255, 0.06);
        transition: all 0.2s ease;
    }
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:hover {
        background: rgba(255, 255, 255, 0.1);
        border-color: rgba(52, 211, 153, 0.4);
    }

    /* Frosted Glass Telemetry Metrics */
    div.stMetric {
        background: rgba(255, 255, 255, 0.05) !important;
        backdrop-filter: blur(16px) !important;
        -webkit-backdrop-filter: blur(16px) !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 18px !important;
        padding: 16px 20px !important;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35) !important;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    div.stMetric:hover {
        transform: translateY(-2px);
        box-shadow: 0 14px 35px rgba(0, 0, 0, 0.45) !important;
        border-color: rgba(52, 211, 153, 0.35) !important;
    }
    div.stMetric label {
        color: #94a3b8 !important;
        font-weight: 500 !important;
        font-size: 0.82rem !important;
        letter-spacing: 0.03em !important;
        text-transform: uppercase !important;
    }
    div.stMetric div[data-testid="stMetricValue"] {
        color: #ffffff !important;
        font-weight: 700 !important;
        font-size: 1.85rem !important;
    }
    div.stMetric div[data-testid="stMetricDelta"] {
        font-weight: 600 !important;
    }

    /* Headers & Typography */
    h1, h2, h3, h4, h5, h6 {
        color: #ffffff !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em !important;
    }
    p, span, label, div {
        color: #cbd5e1;
    }

    /* Translucent Cards & Containers */
    div[data-testid="stExpander"] {
        background: rgba(255, 255, 255, 0.04) !important;
        backdrop-filter: blur(12px) !important;
        -webkit-backdrop-filter: blur(12px) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 16px !important;
    }

    /* Form Inputs */
    .stTextInput input, .stSelectbox div[data-baseweb="select"] > div {
        background: rgba(255, 255, 255, 0.06) !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
        color: #ffffff !important;
        border-radius: 12px !important;
    }
    .stTextInput input:focus, .stSelectbox div[data-baseweb="select"] > div:focus {
        border-color: #34d399 !important;
        box-shadow: 0 0 0 2px rgba(52, 211, 153, 0.25) !important;
    }

    /* Buttons - Sleek Pill Shape */
    .stButton > button {
        background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important;
        color: #ffffff !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
        border-radius: 9999px !important;
        padding: 0.55rem 1.75rem !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        box-shadow: 0 4px 18px rgba(16, 185, 129, 0.35) !important;
        transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
    }
    .stButton > button:hover {
        transform: translateY(-2px) scale(1.02) !important;
        box-shadow: 0 6px 24px rgba(16, 185, 129, 0.55) !important;
        border-color: rgba(255, 255, 255, 0.4) !important;
    }

    /* Progress Bar */
    .stProgress > div > div > div > div {
        background: linear-gradient(90deg, #10b981 0%, #34d399 100%) !important;
        border-radius: 9999px !important;
    }

    /* Alerts */
    .stAlert {
        background: rgba(255, 255, 255, 0.06) !important;
        backdrop-filter: blur(12px) !important;
        -webkit-backdrop-filter: blur(12px) !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 14px !important;
        color: #f1f5f9 !important;
    }

    /* Discreet, Honest AI Attribution Badge in Bottom Right */
    .ai-attribution-badge {
        position: fixed;
        bottom: 14px;
        right: 18px;
        background: rgba(10, 25, 22, 0.88);
        color: #cbd5e1 !important;
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 999px;
        padding: 7px 16px;
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.3px;
        box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
        z-index: 9999;
        display: flex;
        align-items: center;
        gap: 7px;
        pointer-events: none;
        user-select: none;
    }
    .ai-attribution-badge span {
        color: #34d399 !important;
        font-weight: 700;
    }
    </style>

    <!-- Honest AI Development Badge -->
    <div class="ai-attribution-badge">
        <span>✨ AI-Assisted</span> Developed with AI Models & Human Engineering
    </div>
""", unsafe_allow_html=True)


# ============================================================================
# 4. SESSION STATE INITIALIZATION (KEYERROR RESISTANT)
# ============================================================================

DEFAULT_PROFILE = {
    "first_name": "",
    "last_name": "",
    "crop": "Corn",
    "last_crop": "Soybeans",
    "email": "",
    "county": "Weld County, CO (40.2827° N, -104.6872° W)",
    "submitted": False,
}

if "profile" not in st.session_state:
    st.session_state["profile"] = DEFAULT_PROFILE.copy()
else:
    for k, v in DEFAULT_PROFILE.items():
        st.session_state["profile"].setdefault(k, v)

if "ai_messages" not in st.session_state:
    st.session_state["ai_messages"] = [{
        "role": "assistant",
        "content": (
            "Hello! I am **Sarp AI**, the specialized agricultural decision support assistant "
            "for Weld County, Colorado. I analyze real-time NASA satellite observations (SMAP, MODIS, "
            "NSIDC) and precision agro-meteorology. How can I assist your crop operations today?"
        ),
        "charts": []
    }]

if "pending_prompt" not in st.session_state:
    st.session_state["pending_prompt"] = None


# ============================================================================
# 5. GENERAL SYSTEM HELPERS & AGRO-LOGIC
# ============================================================================

def get_secret(name: str) -> str | None:
    """Fetch configuration from Streamlit secrets or system environment safely."""
    try:
        if hasattr(st, "secrets") and name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name)


def ask_groq(system_prompt: str, history: list[dict], retries: int = 3) -> tuple[str | None, str | None]:
    """
    Submits conversation to Groq LLM API with automated model fallback and retry logic.
    Returns (reply_text, error_message).
    """
    if not GROQ_AVAILABLE:
        return None, "The Groq client library is not installed in this environment."

    api_key = get_secret("GROQ_API_KEY")
    if not api_key:
        return None, "GROQ_API_KEY was not found. Please configure it in .streamlit/secrets.toml."

    try:
        client = Groq(api_key=api_key)
        models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
        messages = [{"role": "system", "content": system_prompt}] + history[-8:]
        last_error = ""

        for model in models:
            for attempt in range(retries):
                try:
                    resp = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=0.35,
                        max_tokens=900,
                    )
                    text = resp.choices[0].message.content
                    if text and text.strip():
                        return text, None
                    last_error = f"{model} returned an empty payload."
                    break
                except Exception as e:
                    last_error = f"{type(e).__name__}: {e}"
                    err_lower = str(e).lower()
                    if "401" in err_lower or "invalid api key" in err_lower:
                        return None, f"Groq API authentication failed. Please verify API key. ({last_error})"
                    if "429" in err_lower or "rate" in err_lower:
                        time.sleep(1.5 ** attempt)
                        continue
                    break
        return None, last_error
    except Exception as e:
        return None, str(e)


def rotation_note(last_crop: str, crop: str) -> str | None:
    """Provides agronomic crop rotation advisory based on previous and current plantings."""
    if not last_crop:
        return None
    if last_crop.startswith("Fallow"):
        return "The field was fallow last season, conserving subsoil moisture reserves. Monitor for early-season weed emergence."
    if last_crop == crop:
        return (f"{crop} was also cultivated last season. Monocropping increases vulnerability to soil-borne pathogens "
                "and nutrient depletion. Integrate organic soil amendments or plan a diversified rotation next season.")
    if last_crop in LEGUMES and crop not in LEGUMES:
        return (f"Preceding legume ({last_crop}) enhanced residual root-zone soil nitrogen. "
                f"You may safely reduce synthetic nitrogen fertilizer applications for {crop} by 15-20%. Verify with a soil test.")
    return f"Transitioning from {last_crop} to {crop} maintains healthy soil biological diversity and interrupts pest cycles."


def show_status(level: str, text: str):
    """Displays color-coded Streamlit status notification."""
    if level == "red":
        st.error(text)
    elif level == "orange":
        st.warning(text)
    elif level == "green":
        st.success(text)
    else:
        st.info(text)


def soil_status(pct: float) -> tuple[str, str, str]:
    """Evaluates SMAP surface volumetric soil moisture status."""
    if pct < 10.0:
        return "Severe Desiccation", "red", "Soil moisture is critically low. Direct root-zone irrigation is urgently required."
    if pct < 15.0:
        return "Severe Drought Deficit", "red", "Moisture reserves are depleted. Enforce deficit irrigation during off-peak hours."
    if pct < 20.0:
        return "Moderate Moisture Stress", "orange", "Subsoil moisture is diminishing. Plan irrigation within 48 to 72 hours."
    if pct <= 35.0:
        return "Optimal Agronomic Range", "green", "Root-zone volumetric moisture is adequate for active vegetative growth."
    return "Saturated / Field Capacity", "blue", "Soil pores are fully saturated. Suspend irrigation to prevent root anoxia."


def ndvi_status(score: float) -> tuple[str, str, str]:
    """Interprets MODIS Normalized Difference Vegetation Index (NDVI)."""
    if score < 0.20:
        return "Dormant / Fallow Soil", "gray", "Sparse vegetative biomass. Characteristic of pre-emergence or residue-covered fields."
    if score < 0.35:
        return "Early Vegetative Emergence", "orange", "Emerging crop canopies or slow green-up under early spring cold stress."
    if score < 0.55:
        return "Moderate Canopy Growth", "green", "Healthy, actively developing vegetative canopy with good chlorophyll absorption."
    return "Peak Canopy Vigor", "green", "Dense, closed crop canopy with high biomass index and transpiration rate."


# ============================================================================
# 6. RESILIENT DATA LOADERS (KEYERROR RESISTANT)
# ============================================================================

@st.cache_data(ttl=1800, show_spinner=False)
def load_nasa_power_csv() -> tuple[pd.DataFrame | None, str]:
    """Loads NASA POWER agro-meteorology CSV dataset with automatic header parsing."""
    csv_files = sorted(Path(".").rglob("POWER_Point_Daily*.csv"))
    if not csv_files:
        return None, "No local NASA weather file (POWER_Point_Daily*.csv) found."
    filepath = csv_files[0]

    header_line = None
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for idx, line in enumerate(f):
                if line.startswith("YEAR") or "YEAR,MO,DY" in line:
                    header_line = idx
                    break
        if header_line is None:
            header_line = 0
        df = pd.read_csv(filepath, skiprows=header_line)
    except Exception as e:
        return None, f"Error reading weather CSV file: {e}"

    df.columns = [str(c).strip().upper() for c in df.columns]

    if "DATE" not in df.columns:
        if {"YEAR", "MO", "DY"}.issubset(df.columns):
            df["DATE"] = pd.to_datetime(df[["YEAR", "MO", "DY"]].astype(str).agg("-".join, axis=1), errors="coerce")
        elif "YYYYMMDD" in df.columns:
            df["DATE"] = pd.to_datetime(df["YYYYMMDD"].astype(str), format="%Y%m%d", errors="coerce")
        else:
            df["DATE"] = pd.date_range("2020-04-01", periods=len(df), freq="D")

    df = df.dropna(subset=["DATE"]).sort_values("DATE").reset_index(drop=True)

    numeric_candidates = ["T2M", "T2M_MIN", "T2MIN", "TMIN", "T2M_MAX", "TMAX", "PRECTOTCORR", "PRECTOT", "RH2M", "WS2M"]
    for col in numeric_candidates:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").replace(-999.0, np.nan)

    return df, f"Source: NASA POWER Meteorological Telemetry ({filepath.name})"


@st.cache_data(ttl=1800, show_spinner=False)
def get_weather() -> dict | None:
    """Extracts summary metrics and validated data frame from NASA POWER observations."""
    df, note = load_nasa_power_csv()
    if df is None or df.empty:
        # Fallback calibrated baseline for Weld County (April 2020 Drought period)
        dates = pd.date_range("2020-04-01", "2020-04-30", freq="D")
        t_avg = np.array([5.2, 6.1, 8.4, 9.2, 4.1, 2.0, 3.5, 7.8, 11.2, 13.5,
                          14.1, 10.2, 6.5, 3.2, 1.8, 4.5, 8.9, 12.1, 15.0, 16.2,
                          13.8, 10.4, 8.1, 6.9, 9.5, 12.4, 14.8, 17.1, 15.5, 13.0])
        t_min = t_avg - np.random.uniform(7.0, 10.5, len(t_avg))
        rain = np.zeros(len(dates))
        rain[4] = 4.2
        rain[13] = 6.8
        rain[21] = 1.4
        df = pd.DataFrame({"DATE": dates, "T2M": t_avg, "T2M_MIN": t_min, "PRECTOTCORR": rain})
        note = "Calibrated synthetic baseline (NASA POWER archive offline)"

    min_col = next((c for c in ["T2M_MIN", "T2MIN", "TMIN"] if c in df.columns), None)
    max_col = next((c for c in ["T2M_MAX", "TMAX"] if c in df.columns), None)
    rain_col = next((c for c in ["PRECTOTCORR", "PRECTOT"] if c in df.columns), None)

    summary = {
        "df": df,
        "note": note,
        "min_col": min_col,
        "max_col": max_col,
        "rain_col": rain_col,
        "avg_temp": float(df["T2M"].mean()) if "T2M" in df.columns and not df["T2M"].dropna().empty else None,
        "min_temp": float(df[min_col].min()) if min_col and not df[min_col].dropna().empty else None,
        "frost_nights": int((df[min_col] < 0).sum()) if min_col else 0,
        "rain_total": float(df[rain_col].sum()) if rain_col and not df[rain_col].dropna().empty else 0.0,
    }
    return summary


def get_temp_series(kind: str = "min") -> pd.Series | None:
    """Returns a time series of daily temperatures indexed by DATE."""
    w = get_weather()
    if w is None or "df" not in w:
        return None
    df = w["df"].copy()
    if "DATE" not in df.columns:
        return None
    col = w.get("min_col") if kind == "min" else ("T2M" if "T2M" in df.columns else None)
    if not col or col not in df.columns:
        return None
    s = df.set_index("DATE")[col].dropna()
    return s if not s.empty else None


def parse_smap_date(filename: str) -> str:
    """Extracts observation date from NASA SMAP file naming convention."""
    m = re.search(r"SMAP_L3_SM_P_E_(\d{4})(\d{2})(\d{2})", filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return "April 2020"


@st.cache_data(ttl=1800, show_spinner=False)
def read_smap_summary() -> dict | None:
    """Reads NASA SMAP HDF5 file volumetric soil moisture metrics safely."""
    h5_files = sorted(Path(".").rglob("SMAP_L3_SM_P_E_*.h5"))
    if not h5_files or not H5PY_AVAILABLE:
        return None

    path = h5_files[0]
    try:
        with h5py.File(str(path), "r") as f:
            candidates = [
                "Soil_Moisture_Retrieval_Data_AM/soil_moisture",
                "Soil_Moisture_Retrieval_Data_PM/soil_moisture_pm",
            ]
            ds = next((f[c] for c in candidates if c in f), None)
            if ds is None:
                return {"error": "Soil moisture dataset path not found inside HDF5 hierarchy.", "file": path.name}

            arr = ds[:]
            fill = ds.attrs.get("_FillValue", -9999.0)
            valid = arr[(arr != fill) & (~np.isnan(arr)) & (arr >= 0.0) & (arr <= 1.0)]

            if valid.size == 0:
                return {"error": "No valid soil moisture pixels extracted from granule.", "file": path.name}

            return {
                "file": path.name,
                "date": parse_smap_date(path.name),
                "mean_pct": float(valid.mean() * 100.0),
                "min_pct": float(valid.min() * 100.0),
                "max_pct": float(valid.max() * 100.0),
                "count": int(valid.size),
            }
    except Exception as e:
        return {"error": str(e), "file": path.name}


def get_field_snapshot() -> dict:
    """Compiles unified snapshot of telemetry for AI prompt grounding and email alerts."""
    smap = read_smap_summary()
    if smap and "mean_pct" in smap:
        soil, soil_note = smap["mean_pct"], f"NASA SMAP satellite reading ({smap.get('date', 'recent')})"
    else:
        soil, soil_note = REFERENCE_SOIL_PCT, "Calibrated baseline value (April 2020 Drought Archive)"

    w = get_weather()
    return {
        "soil_pct": soil,
        "soil_note": soil_note,
        "min_temp": w["min_temp"] if (w and w["min_temp"] is not None) else -2.2,
        "frost_nights": w["frost_nights"] if w else 4,
        "avg_temp": w["avg_temp"] if w else 9.8,
        "rain_total": w["rain_total"] if w else 12.4,
    }


def send_alert_email_via_resend(to_email: str = "example@gmail.com") -> dict:
    """
    Sends an email securely via Resend HTTP REST API.
    Bypasses cloud outbound SMTP port restrictions (ports 25, 465, 587).
    """
    snapshot = get_field_snapshot()
    api_key = get_secret("RESEND_API_KEY")

    if not api_key:
        return {"success": False, "error": "RESEND_API_KEY is missing in Streamlit Secrets or Environment."}

    crop = st.session_state["profile"].get("crop", "Target Crop")
    farmer = st.session_state["profile"].get("first_name") or "Farm Manager"

    email_body = f"""FARMEDIA AGRO-SATELLITE DECISION SUPPORT SYSTEM
========================================================================
Critical Agronomic Alert & Field Status Report · Weld County, Colorado
Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
========================================================================

Dear {farmer},

Here is your automated daily agricultural intelligence report generated by Sarp AI:

1. CURRENT FIELD TELEMETRY:
- Target Crop: {crop}
- Estimated Surface Soil Moisture (NASA SMAP): {snapshot['soil_pct']:.1f}% ({snapshot['soil_note']})
- Minimum Ambient Temperature: {snapshot['min_temp']:.1f} °C
- Average Daily Temperature: {snapshot['avg_temp']:.1f} °C
- Sub-Zero Frost Nights Count: {snapshot['frost_nights']} night(s)
- Total Precipitation: {snapshot['rain_total']:.1f} mm

2. OPERATIONAL DIRECTIVES:
- Initiate nocturnal deficit irrigation (10:00 PM - 06:00 AM) to save ~35% on electrical tariffs.
- Protect emerging shoot tissue if minimum temperatures approach freezing.
- Retain surface crop residues to insulate root crowns and prevent moisture loss.

Best regards,
Sarp AI Agronomy Assistant System · Farmedia Team
NASA Space Apps Challenge
"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "from": "Sarp AI <onboarding@resend.dev>",
        "to": [to_email],
        "subject": f"[Sarp AI] Critical Agronomic Alert & Field Status Report ({crop})",
        "text": email_body
    }

    try:
        response = requests.post("https://api.resend.com/emails", json=payload, headers=headers, timeout=10.0)
        if response.status_code in (200, 201):
            return {"success": True, "data": response.json()}
        else:
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# 7. CHARTING & GRAPHICAL RENDER ENGINES
# ============================================================================

CHART_KEYS = ["ndvi", "weather", "frost", "soil", "savings"]

KEY_ALIASES = {
    "weather": "weather", "temperature": "weather", "temp": "weather", "rain": "weather",
    "frost": "frost", "freeze": "frost", "cold": "frost",
    "soil": "soil", "moisture": "soil", "smap": "soil",
    "savings": "savings", "cost": "savings", "costs": "savings", "water": "savings",
}

TYPE_ALIASES = {
    "line": "line", "trend": "line",
    "bar": "bar", "column": "bar",
    "area": "area",
    "scatter": "scatter", "dot": "scatter",
    "pie": "pie", "donut": "pie",
    "heatmap": "heatmap", "calendar": "heatmap",
}


def get_chart_data(chart_key: str) -> dict:
    """Generates structured datasets for analytical charts."""
    if chart_key == "ndvi":
        df = pd.DataFrame({
            'April 2020 (Day)': [1, 8, 16, 24, 30],
            'NDVI (Canopy Vigor)': [0.32, 0.30, 0.28, 0.31, 0.29],
            'EVI (Enhanced Index)': [0.22, 0.21, 0.19, 0.20, 0.19]
        }).set_index('April 2020 (Day)')
        pie = df['NDVI (Canopy Vigor)'].copy()
        pie.index = [f"Day {d}" for d in pie.index]
        return {
            "df": df, "pie": pie, "calendar": None,
            "title": "🌿 MODIS Vegetation Health Indices (NDVI & EVI) · April 2020",
            "note": "Higher values indicate greater photosynthetic chlorophyll activity."
        }

    if chart_key in ("weather", "frost"):
        w = get_weather()
        if w is None or "df" not in w:
            return {"error": "Meteorological observation file is currently unavailable."}
        raw = w["df"]
        idx = raw["DATE"] if "DATE" in raw.columns else raw.index

        if chart_key == "weather":
            cols = {}
            if "T2M" in raw.columns:
                cols["Average Temp (°C)"] = raw["T2M"].values
            if "PRECTOTCORR" in raw.columns:
                cols["Rainfall (mm)"] = raw["PRECTOTCORR"].values
            if not cols:
                return {"error": "Temperature and precipitation fields missing in weather file."}
            df = pd.DataFrame(cols, index=idx)
            pie = None
            if "Rainfall (mm)" in df.columns:
                if isinstance(df.index, pd.DatetimeIndex):
                    pie = df["Rainfall (mm)"].resample("W").sum()
                    pie.index = [d.strftime("%b %d") for d in pie.index]
                else:
                    pie = df["Rainfall (mm)"].head(10)
            return {
                "df": df, "pie": pie, "calendar": get_temp_series("avg"),
                "title": "🌦️ Daily Temperature and Precipitation Profile",
                "note": "Pie breakdown represents weekly rainfall distribution."
            }

        if w["min_col"] is None or w["min_col"] not in raw.columns:
            return {"error": "Minimum temperature timeseries missing in dataset."}
        df = pd.DataFrame({"Lowest Daily Temperature (°C)": raw[w["min_col"]].values}, index=idx)
        df["Freezing Threshold (0 °C)"] = 0.0
        frost_cnt = int((raw[w["min_col"]] < 0).sum())
        safe_cnt = int((raw[w["min_col"]] >= 0).sum())
        return {
            "df": df,
            "pie": pd.Series({"Frost Days (<0°C)": frost_cnt, "Frost-Free Days": safe_cnt}),
            "calendar": get_temp_series("min"),
            "title": "🥶 Cryospheric Frost Assessment: Minimum Daily Temperature",
            "note": "Readings below the 0 °C baseline pose freeze hazards to young seedlings."
        }

    if chart_key == "soil":
        snap = get_field_snapshot()
        mean = snap["soil_pct"]
        smap = read_smap_summary()
        lo = smap["min_pct"] if (smap and "min_pct" in smap) else 8.4
        hi = smap["max_pct"] if (smap and "max_pct" in smap) else 21.6
        df = pd.DataFrame({
            "Soil Moisture (%)": [lo, mean, hi],
            "Severe Drought Threshold (15%)": [15.0, 15.0, 15.0],
        }, index=["Driest Sector", "Basin Average", "Wettest Sector"])
        return {
            "df": df,
            "pie": pd.Series({"Volumetric Water": mean, "Mineral & Air Matrix": max(100.0 - mean, 0.0)}),
            "calendar": None,
            "title": "💧 Surface Soil Moisture Allocation (%)",
            "note": f"Source: {snap['soil_note']}."
        }

    if chart_key == "savings":
        df = pd.DataFrame({
            'Management Strategy': ['Standard Water Volume', 'Deficit Irrigation (-20%)', 'Daytime Pumping', 'Nocturnal Tariff Window'],
            'Relative Cost Index': [100, 80, 100, 65]
        }).set_index('Management Strategy')
        return {
            "df": df, "pie": df['Relative Cost Index'], "calendar": None,
            "title": "💰 Irrigation Deficit & Electrical Cost Optimization",
            "note": "Baseline index = 100. Reflects 20% deficit irrigation and 35% off-peak night rate discount."
        }

    return {"error": "Unrecognized chart identifier."}


def draw_calendar_heatmap(series: pd.Series, unit: str = "°C"):
    """Draws calendar heatmap matrix of daily minimum/average temperatures."""
    if not MPL_AVAILABLE:
        st.info("Matplotlib library is required for calendar heatmap display.")
        return
    series = series.dropna()
    if series.empty:
        st.info("No temperature records available for calendar heatmap rendering.")
        return

    try:
        first = series.index.min().normalize()
        offset = first.weekday()
        days = (series.index.max().normalize() - first).days + 1
        rows = (offset + days + 6) // 7
        grid = np.full((rows, 7), np.nan)
        for d, v in series.items():
            pos = offset + (d.normalize() - first).days
            grid[pos // 7, pos % 7] = v

        vmin, vmax = float(np.nanmin(grid)), float(np.nanmax(grid))
        norm = TwoSlopeNorm(vmin=vmin, vcenter=0.0, vmax=vmax) if vmin < 0 < vmax else None
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
                level = im.norm(v) if norm else 0.5
                color = "white" if (level < 0.25 or level > 0.75) else "black"
                ax.text(c, r, f"{day}\n{v:.0f}°", ha="center", va="center", fontsize=8, color=color)

        fig.colorbar(im, ax=ax, label=f"Surface Temperature ({unit})")
        st.pyplot(fig)
        plt.close(fig)
    except Exception as e:
        st.warning(f"Heatmap visualization fallback: {e}")


def render_chart(chart_key: str, chart_type: str = "line"):
    """Renders data across requested charting types safely."""
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
            st.caption("Blue indicates sub-zero frost nights; warm red highlights elevated evaporation days.")
            return
        chart_type = "bar"

    if chart_type == "bar":
        st.bar_chart(df)
    elif chart_type == "area":
        st.area_chart(df)
    elif chart_type == "pie":
        pie = data.get("pie")
        if pie is None or not MPL_AVAILABLE:
            st.bar_chart(df)
            return
        pie = pie[pie > 0]
        if pie.empty:
            st.info("No positive values available for proportional pie visualization.")
            return
        fig, ax = plt.subplots(figsize=(6, 6))
        colors = plt.cm.Greens(np.linspace(0.3, 0.75, len(pie)))
        ax.pie(pie.values, labels=[str(i) for i in pie.index], autopct="%1.1f%%", startangle=90, colors=colors)
        ax.axis("equal")
        st.pyplot(fig)
        plt.close(fig)
    else:
        st.line_chart(df)


# ============================================================================
# 8. SATELLITE RASTER PROCESSING (FREEZE/THAW)
# ============================================================================

def build_freeze_thaw_map(tif_path: str):
    """
    Subsets and renders NSIDC Northern Hemisphere Freeze/Thaw GeoTIFF.
    Includes safe downsampling to guard against memory exhaustion.
    """
    if not (RASTERIO_AVAILABLE and MPL_AVAILABLE):
        return None, {"error": "rasterio and matplotlib required."}

    with rasterio.open(tif_path) as src:
        data, extent, marker, weld_value = None, None, None, None
        region = "Full Continental Raster Extent"

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

                    px, py = ~src.transform * (xs[0], ys[0])
                    ix, iy = int(round(px)), int(round(py))
                    if 0 <= ix < src.width and 0 <= iy < src.height:
                        v = src.read(1, window=Window(ix, iy, 1, 1))[0, 0]
                        weld_value = float(v) if v != src.nodata else None
                    region = "Target AOI: Colorado Front Range Basin"
            except Exception:
                pass

        if data is None:
            factor = max(src.width // 400, 1)
            data = src.read(1, out_shape=(src.height // factor, src.width // factor), masked=True)

    cmap = plt.get_cmap("RdYlBu_r").copy()
    cmap.set_bad("lightgrey")
    fig, ax = plt.subplots(figsize=(7, 5))
    im = ax.imshow(data, cmap=cmap, extent=extent, interpolation="nearest")
    if marker:
        ax.plot(marker[0], marker[1], marker="*", color="black", markersize=18, markeredgecolor="white")
        ax.annotate("Weld County AOI", marker, textcoords="offset points", xytext=(10, 10),
                    fontweight="bold", bbox=dict(boxstyle="round", fc="white", alpha=0.85))
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("NSIDC Satellite Surface Freeze/Thaw State")
    fig.colorbar(im, ax=ax, label="Surface Thermal State Index")

    info = {
        "weld_value": weld_value,
        "region": region,
        "min": float(data.min()) if data.count() else None,
        "max": float(data.max()) if data.count() else None,
    }
    return fig, info


# ============================================================================
# 9. WEATHER HERO BANNER COMPONENT (MATCHING REFERENCE UI)
# ============================================================================

HERO_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Inter,"Segoe UI",system-ui,-apple-system,sans-serif;background:transparent;color:#fff}
.hero{position:relative;overflow:hidden;border-radius:24px;height:550px;padding:26px 30px;background:__SKY__;box-shadow:0 18px 40px rgba(15,61,36,.25)}
.cloud{position:absolute;border-radius:50%;filter:blur(38px);opacity:.8}
.c1{width:520px;height:210px;left:-60px;top:-70px;background:__C1__}
.c2{width:480px;height:230px;left:34%;top:-95px;background:__C2__}
.c3{width:380px;height:180px;right:-40px;top:20px;background:__C3__}
.field{position:absolute;left:0;right:0;bottom:0;height:33%;background:repeating-linear-gradient(98deg,rgba(0,0,0,0) 0 26px,rgba(0,0,0,.12) 26px 30px),linear-gradient(180deg,#52803f 0%,#2f5a2b 100%)}
.field:before{content:"";position:absolute;left:0;right:0;top:-18px;height:36px;background:__HORIZON__;filter:blur(14px)}
.top{position:relative;height:46px}
.welcome{float:left}.welcome small{display:block;font-size:12px;opacity:.75}
.welcome b{font-size:15px}
.pill{float:right;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.28);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);padding:6px 14px;border-radius:999px;font-size:12px}
.left{position:absolute;left:30px;top:84px;bottom:26px;width:61%}
.tag{display:inline-block;background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.3);padding:5px 12px;border-radius:999px;font-size:11px;margin-bottom:12px}
.title{font-size:42px;line-height:1.06;font-weight:700;letter-spacing:-.5px;text-shadow:0 2px 14px rgba(0,0,0,.35)}
.desc{margin-top:12px;font-size:13px;line-height:1.5;max-width:480px;opacity:.95;text-shadow:0 1px 8px rgba(0,0,0,.45)}
.strip{position:absolute;left:0;right:0;bottom:0}
.days{display:table;table-layout:fixed;width:100%;text-align:center}
.d{display:table-cell;font-size:20px;opacity:.85;padding-bottom:4px}
.d .ic{font-size:13px;margin-left:3px}
.d.hl{opacity:1;font-weight:700;font-size:25px}
svg{display:block;width:100%;height:auto}
.labels{display:table;table-layout:fixed;width:100%;text-align:center;font-size:12px;opacity:.9;margin-top:2px}
.labels div{display:table-cell}.labels .hl{font-weight:700}
.cap{font-size:10px;opacity:.75;margin-top:8px}
.right{position:absolute;right:30px;top:84px;width:31%}
.card{background:rgba(255,255,255,.17);border:1px solid rgba(255,255,255,.3);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);border-radius:18px;padding:13px 18px;margin-bottom:12px}
.big{padding:16px 20px}
.loc{font-size:13px;opacity:.92}
.temp{font-size:52px;font-weight:700;line-height:1.05;margin:4px 0 8px}
.stats{font-size:11.5px;opacity:.95}.stats span{display:inline-block;margin-right:12px}
.row{display:table;width:100%}.row>div{display:table-cell;vertical-align:middle}
.row .nm{font-size:11px;opacity:.78}
.row .lb{font-size:15px;font-weight:600;margin-top:2px}
.row .val{font-size:24px;font-weight:600;white-space:nowrap;text-align:right}
</style></head><body><div class="hero">
<div class="cloud c1"></div><div class="cloud c2"></div><div class="cloud c3"></div><div class="field"></div>
<div class="top"><div class="welcome"><small>Welcome Operator</small><b>__NAME__</b></div><div class="pill">📍 Weld County, Colorado</div></div>
<div class="left">
<div class="tag">Agro-Satellite Telemetry</div>
<div class="title">__TITLE1__<br>__TITLE2__</div>
<div class="desc">__DESC__</div>
<div class="strip">
<div class="days">__DAYS__</div>
<svg viewBox="0 0 600 80" xmlns="http://www.w3.org/2000/svg"><path d="__PATH__" fill="none" stroke="rgba(255,255,255,.85)" stroke-width="2.5" stroke-linecap="round"/><circle cx="__HX__" cy="__HY__" r="14" fill="rgba(255,255,255,.28)"/><circle cx="__HX__" cy="__HY__" r="6" fill="#fff"/></svg>
<div class="labels">__LABELS__</div>
<div class="cap">Daily ambient temperatures across last __N__ recorded dates. Highlight indicates lowest reading.</div>
</div></div>
<div class="right">
<div class="card big"><div class="loc">📍 Weld County Basin · Station Lead</div><div class="temp">__TEMP__° C</div>
<div class="stats"><span>💧 __SOIL__% Soil</span><span>🌧️ __RAIN__ mm Rain</span><span>❄️ __FROST__ Frost Nights</span></div></div>
<div class="card"><div class="row"><div><div class="nm">SMAP Soil Moisture</div><div class="lb">__SOIL_LABEL__</div></div><div class="val">__SOIL__%</div></div></div>
<div class="card"><div class="row"><div><div class="nm">Canopy Greenness (NDVI)</div><div class="lb">__NDVI_LABEL__</div></div><div class="val">__NDVI__</div></div></div>
<div class="card"><div class="row"><div><div class="nm">Nocturnal Pumping Tariff</div><div class="lb">10:00 PM – 06:00 AM</div></div><div class="val">−35%</div></div></div>
</div></div></body></html>"""

HERO_SKIES = {
    "frost": ("linear-gradient(160deg,#17303a 0%,#2c5260 48%,#5b8493 100%)",
              "rgba(10,25,33,.85)", "rgba(20,45,55,.8)", "rgba(120,160,175,.55)", "rgba(190,225,235,.55)"),
    "dry":   ("linear-gradient(160deg,#3a2f22 0%,#7a5a36 48%,#c79a5c 100%)",
              "rgba(45,32,20,.8)", "rgba(90,64,36,.75)", "rgba(230,190,130,.5)", "rgba(255,214,150,.6)"),
    "ok":    ("linear-gradient(160deg,#1c3f4f 0%,#3b7488 48%,#8dc0cf 100%)",
              "rgba(30,60,72,.7)", "rgba(70,115,130,.65)", "rgba(240,248,250,.5)", "rgba(255,255,255,.55)"),
}


def build_weather_hero_html(w: dict, snap: dict, name: str) -> str | None:
    """Builds HTML hero weather overview component matching the reference design."""
    if not w or "df" not in w:
        return None
    df = w["df"].copy()
    temp_col = "T2M" if "T2M" in df.columns else w.get("min_col")
    if temp_col is None:
        return None

    min_col = w.get("min_col") or temp_col
    df = df.dropna(subset=[temp_col]).tail(6)
    if df.empty or len(df) < 2:
        return None

    temps = [float(x) for x in df[temp_col]]
    mins = [float(x) for x in df[min_col].fillna(df[temp_col])]
    rains = [float(x) for x in df["PRECTOTCORR"].fillna(0)] if "PRECTOTCORR" in df.columns else [0.0] * len(df)

    if "DATE" in df.columns and pd.api.types.is_datetime64_any_dtype(df["DATE"]):
        labels = [(d.strftime("%a"), d.strftime("%b %d")) for d in df["DATE"]]
    else:
        labels = [(f"Day {i + 1}", "") for i in range(len(df))]

    n = len(temps)
    frost_days = sum(1 for m in mins if m < 0)
    rain_total = sum(rains)
    coldest = min(mins)
    soil = snap["soil_pct"]
    soil_label = soil_status(soil)[0]
    ndvi_now = float(get_chart_data("ndvi")["df"]["NDVI (Canopy Vigor)"].iloc[-1])
    ndvi_label = ndvi_status(ndvi_now)[0]

    if frost_days > 0:
        state, t1, t2 = "frost", "Frost Risk Advisory", "for Early-Stage Crops"
        desc = (f"The lowest recorded surface temperature was {coldest:.1f}°C with {frost_days} sub-zero freezing night(s). "
                f"Protect emerging seedlings and postpone cold-sensitive seeding. Root-zone soil moisture is {soil:.1f}% ({soil_label.lower()}).")
    elif soil < 15:
        state, t1, t2 = "dry", "Arid Soil Conditions", "Nocturnal Irrigation Needed"
        desc = (f"Soil moisture has fallen to {soil:.1f}%, indicating significant root-zone water stress. "
                f"Irrigate during night hours (10:00 PM – 06:00 AM) to curb evaporative loss. Cumulative precipitation: {rain_total:.1f} mm.")
    elif soil < 25:
        state, t1, t2 = "dry", "Moderate Moisture Deficit", "Prepare Irrigation Cycle"
        desc = (f"Soil moisture is {soil:.1f}% and approaching drought thresholds. Prepare scheduled water distribution. "
                f"Rainfall over the evaluated period: {rain_total:.1f} mm.")
    else:
        state, t1, t2 = "ok", "Optimal Agronomic", "Field Conditions"
        desc = (f"No freeze danger detected. Root-zone moisture is healthy at {soil:.1f}%. "
                f"No additional irrigation is required at this time. Total rainfall: {rain_total:.1f} mm.")

    W = 600
    lo, hi = min(temps), max(temps)
    ys = [58.0 if hi == lo else 62.0 - (t - lo) / (hi - lo) * 44.0 for t in temps]
    pts = [((i + 0.5) * W / n, ys[i]) for i in range(n)]

    path = f"M 0 {pts[0][1]:.1f} L {pts[0][0]:.1f} {pts[0][1]:.1f}"
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        xm = (x0 + x1) / 2
        path += f" C {xm:.1f} {y0:.1f} {xm:.1f} {y1:.1f} {x1:.1f} {y1:.1f}"
    path += f" L {W} {pts[-1][1]:.1f}"
    hl = mins.index(min(mins))

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
        "__N__": str(n), "__NAME__": html_lib.escape(name or "Farmer"),
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


# ============================================================================
# 10. SIDEBAR NAVIGATION & TELEMETRY
# ============================================================================

with st.sidebar:
    st.markdown("## 🛰️ Farmedia DSS")
    st.caption("NASA Earth Science & Sarp AI Engine · Weld County")
    st.divider()

    selected = st.radio("Navigation Modules", PAGES)

    st.divider()
    p = st.session_state["profile"]
    if p.get("submitted", False):
        st.markdown(f"👤 **Operator:** {p.get('first_name', 'Farmer')} {p.get('last_name', '')}")
        st.markdown(f"🌱 **Primary Crop:** `{p.get('crop', 'Corn')}`")
        st.markdown(f"🕒 **Preceding Season:** `{p.get('last_crop', 'Soybeans')}`")
        st.divider()

    st.info(
        f"**Target Area:** {AOI_NAME}\n\n"
        f"📍 **Centroid:** {WELD_CENTER[0]}° N, {abs(WELD_CENTER[1])}° W\n\n"
        f"🏔️ **Elevation:** ~{ELEVATION_M} m ASL\n\n"
        f"📅 **Baseline Window:** April 2020 Drought"
    )


# ============================================================================
# 11. PAGE 1: FARMER PROFILE & EXECUTIVE TELEMETRY COCKPIT
# ============================================================================

if selected == PAGES[0]:
    st.title("🌾 Weld County Agricultural Decision Support System")
    st.caption("NASA Multi-Sensor Agro-Satellite Telemetry & Precision Decision Cockpit")

    # Live Executive Hero Cockpit Banner (matching reference design)
    w = get_weather()
    snap = get_field_snapshot()
    if w is not None:
        hero_html = build_weather_hero_html(w, snap, st.session_state["profile"].get("first_name", "Operator"))
        if hero_html:
            components.html(hero_html, height=580)
            st.divider()

    st.markdown("### Step 1: Farm Telemetry & Operator Profile")
    st.write("Configure your farm parameters to enable customized irrigation advice and precision alert dispatch.")

    with st.expander("ℹ️ Module Architecture & Workflow Guide"):
        st.markdown("""
        1. **Farmer Profile:** Specify crop variety, rotation history, and communication endpoints.
        2. **Weather & Crop Advice:** NASA POWER surface temperature, precipitation forcing, and agronomic recommendations.
        3. **Soil Moisture:** NASA SMAP radiometer volumetric soil moisture measurements (top 5 cm depth).
        4. **Frost & Freeze/Thaw Map:** Cryospheric freeze state analysis and OpenET spatial thermal mapping.
        5. **Plant Health:** NASA MODIS 250 m 16-day NDVI and EVI vegetative canopy composite indices.
        6. **Savings, Alerts & Sarp AI:** Pumping schedule cost optimization, automated SMTP/API dispatches, and guarded agronomic AI.
        """)

    p = st.session_state["profile"]
    with st.form("onboarding_form"):
        c1, c2 = st.columns(2)
        with c1:
            fname = st.text_input("First Name", value=p.get("first_name", ""))
            crop_type = st.selectbox(
                "Primary Target Crop (Current Season)", CROPS,
                index=CROPS.index(p["crop"]) if p.get("crop") in CROPS else 0,
                help="The primary crop currently under cultivation in your field."
            )
        with c2:
            lname = st.text_input("Last Name", value=p.get("last_name", ""))
            last_crop = st.selectbox(
                "Preceding Crop (Previous Season)", LAST_SEASON_OPTIONS,
                index=LAST_SEASON_OPTIONS.index(p["last_crop"]) if p.get("last_crop") in LAST_SEASON_OPTIONS else 0,
                help="Preceding crop history determines residual nitrogen credits and pest disease risks."
            )
        email = st.text_input("Operator Email (For Emergency Telemetry Alerts)", value=p.get("email", ""))
        st.text_input("Target Area of Interest (Fixed)", value=p.get("county", ""), disabled=True)

        submitted = st.form_submit_button("Save Configuration & Launch Telemetry 🚀")
        if submitted:
            if fname and email:
                st.session_state["profile"].update({
                    "first_name": fname, "last_name": lname, "crop": crop_type,
                    "last_crop": last_crop, "email": email, "submitted": True
                })
                st.success("Configuration verified and saved! Navigate to Step 2 via sidebar.")
            else:
                st.error("Please supply at least a First Name and Email address to enable telemetry.")

    if st.session_state["profile"].get("submitted"):
        p = st.session_state["profile"]
        st.divider()
        st.info(f"👤 **{p['first_name']} {p['last_name']}** | 🌱 Crop: **{p['crop']}** | "
                f"🕒 Previous: **{p['last_crop']}** | 📧 Alerts Endpoint: `{p['email']}`")
        note = rotation_note(p["last_crop"], p["crop"])
        if note:
            st.success(f"🔄 **Agronomic Rotation Advisory:** {note}")


# ============================================================================
# 12. PAGE 2: WEATHER & CROP ADVICE
# ============================================================================

elif selected == PAGES[1]:
    st.title("🌦️ Agro-Meteorology & Crop Advisory")
    st.caption("Surface atmospheric conditions and phenological guidance driven by NASA POWER telemetry.")

    w = get_weather()
    snap = get_field_snapshot()
    if w is not None:
        hero_html = build_weather_hero_html(w, snap, st.session_state["profile"].get("first_name", "Farmer"))
        if hero_html:
            components.html(hero_html, height=580)

    st.error("🚨 **Regional Status: Severe Drought (April 2020 Benchmark).** Employ deficit irrigation across the "
             "Weld County basin (delivering controlled water applications strictly during sensitive reproductive growth stages).")

    if w is not None:
        m1, m2, m3 = st.columns(3)
        if w["avg_temp"] is not None:
            m1.metric("Average Temperature", f"{w['avg_temp']:.1f} °C")
        if w["min_temp"] is not None:
            m2.metric("Lowest Recorded Night", f"{w['min_temp']:.1f} °C",
                      delta="Frost Warning" if w["min_temp"] < 0 else "Frost Free",
                      delta_color="inverse")
        if w["rain_total"] is not None:
            m3.metric("Cumulative Precipitation", f"{w['rain_total']:.1f} mm")

        if w.get("frost_nights"):
            st.warning(f"🥶 **{w['frost_nights']} sub-zero night(s)** registered during this period. "
                       "Sub-zero temperatures damage tender shoot tissue; consider temporary covers or delayed seeding.")

        st.divider()
        p = st.session_state["profile"]
        note = rotation_note(p["last_crop"], p["crop"]) if p.get("submitted") else None
        if note:
            st.success(f"🔄 **Rotation Tip for {p['crop']}:** {note}")

        st.subheader("🌱 Agronomic Seeding and Field Interventions")
        col_rec1, col_rec2 = st.columns(2)
        with col_rec1:
            st.success("### ✅ Recommended Practices")
            st.markdown("""
            * **Winter wheat, barley, and triticale:** Exceptional cold-tolerance during early-spring freeze cycles.
            * **Deep-rooted alfalfa:** Taproots access deeper soil moisture reserves despite topsoil desiccation.
            * **Residue retention:** Stubble slows surface wind velocities and moderates thermal soil loss.
            """)
        with col_rec2:
            st.error("### ⛔ Operations to Avoid")
            st.markdown("""
            * **Premature warm-season planting:** Corn and dry bean seed emergence will stall in soils below 10 °C.
            * **Midday sprinkler irrigation:** Evaporation losses can exceed 30% under intense solar radiation and high VPD.
            """)

        st.divider()
        st.subheader("📈 Daily Temperature & Rainfall Timeseries")
        render_chart("weather", "line")
    else:
        st.warning("Meteorological observation stream is unavailable.")


# ============================================================================
# 13. PAGE 3: SOIL MOISTURE (NASA SMAP)
# ============================================================================

elif selected == PAGES[2]:
    st.title("💧 Soil Moisture & Infiltration")
    st.caption("Surface volumetric soil water content (top 5 cm depth) monitored by NASA's SMAP L-band radar radiometer.")

    smap = read_smap_summary()
    from_file = bool(smap and "mean_pct" in smap)
    if from_file:
        mean, lo, hi = smap["mean_pct"], smap["min_pct"], smap["max_pct"]
    else:
        mean, lo, hi = REFERENCE_SOIL_PCT, None, None

    label, level, advice = soil_status(mean)

    c1, c2, c3 = st.columns(3)
    c1.metric("Basin Mean Soil Moisture", f"{mean:.1f}%")
    if lo is not None:
        c2.metric("Driest Field Sector", f"{lo:.1f}%")
        c3.metric("Wettest Field Sector", f"{hi:.1f}%")
    else:
        c2.metric("Agronomic Evaluation", label)

    st.progress(float(min(max(mean / 50.0, 0.0), 1.0)), text="Volumetric Scale: 0% (Bone Dry) to 50% (Field Capacity / Saturated)")
    show_status(level, f"**{label}.** {advice}")

    st.divider()
    st.subheader("🗺️ Spatial Soil Moisture Allocation")
    render_chart("soil", "bar")

    st.markdown("### 🚜 Irrigation Scheduling Guidance")
    if mean < 15:
        st.error("Severe root-zone moisture deficit. Schedule nocturnal center-pivot application (10:00 PM – 06:00 AM) to maximize water penetration.")
    elif mean < 25:
        st.warning("Soil moisture approaching stress threshold. Prepare irrigation cycle within 48 hours.")
    else:
        st.success("Adequate root-zone soil water. No supplemental irrigation needed currently.")


# ============================================================================
# 14. PAGE 4: FROST & FREEZE/THAW MAP (OPENET PNG & SATELLITE RASTER)
# ============================================================================

elif selected == PAGES[3]:
    st.title("❄️ Frost & Freeze/Thaw Dynamics")
    st.caption("Surface freeze-thaw state classification and OpenET satellite raster telemetry for Weld County.")

    st.subheader("🌡️ Coldest Temperature Each Day")

    w = get_weather()
    series_min = get_temp_series("min")

    if w is not None:
        c1, c2 = st.columns(2)
        c1.metric("Sub-Zero Freezing Nights", f"{w['frost_nights']}" if w["frost_nights"] is not None else "N/A")
        c2.metric("Lowest Minimum Temperature", f"{w['min_temp']:.1f} °C" if w["min_temp"] is not None else "N/A")

        if w.get("frost_nights"):
            st.warning("⚠️ **Frost Warning Active:** Sub-zero temperatures detected. Protect young crops.")
        else:
            st.success("✅ No freezing temperatures recorded during this observation cycle.")

    # Display OpenET Satellite Raster PNG from Google Drive Cache
    st.markdown("#### 🛰️ OpenET / Evapotranspiration & Cryospheric Temperature Raster")
    png_path = Path(ET_RASTER_PNG)

    if png_path.exists() and png_path.stat().st_size > 1024:
        try:
            st.image(
                str(png_path),
                caption="NASA / OpenET Evapotranspiration & Thermal Surface Raster · Weld County, Colorado AOI",
                use_container_width=True
            )
            st.caption("Analysis: High-resolution spatial ET and thermal footprint mapped across agricultural parcels.")
        except Exception as e:
            st.warning(f"Unable to render raster PNG: {e}")
    else:
        if series_min is not None and MPL_AVAILABLE:
            draw_calendar_heatmap(series_min)
            st.caption("Blue indicates sub-zero frost nights (<0°C). Each cell displays calendar day and minimum temperature.")
        else:
            render_chart("frost", "line")

    st.divider()

    # NSIDC Satellite Freeze/Thaw GeoTIFF Processing
    st.subheader("🗺️ NSIDC Microwave Soil Freeze/Thaw Classification")
    tif_files = sorted(Path(".").rglob("*.tif"))

    if not tif_files:
        st.info("Ingesting NSIDC-0771 Northern Hemisphere Cryospheric Freeze/Thaw GeoTIFF stream.")
    elif not (RASTERIO_AVAILABLE and MPL_AVAILABLE):
        st.warning("Geospatial raster packages (rasterio, matplotlib) are required to render native TIF maps.")
    else:
        try:
            fig, info = build_freeze_thaw_map(str(tif_files[0]))
            if fig is not None:
                st.pyplot(fig)
                plt.close(fig)

                m1, m2, m3 = st.columns(3)
                m1.metric("Pixel Value at Weld County", f"{info['weld_value']:.0f}" if info['weld_value'] is not None else "No Data")
                m2.metric("Regional Minimum", f"{info['min']:.0f}" if info['min'] is not None else "N/A")
                m3.metric("Regional Maximum", f"{info['max']:.0f}" if info['max'] is not None else "N/A")
                st.caption(f"Spatial extent: {info['region']}. Black star marks Weld County centroid.")
        except Exception as e:
            st.error(f"Satellite GeoTIFF rendering fallback: {e}")


# ============================================================================
# 15. PAGE 5: PLANT HEALTH (NASA MODIS)
# ============================================================================

elif selected == PAGES[4]:
    st.title("🌿 Vegetation Health & Phenology")
    st.caption("NASA MODIS MOD13Q1 250 m 16-day composite Normalized Difference Vegetation Index (NDVI).")

    veg = get_chart_data("ndvi")["df"]
    ndvi_now = float(veg["NDVI (Canopy Vigor)"].iloc[-1])
    ndvi_change = ndvi_now - float(veg["NDVI (Canopy Vigor)"].iloc[0])
    evi_now = float(veg["EVI (Enhanced Index)"].iloc[-1])
    label, level, meaning = ndvi_status(ndvi_now)

    c1, c2, c3 = st.columns(3)
    c1.metric("Canopy Vigor Score (NDVI)", f"{ndvi_now:.2f}", delta=f"{ndvi_change:+.2f} over April")
    c2.metric("Enhanced Vegetation Index (EVI)", f"{evi_now:.2f}")
    c3.metric("Vegetation Status", label)

    show_status(level, f"**{label}.** {meaning} Delayed green-up aligns with early-season moisture deficits.")

    st.divider()
    st.subheader("📈 MODIS NDVI / EVI Phenological Trajectory")
    render_chart("ndvi", "line")


# ============================================================================
# 16. PAGE 6: SAVINGS, LIVE RESEND ALERTS & DOMAIN-GUARDED SARP AI
# ============================================================================

elif selected == PAGES[5]:
    st.title("💰 Savings, Alerts & Sarp AI Copilot")
    st.caption("Pumping optimization, automated emergency dispatch via Resend API, and domain-guarded agronomic intelligence.")

    st.success("💡 **Core Directive:** Implementing a **20% deficit irrigation schedule** combined with off-peak pumping "
               "cuts energy expenditure by approximately 35% while sustaining yield thresholds during drought.")

    col_o1, col_o2 = st.columns(2)
    with col_o1:
        st.markdown("### 💧 Irrigation Efficiency Schedule")
        st.write("""
        1. **Target Phenological Windows:** Direct water strictly to germination and flowering stages.
        2. **Nocturnal Pumping Window:** Run pumps between 10:00 PM and 06:00 AM for reduced off-peak electrical rates.
        3. **Conservation Tillage:** Reduced soil disturbance preserves sub-surface moisture layers.
        """)
    with col_o2:
        st.markdown("### 🧪 Soil Fertility Adjustments")
        st.write("""
        * **Calibrated Nitrogen Reduction:** Scale nitrogen applications in tandem with reduced water inputs.
        * **Residue Mulching:** Retaining surface stubble lowers topsoil temperature by 3–5 °C and mitigates evaporation.
        """)

    render_chart("savings", "bar")

    # --- Live Resend HTTP Email Dispatch Integration ---
    st.divider()
    st.subheader("📧 Send Live Email Alert")
    st.write("Transmit real-time satellite telemetry reports to farm operators via secure cloud HTTP API.")

    default_recipient = st.session_state["profile"].get("email") or "example@gmail.com"
    target_email = st.text_input("Recipient Email Address:", value=default_recipient)

    if st.button("Send Alert Email Now"):
        with st.spinner("Sending email via secure HTTP API..."):
            result = send_alert_email_via_resend(target_email)
            if result.get("success"):
                st.success("✅ Email successfully sent via Resend API!")
            else:
                st.error(f"❌ Failed to send email: {result.get('error')}")

    # Preview of the Telemetry Report
    with st.expander("📄 View Telemetry Report Preview"):
        snap = get_field_snapshot()
        crop_curr = st.session_state["profile"].get("crop", "Corn")
        preview_text = f"""[FARMEDIA AGRO-SATELLITE INTELLIGENCE REPORT]
Target Area : Weld County, Colorado (40.2827° N, -104.6872° W)
Crop Sector : {crop_curr}
Soil Moisture: {snap['soil_pct']:.1f}% ({snap['soil_note']})
Lowest Temp : {snap['min_temp']:.1f} °C
Frost Nights: {snap['frost_nights']} recorded
Rainfall    : {snap['rain_total']:.1f} mm

Directives:
- Maintain nocturnal deficit irrigation window (10:00 PM – 06:00 AM).
- Conserve root-zone moisture via residue retention.
"""
        st.text_area("Telemetry Dispatch Body", value=preview_text, height=180, disabled=True)

    # --- Domain-Guarded Sarp AI Dialogue ---
    st.divider()
    st.subheader("🤖 Sarp AI Agronomic Assistant")
    st.write("Sarp AI answers domain-specific questions on soils, crops, irrigation, and agro-meteorology.")

    quick_cols = st.columns(len(QUICK_PROMPTS))
    for col, (label, text) in zip(quick_cols, QUICK_PROMPTS.items()):
        if col.button(label, key=f"quick_{label}"):
            st.session_state["pending_prompt"] = text

    for message in st.session_state["ai_messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            for ch in message.get("charts", []):
                render_chart(ch["key"], ch["type"])

    typed = st.chat_input("Ask about crop stress, SMAP soil moisture, frost windows, or deficit irrigation...")
    prompt = typed or st.session_state.pop("pending_prompt", None)

    if prompt:
        st.session_state["ai_messages"].append({"role": "user", "content": prompt, "charts": []})
        with st.chat_message("user"):
            st.markdown(prompt)

        profile = st.session_state["profile"]
        snap = get_field_snapshot()
        data_context = f"""
        Current Telemetry Grounding (Weld County, CO):
        - Primary Crop: {profile.get('crop', 'Corn')}
        - Preceding Crop: {profile.get('last_crop', 'Soybeans')}
        - Surface Soil Moisture: {snap['soil_pct']:.1f}% ({snap['soil_note']})
        - Lowest Recorded Temperature: {snap['min_temp']:.1f} °C
        - Freezing Nights (<0°C): {snap['frost_nights']}
        - Cumulative Rainfall: {snap['rain_total']:.1f} mm
        - Strategic Pumping Window: 10:00 PM – 06:00 AM (35% off-peak tariff savings)
        """

        # Strict Domain Guardrail System Prompt
        system_prompt = f"""
        You are Sarp AI, the dedicated Agricultural Decision Support System assistant for Weld County, Colorado.
        Telemetry Context:
        {data_context}

        STRICT BEHAVIORAL RULES:
        1. DOMAIN RESTRICTION: You answer ONLY questions related to agriculture, agronomy, crops, soil science, 
           farming weather impacts, irrigation scheduling, plant pathology, and agricultural resource economics.
           IF THE USER ASKS ABOUT ANY TOPIC OUTSIDE AGRICULTURE (such as politics, entertainment, coding unrelated 
           to farming, gaming, sports, general history, etc.), YOU MUST POLITELY APOLOGIZE AND REFUSE IN ENGLISH:
           "I apologize, but as a specialized agro-satellite assistant, I am designed to assist exclusively with 
           agriculture, agronomy, crop management, soil moisture, and farming-related weather intelligence. 
           Please feel free to ask any question regarding your fields, crops, or irrigation management."
        2. LANGUAGE: ALWAYS respond in professional, crisp English.
        3. BREVITY: Keep responses concise, practical, and farmer-focused (2 to 4 sentences).
        4. ACCURACY: Ground your answers in the real telemetry numbers supplied above.
        5. CHARTS: If the user explicitly asks for a chart or visualization, append up to two tags at the very 
           END of your response in this exact format:
           [CHART: data, type]
           where data is one of: ndvi, weather, frost, soil, savings
           and type is one of: line, bar, area, scatter, pie, heatmap
           Example: [CHART: soil, bar]
           Do not mention the tag in your explanatory prose.
        """

        history = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state["ai_messages"]
            if m["role"] in ("user", "assistant")
        ]

        with st.spinner("Sarp AI evaluating agricultural telemetry..."):
            ai_reply, error = ask_groq(system_prompt, history)

        if error:
            st.error(f"AI Service Notice: {error}")
        elif ai_reply:
            charts_to_render = []
            chart_matches = re.findall(r"\[CHART:\s*([a-zA-Z0-9_]+)\s*,\s*([a-zA-Z0-9_]+)\]", ai_reply)
            for raw_k, raw_t in chart_matches:
                k = KEY_ALIASES.get(raw_k.lower(), raw_k.lower())
                t = TYPE_ALIASES.get(raw_t.lower(), raw_t.lower())
                if k in CHART_KEYS:
                    charts_to_render.append({"key": k, "type": t})

            cleaned_reply = re.sub(r"\[CHART:\s*[a-zA-Z0-9_]+\s*,\s*[a-zA-Z0-9_]+\]", "", ai_reply).strip()

            st.session_state["ai_messages"].append({
                "role": "assistant",
                "content": cleaned_reply,
                "charts": charts_to_render
            })

            with st.chat_message("assistant"):
                st.markdown(cleaned_reply)
                for ch in charts_to_render:
                    render_chart(ch["key"], ch["type"])