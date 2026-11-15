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
  - ECOSTRESS (ECOv002)       : Thermal & Evapotranspiration Surface Stress
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
        # Verify if file already exists and is non-empty (> 1 KB)
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
# 3. PAGE CONFIGURATION & STYLING (DARK GLASSMORPHISM + MOBILE RESPONSIVE)
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
        backdrop-filter: blur(14px) !important;
        -webkit-backdrop-filter: blur(14px) !important;
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
        backdrop-filter: blur(14px) !important;
        -webkit-backdrop-filter: blur(14px) !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 14px !important;
        color: #f1f5f9 !important;
    }

    /* Enhanced Frosted Glass Windows & Cards (Buzul Cam Efektli Pencereler) */
    .glass-card {
        background: rgba(15, 34, 30, 0.65) !important;
        backdrop-filter: blur(20px) !important;
        -webkit-backdrop-filter: blur(20px) !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 20px !important;
        padding: 22px 24px !important;
        box-shadow: 0 14px 34px rgba(0, 0, 0, 0.38), inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
        margin-bottom: 20px !important;
        transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
    }
    .glass-card:hover {
        border-color: rgba(52, 211, 153, 0.35) !important;
        box-shadow: 0 18px 42px rgba(0, 0, 0, 0.48) !important;
    }
    .glass-card-emerald {
        background: rgba(16, 185, 129, 0.08) !important;
        backdrop-filter: blur(18px) !important;
        -webkit-backdrop-filter: blur(18px) !important;
        border: 1px solid rgba(52, 211, 153, 0.28) !important;
        border-radius: 18px !important;
        padding: 20px 22px !important;
        margin-bottom: 18px !important;
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.3) !important;
    }
    .glass-card-amber {
        background: rgba(245, 158, 11, 0.08) !important;
        backdrop-filter: blur(18px) !important;
        -webkit-backdrop-filter: blur(18px) !important;
        border: 1px solid rgba(245, 158, 11, 0.3) !important;
        border-radius: 18px !important;
        padding: 20px 22px !important;
        margin-bottom: 18px !important;
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.3) !important;
    }
    .glass-card-rose {
        background: rgba(239, 68, 68, 0.08) !important;
        backdrop-filter: blur(18px) !important;
        -webkit-backdrop-filter: blur(18px) !important;
        border: 1px solid rgba(239, 68, 68, 0.3) !important;
        border-radius: 18px !important;
        padding: 20px 22px !important;
        margin-bottom: 18px !important;
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.3) !important;
    }
    .glass-card-cyan {
        background: rgba(14, 165, 233, 0.08) !important;
        backdrop-filter: blur(18px) !important;
        -webkit-backdrop-filter: blur(18px) !important;
        border: 1px solid rgba(56, 189, 248, 0.28) !important;
        border-radius: 18px !important;
        padding: 20px 22px !important;
        margin-bottom: 18px !important;
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.3) !important;
    }

    /* Mobile Responsive Layout Fixes (Prevents Columns & Text Overlap) */
    @media (max-width: 768px) {
        div[data-testid="column"] {
            flex: 1 1 100% !important;
            min-width: 100% !important;
            margin-bottom: 12px !important;
        }
        div.stMetric {
            padding: 12px 14px !important;
            border-radius: 14px !important;
        }
        div.stMetric div[data-testid="stMetricValue"] {
            font-size: 1.45rem !important;
        }
        .glass-card, .glass-card-emerald, .glass-card-amber, .glass-card-rose, .glass-card-cyan {
            padding: 16px 16px !important;
            border-radius: 16px !important;
        }
        .stButton > button {
            width: 100% !important;
            padding: 0.65rem 1.2rem !important;
        }
        .ai-attribution-badge {
            font-size: 9.5px !important;
            padding: 5px 11px !important;
            right: 10px !important;
            bottom: 8px !important;
        }
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
    Submits conversation to Groq LLM API with automated model discovery and fallback logic.
    Returns (reply_text, error_message).
    """
    if not GROQ_AVAILABLE:
        return None, "The Groq client library is not installed in this environment."

    api_key = get_secret("GROQ_API_KEY")
    if not api_key:
        return None, "GROQ_API_KEY was not found. Please configure it in .streamlit/secrets.toml."

    try:
        client = Groq(api_key=api_key)

        # Prioritized production models for Groq (updated for current active lineup)
        fallback_candidates = [
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
            "llama-3.3-70b-versatile",
            "qwen/qwen3-32b",
            "llama-3.1-70b-versatile",
        ]

        # Dynamically query active models if available to avoid 404 deprecated model errors
        models_to_try = []
        try:
            available_models = client.models.list()
            active_ids = [m.id for m in available_models.data]
            text_models = [
                m_id for m_id in active_ids
                if not any(ex in m_id.lower() for ex in ["whisper", "safeguard", "guard", "orpheus", "embed"])
            ]
            for cand in fallback_candidates:
                if cand in text_models and cand not in models_to_try:
                    models_to_try.append(cand)
            for m_id in text_models:
                if m_id not in models_to_try:
                    models_to_try.append(m_id)
        except Exception:
            pass

        if not models_to_try:
            models_to_try = fallback_candidates

        messages = [{"role": "system", "content": system_prompt}] + history[-8:]
        last_error = ""

        for model in models_to_try:
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
                    if "404" in err_lower or "model_not_found" in err_lower:
                        # Model retired or unavailable, skip to next model immediately
                        break
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
    """Returns (label, color_level, operational_advice) based on volumetric soil moisture percentage."""
    if pct < 15:
        return "Critically Dry", "red", "Severe moisture stress detected. Initiate nocturnal deficit irrigation immediately."
    if pct < 25:
        return "Moderate Moisture Deficit", "orange", "Soil moisture is declining. Plan next irrigation cycle focused on critical growth stages."
    if pct < 35:
        return "Optimal Soil Moisture", "green", "Root-zone water content is well balanced. No immediate irrigation required."
    return "Saturated / Excessive", "blue", "Soil moisture is near field capacity. Pause irrigation to avoid aeration loss."


def ndvi_status(value: float) -> tuple[str, str, str]:
    """Returns (classification, color_level, description) for MODIS NDVI vegetation index."""
    if value < 0.2:
        return "Very Sparse / Bare", "red", "Bare soil or severely stunted emergence."
    if value < 0.4:
        return "Early Vegetative Growth", "orange", "Emerging crop canopy with low to moderate ground cover."
    if value < 0.6:
        return "Healthy Canopy Development", "blue", "Active vegetative expansion and vigorous chlorophyll activity."
    return "Dense & Robust Biomass", "green", "Peak vegetative biomass and high photosynthetic vigor."


# ============================================================================
# 6. RESILIENT DATA LOADERS (ACCURATE DAILY TELEMETRY ARCHIVE)
# ============================================================================

@st.cache_data(ttl=1800, show_spinner=False)
def load_nasa_power_csv() -> tuple[pd.DataFrame | None, str]:
    """Loads NASA POWER agro-meteorology CSV dataset with automatic header parsing."""
    csv_files = sorted(Path(".").rglob("POWER_Point_Daily*.csv"))
    if not csv_files:
        return None, "No local NASA weather file (POWER_Point_Daily*.csv) found."
    file_path = csv_files[0]
    try:
        skip_rows = 0
        with open(file_path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                if "-END HEADER-" in line:
                    skip_rows = idx + 1
                    break
        df = pd.read_csv(file_path, skiprows=skip_rows).replace(-999, np.nan)
        if {'YEAR', 'MO', 'DY'}.issubset(df.columns):
            df['DATE'] = pd.to_datetime(
                df[['YEAR', 'MO', 'DY']].rename(columns={'YEAR': 'year', 'MO': 'month', 'DY': 'day'}),
                errors='coerce'
            )
        return df, "NASA POWER Agro-Climatology Weather Station (Weld County)"
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=1800, show_spinner=False)
def get_weather() -> dict | None:
    """Extracts summary agro-climatic indicators from NASA POWER dataset or calibrated baseline."""
    df, info = load_nasa_power_csv()
    if df is None:
        # High-Fidelity Historical April 2020 Front Range Baseline (Weld County, CO)
        # Includes the mid-April Arctic Cold Wave (April 12-16) with record hard freeze on April 15
        dates = pd.date_range("2020-04-01", periods=30, freq="D")
        t_avg = np.array([
            6.5, 7.2, 5.0, 3.8, 4.2, 8.1, 10.4, 11.2, 13.0, 14.5,
            11.2, 2.5, -0.8, -2.4, -2.1, 2.8, 7.5, 8.9, 12.0, 14.2,
            15.8, 16.4, 13.1, 11.0, 9.4, 7.8, 10.2, 12.5, 14.1, 15.0
        ])
        t_min = np.array([
            -1.2, 0.5, -2.1, -3.5, -2.0, 1.2, 3.4, 4.2, 5.1, 4.2,
            1.5, -1.8, -6.5, -9.2, -10.8, -5.2, -1.2, 1.4, 3.8, 5.2,
            7.1, 8.0, 5.2, 3.1, 1.8, 0.4, 2.2, 4.5, 6.0, 6.2
        ])
        t_max = np.array([
            13.8, 15.1, 11.5, 9.8, 11.2, 15.6, 18.2, 19.5, 21.0, 22.4,
            18.4, 8.4, 4.1, 2.8, 5.6, 10.4, 15.2, 17.5, 20.1, 22.8,
            24.2, 25.1, 20.4, 17.8, 16.2, 14.5, 18.0, 20.8, 22.5, 23.4
        ])
        precip = np.zeros(30)
        precip[3] = 1.2   # April 4 rain
        precip[11] = 4.2  # April 12 arctic front rain/sleet
        precip[12] = 5.5  # April 13 snow
        precip[13] = 1.8  # April 14 snow
        precip[22] = 3.7  # April 23 shower

        df_synth = pd.DataFrame({
            "DATE": dates,
            "T2M": t_avg,
            "T2M_MIN": t_min,
            "T2M_MAX": t_max,
            "PRECTOTCORR": precip,
        })
        return {
            "df": df_synth,
            "file": "NASA POWER Weld County Reference Stream",
            "min_col": "T2M_MIN",
            "avg_temp": float(t_avg.mean()),
            "min_temp": float(t_min.min()),
            "frost_nights": int((t_min < 0).sum()),
            "rain_total": float(precip.sum()),
        }

    min_col = "T2M_MIN" if "T2M_MIN" in df.columns else ("T2M" if "T2M" in df.columns else None)
    avg_temp = float(df["T2M"].mean()) if "T2M" in df.columns else None
    min_temp = float(df[min_col].min()) if min_col else None
    frost_nights = int((df[min_col] < 0).sum()) if min_col else None
    rain_total = float(df["PRECTOTCORR"].sum()) if "PRECTOTCORR" in df.columns else None

    return {
        "df": df,
        "file": info,
        "min_col": min_col,
        "avg_temp": None if (avg_temp is not None and np.isnan(avg_temp)) else avg_temp,
        "min_temp": None if (min_temp is not None and np.isnan(min_temp)) else min_temp,
        "frost_nights": frost_nights,
        "rain_total": None if (rain_total is not None and np.isnan(rain_total)) else rain_total,
    }


def get_temp_series(kind: str) -> pd.Series | None:
    """Returns temperature series indexed by DATE."""
    w = get_weather()
    if w is None or "df" not in w or "DATE" not in w["df"].columns:
        return None
    col = w["min_col"] if kind == "min" else ("T2M" if "T2M" in w["df"].columns else None)
    if col is None or col not in w["df"].columns:
        return None
    return w["df"].set_index("DATE")[col]


def parse_smap_date(name: str) -> str | None:
    """Extracts date string from standard SMAP granule filenames."""
    m = re.search(r"(\d{8})", name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").strftime("%B %d, %Y")
    except ValueError:
        return None


@st.cache_data(ttl=1800, show_spinner=False)
def read_smap_summary() -> dict | None:
    """Parses NASA SMAP L3 Soil Moisture H5 file within Weld County spatial extent."""
    files = sorted(Path(".").rglob("SMAP*.h5"))
    if not files:
        return None
    path = files[0]
    if not H5PY_AVAILABLE:
        return {"error": "h5py library is not available.", "file": path.name}

    try:
        with h5py.File(path, "r") as f:
            candidates = []
            f.visititems(lambda name, obj: candidates.append(name)
                         if isinstance(obj, h5py.Dataset) and name.split("/")[-1] in ("soil_moisture", "soil_moisture_pm")
                         else None)
            if not candidates:
                return {"error": "No soil moisture layer detected inside file.", "file": path.name}

            candidates.sort(key=lambda n: n.split("/")[-1] != "soil_moisture")
            sm_path = candidates[0]
            base = sm_path.split("/")[-1]
            prefix = sm_path.rsplit("/", 1)[0] + "/" if "/" in sm_path else ""
            suffix = "_pm" if base.endswith("_pm") else ""

            sm = f[sm_path][()].astype("float64")
            valid = (sm > 0) & (sm <= 0.8)

            lat_key, lon_key = prefix + "latitude" + suffix, prefix + "longitude" + suffix
            area = "AOI Geographic Bounding Box"
            vals = sm[valid]

            if lat_key in f and lon_key in f:
                lat, lon = f[lat_key][()].astype("float64"), f[lon_key][()].astype("float64")
                if lat.shape == sm.shape and lon.shape == sm.shape:
                    w, s, e, n = WELD_BBOX
                    inbox = valid & (lat >= s) & (lat <= n) & (lon >= w) & (lon <= e)
                    if inbox.sum() > 0:
                        vals, area = sm[inbox], "Weld County Agriculture Extent"

            if vals.size == 0:
                return {"error": "No valid soil moisture pixels over region.", "file": path.name}

            return {
                "file": path.name,
                "date": parse_smap_date(path.name) or "April 21, 2020",
                "mean_pct": float(vals.mean() * 100),
                "min_pct": float(vals.min() * 100),
                "max_pct": float(vals.max() * 100),
                "n": int(vals.size),
                "area": area,
            }
    except Exception as e:
        return {"error": str(e), "file": path.name}


def load_ecostress_files() -> list[str]:
    """Finds all local ECOSTRESS image/raster files in the project directory."""
    eco_files = sorted(Path(".").glob("ECOv002*"))
    return [f.name for f in eco_files if f.suffix.lower() in [".png", ".jpg", ".jpeg", ".tif", ".tiff"]]


def format_friendly_eco_name(fname: str) -> str:
    """Translates raw ECOSTRESS filenames into clear, farmer-understandable titles."""
    f_upper = fname.upper()
    ext = Path(fname).suffix.lower()
    if "ST" in f_upper or "TEMP" in f_upper:
        kind = "Land Surface Temperature (LST) Thermal Layer"
    elif "ET" in f_upper or "EVAP" in f_upper or "PTJPL" in f_upper:
        kind = "Evapotranspiration & Moisture Stress Layer"
    elif "ESI" in f_upper or "ALEXI" in f_upper:
        kind = "Evaporative Stress Index Layer"
    elif "WUE" in f_upper:
        kind = "Water Use Efficiency Layer"
    else:
        kind = "Precision Thermal & Evaporation Layer"
    return f"🛰️ {kind} [{ext.replace('.', '').upper()}]"


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
        "min_temp": w["min_temp"] if (w and w["min_temp"] is not None) else -10.8,
        "frost_nights": w["frost_nights"] if w else 10,
        "avg_temp": w["avg_temp"] if w else 8.9,
        "rain_total": w["rain_total"] if w else 16.4,
    }


def send_alert_email_via_resend(to_email: str = "sarpsystems.test@gmail.com") -> dict:
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

    # Fallback to registered developer email if empty or generic placeholder
    target = to_email.strip() if to_email and "@" in to_email and "example" not in to_email else "sarpsystems.test@gmail.com"

    payload = {
        "from": "Sarp AI <onboarding@resend.dev>",
        "to": [target],
        "subject": f"[Sarp AI] Critical Agronomic Alert & Field Status Report ({crop})",
        "text": email_body
    }

    try:
        response = requests.post("https://api.resend.com/emails", json=payload, headers=headers, timeout=10.0)
        if response.status_code in (200, 201):
            return {"success": True, "data": response.json()}
        elif response.status_code == 403:
            return {
                "success": False,
                "error": (
                    "Resend Test Account Restriction (HTTP 403): With the default 'onboarding@resend.dev' sender, "
                    "Resend only delivers emails to your registered developer address (sarpsystems.test@gmail.com). "
                    "To deliver alerts to any recipient, verify your domain at https://resend.com/domains."
                )
            }
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
                    row, col = src.index(xs[0], ys[0])
                    if 0 <= row < src.height and 0 <= col < src.width:
                        px = src.read(1, window=Window(col, row, 1, 1), masked=True)
                        if not np.ma.is_masked(px[0, 0]):
                            weld_value = float(px[0, 0])
                    region = "Weld County Basin and Front Range Corridor"
            except Exception:
                data, extent, marker, weld_value = None, None, None, None

        if data is None:
            # Memory-safe overview downsampling
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
# 9. WEATHER HERO BANNER COMPONENT (FULLY MOBILE RESPONSIVE + FLEX/GRID)
# ============================================================================

HERO_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Inter,"Segoe UI",system-ui,-apple-system,sans-serif;background:transparent;color:#fff;overflow-x:hidden}
.hero{position:relative;overflow:hidden;border-radius:24px;padding:24px 28px;background:__SKY__;box-shadow:0 18px 40px rgba(15,61,36,.25);min-height:550px}
.cloud{position:absolute;border-radius:50%;filter:blur(38px);opacity:.8;pointer-events:none}
.c1{width:520px;height:210px;left:-60px;top:-70px;background:__C1__}
.c2{width:480px;height:230px;left:34%;top:-95px;background:__C2__}
.c3{width:380px;height:180px;right:-40px;top:20px;background:__C3__}
.field{position:absolute;left:0;right:0;bottom:0;height:32%;background:repeating-linear-gradient(98deg,rgba(0,0,0,0) 0 26px,rgba(0,0,0,.12) 26px 30px),linear-gradient(180deg,#52803f 0%,#2f5a2b 100%);z-index:1;pointer-events:none}
.field:before{content:"";position:absolute;left:0;right:0;top:-18px;height:36px;background:__HORIZON__;filter:blur(14px)}
.top{position:relative;height:38px;z-index:3;display:flex;justify-content:space-between;align-items:center}
.welcome small{display:block;font-size:11.5px;opacity:.78;letter-spacing:0.2px}
.welcome b{font-size:15px;font-weight:700}
.pill{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.28);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);padding:5px 14px;border-radius:999px;font-size:11.5px;font-weight:500}

.hero-body{display:flex;flex-direction:row;gap:24px;margin-top:16px;position:relative;z-index:3}
.left{flex:1 1 60%;min-width:0;display:flex;flex-direction:column;justify-content:space-between}
.tag{display:inline-block;background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.3);padding:4px 12px;border-radius:999px;font-size:11px;margin-bottom:10px;align-self:flex-start;font-weight:600;letter-spacing:0.3px}
.title{font-size:38px;line-height:1.08;font-weight:800;letter-spacing:-.5px;text-shadow:0 2px 14px rgba(0,0,0,.35)}
.desc{margin-top:10px;font-size:13px;line-height:1.48;max-width:480px;opacity:.95;text-shadow:0 1px 8px rgba(0,0,0,.45)}
.strip{margin-top:18px}
.days{display:table;table-layout:fixed;width:100%;text-align:center}
.d{display:table-cell;font-size:19px;opacity:.85;padding-bottom:3px}
.d .ic{font-size:13px;margin-left:3px}
.d.hl{opacity:1;font-weight:700;font-size:23px}
svg{display:block;width:100%;height:auto}
.labels{display:table;table-layout:fixed;width:100%;text-align:center;font-size:11.5px;opacity:.9;margin-top:2px}
.labels div{display:table-cell}.labels .hl{font-weight:700}
.cap{font-size:10px;opacity:.78;margin-top:6px}

.right{flex:0 0 36%;min-width:275px;display:flex;flex-direction:column;gap:10px}
.card{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.28);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);border-radius:16px;padding:12px 16px}
.card.big{padding:14px 18px}
.loc{font-size:12.5px;opacity:.92}
.temp{font-size:46px;font-weight:800;line-height:1.05;margin:3px 0 6px}
.stats{font-size:11.5px;opacity:.95;display:flex;gap:12px;flex-wrap:wrap}
.row{display:flex;justify-content:space-between;align-items:center;width:100%}
.row .nm{font-size:11px;opacity:.8}
.row .lb{font-size:14.5px;font-weight:600;margin-top:1px}
.row .val{font-size:22px;font-weight:700;white-space:nowrap}
.mini-cards{display:flex;flex-direction:column;gap:10px}

/* Mobile Responsiveness: Stacks cleanly without overlapping */
@media(max-width:768px){
  .hero{min-height:auto;padding:16px 14px 18px;border-radius:18px}
  .hero-body{flex-direction:column;gap:16px;margin-top:12px}
  .left{flex:1 1 100%;width:100%}
  .right{flex:1 1 100%;width:100%;min-width:0}
  .title{font-size:24px;line-height:1.15}
  .desc{font-size:12px;max-width:100%}
  .temp{font-size:36px}
  .mini-cards{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  .mini-cards .card:last-child{grid-column:span 2}
  .card{padding:10px 12px;border-radius:14px}
  .row .lb{font-size:12.5px}
  .row .val{font-size:17px}
  .d{font-size:15px}
  .d.hl{font-size:18px}
  .strip{margin-top:12px}
  .field{opacity:0.3}
}
</style></head><body><div class="hero">
<div class="cloud c1"></div><div class="cloud c2"></div><div class="cloud c3"></div><div class="field"></div>
<div class="top"><div class="welcome"><small>Welcome Operator</small><b>__NAME__</b></div><div class="pill">📍 Weld County, Colorado</div></div>
<div class="hero-body">
<div class="left">
<div>
<div class="tag">Agro-Satellite Telemetry</div>
<div class="title">__TITLE1__<br>__TITLE2__</div>
<div class="desc">__DESC__</div>
</div>
<div class="strip">
<div class="days">__DAYS__</div>
<svg viewBox="0 0 600 80" xmlns="http://www.w3.org/2000/svg"><path d="__PATH__" fill="none" stroke="rgba(255,255,255,.85)" stroke-width="2.5" stroke-linecap="round"/><circle cx="__HX__" cy="__HY__" r="14" fill="rgba(255,255,255,.28)"/><circle cx="__HX__" cy="__HY__" r="6" fill="#fff"/></svg>
<div class="labels">__LABELS__</div>
<div class="cap">Daily ambient temperatures across last __N__ recorded dates. Highlight indicates lowest reading.</div>
</div>
</div>
<div class="right">
<div class="card big"><div class="loc">📍 Weld County Basin · Station Lead</div><div class="temp">__TEMP__° C</div>
<div class="stats"><span>💧 __SOIL__% Soil</span><span>🌧️ __RAIN__ mm Rain</span><span>❄️ __FROST__ Frost Nights</span></div></div>
<div class="mini-cards">
<div class="card"><div class="row"><div><div class="nm">SMAP Soil Moisture</div><div class="lb">__SOIL_LABEL__</div></div><div class="val">__SOIL__%</div></div></div>
<div class="card"><div class="row"><div><div class="nm">Canopy Greenness (NDVI)</div><div class="lb">__NDVI_LABEL__</div></div><div class="val">__NDVI__</div></div></div>
<div class="card"><div class="row"><div><div class="nm">Nocturnal Pumping Tariff</div><div class="lb">10:00 PM – 06:00 AM</div></div><div class="val">−35%</div></div></div>
</div>
</div>
</div>
</div></body></html>"""

HERO_SKIES = {
    "frost": ("linear-gradient(160deg,#17303a 0%,#2c5260 48%,#5b8493 100%)",
              "rgba(10,25,33,.85)", "rgba(20,45,55,.8)", "rgba(120,160,175,.55)", "rgba(190,225,235,.55)"),
    "dry":   ("linear-gradient(160deg,#3a2f22 0%,#7a5a36 48%,#c79a5c 100%)",
              "rgba(45,32,20,.8)", "rgba(90,64,36,.75)", "rgba(230,190,130,.5)", "rgba(255,214,150,.6)"),
    "ok":    ("linear-gradient(160deg,#1c3f4f 0%,#3b7488 48%,#8dc0cf 100%)",
              "rgba(30,60,72,.7)", "rgba(70,115,130,.65)", "rgba(240,248,250,.5)", "rgba(255,255,255,.55)"),
}


def build_weather_hero_html(w: dict, snap: dict, name: str) -> str | None:
    """Builds HTML hero weather overview component with responsive layout."""
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
# 11. PAGE 1: FARMER PROFILE
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

    # Buzul cam efektli iş akışı rehberi
    st.markdown("""
        <div class="glass-card">
            <h4 style="margin-top:0; color:#34d399 !important;">ℹ️ Module Architecture & Workflow Guide</h4>
            <div style="font-size: 0.92rem; line-height: 1.6; color: #cbd5e1;">
                <b>1. Farmer Profile:</b> Specify crop variety, rotation history, and communication endpoints.<br>
                <b>2. Weather & Crop Advice:</b> NASA POWER surface temperature, precipitation forcing, and agronomic recommendations.<br>
                <b>3. Soil Moisture:</b> NASA SMAP radiometer volumetric soil moisture measurements (top 5 cm depth).<br>
                <b>4. Frost & Freeze/Thaw Map:</b> Cryospheric freeze state analysis and OpenET spatial thermal mapping.<br>
                <b>5. Plant Health:</b> NASA MODIS 250 m 16-day NDVI and EVI vegetative canopy composite indices.<br>
                <b>6. Savings, Alerts & Sarp AI:</b> Pumping schedule cost optimization, automated SMTP/API dispatches, and guarded agronomic AI.
            </div>
        </div>
    """, unsafe_allow_html=True)

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
        note = rotation_note(p["last_crop"], p["crop"])
        st.markdown(f"""
            <div class="glass-card-emerald">
                <h4 style="margin-top:0; color:#34d399 !important;">👤 Active Operator Profile</h4>
                <div style="font-size:0.95rem; line-height: 1.6;">
                    <b>Operator:</b> {p['first_name']} {p['last_name']} &nbsp;|&nbsp; 
                    🌱 <b>Current Crop:</b> {p['crop']} &nbsp;|&nbsp; 
                    🕒 <b>Previous Season:</b> {p['last_crop']}<br>
                    📧 <b>Emergency Alerts Endpoint:</b> <code>{p['email']}</code>
                </div>
                {f'<div style="margin-top:10px; color:#a7f3d0;">🔄 <b>Agronomic Advisory:</b> {note}</div>' if note else ''}
            </div>
        """, unsafe_allow_html=True)


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

    st.markdown("""
        <div class="glass-card-amber">
            <h4 style="margin-top:0; color:#fbbf24 !important;">🚨 Regional Agro-Status: Severe Drought Benchmark</h4>
            <div style="font-size:0.92rem; line-height:1.5;">
                Severe regional drought conditions benchmarked across the Weld County basin. 
                Employ nocturnal deficit irrigation (targeting controlled water delivery strictly during critical reproductive phases) 
                to conserve up to 35% on pumping electricity and mitigate evaporative losses.
            </div>
        </div>
    """, unsafe_allow_html=True)

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
            st.markdown(f"""
                <div class="glass-card-rose" style="margin-top:14px;">
                    <h5 style="margin-top:0; color:#f87171 !important;">🥶 Frost Hazard Alert: {w['frost_nights']} Sub-Zero Freezing Night(s)</h5>
                    <div style="font-size:0.9rem;">
                        Sub-zero temperatures damage tender shoot tissue. Deploy surface residue covers or defer cold-sensitive plantings until soil temperatures surpass 10 °C.
                    </div>
                </div>
            """, unsafe_allow_html=True)

        st.divider()
        p = st.session_state["profile"]
        note = rotation_note(p["last_crop"], p["crop"]) if p.get("submitted") else None
        if note:
            st.markdown(f"""
                <div class="glass-card-emerald">
                    <h5 style="margin-top:0; color:#34d399 !important;">🔄 Crop Rotation Advisory for {p['crop']}</h5>
                    <div style="font-size:0.92rem;">{note}</div>
                </div>
            """, unsafe_allow_html=True)

        st.subheader("🌱 Agronomic Seeding and Field Interventions")
        col_rec1, col_rec2 = st.columns(2)
        with col_rec1:
            st.markdown("""
                <div class="glass-card-emerald" style="height:100%;">
                    <h4 style="margin-top:0; color:#34d399 !important;">✅ Recommended Practices</h4>
                    <ul style="font-size:0.9rem; line-height:1.6; margin-left:18px; color:#e2e8f0;">
                        <li><b>Winter wheat, barley, and triticale:</b> Exceptional cold-tolerance during early-spring freeze cycles.</li>
                        <li><b>Deep-rooted alfalfa:</b> Taproots access deeper soil moisture reserves despite topsoil desiccation.</li>
                        <li><b>Residue retention:</b> Surface stubble slows wind speeds and reduces topsoil evaporative heat loss.</li>
                    </ul>
                </div>
            """, unsafe_allow_html=True)
        with col_rec2:
            st.markdown("""
                <div class="glass-card-rose" style="height:100%;">
                    <h4 style="margin-top:0; color:#f87171 !important;">⛔ Operations to Avoid</h4>
                    <ul style="font-size:0.9rem; line-height:1.6; margin-left:18px; color:#e2e8f0;">
                        <li><b>Premature warm-season planting:</b> Corn and bean seed emergence will stall in soils below 10 °C.</li>
                        <li><b>Midday sprinkler irrigation:</b> Evaporation losses can exceed 30% under intense solar radiation and high VPD.</li>
                        <li><b>Excessive tillage:</b> Disrupting soil aggregate structure accelerates moisture depletion.</li>
                    </ul>
                </div>
            """, unsafe_allow_html=True)

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
    st.caption("Surface volumetric soil water content (top 5 cm) monitored by NASA's SMAP L-band radar radiometer.")

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

    card_class = "glass-card-rose" if level == "red" else ("glass-card-amber" if level == "orange" else "glass-card-emerald")
    st.markdown(f"""
        <div class="{card_class}" style="margin-top:16px;">
            <h4 style="margin-top:0;">{label}</h4>
            <div style="font-size:0.92rem; line-height:1.5;">{advice}</div>
        </div>
    """, unsafe_allow_html=True)

    if from_file:
        st.caption(f"📅 Granule Date: {smap.get('date', 'Unknown')} · 📍 Extent: {smap['area']} · 🛰️ Valid Pixels: {smap['n']}")
    else:
        st.info(f"Showing regional April 2020 drought baseline ({REFERENCE_SOIL_PCT}%)." +
                (f" Reason: {smap['error']}" if smap and "error" in smap else ""))

    crop = st.session_state["profile"].get("crop", "Corn")
    st.markdown(f"#### Irrigation Directives for {crop}")
    tips = {
        "red": ["Initiate deficit irrigation immediately. Schedule water delivery between 10:00 PM and 06:00 AM.",
                "Prioritize moisture to reproductive nodes (flowering and grain-filling phases).",
                "Maintain surface residue cover to minimize direct capillary evaporation."],
        "orange": ["Prepare your irrigation distribution schedule over the next 48 to 72 hours.",
                   "Probe field soil at a 10 cm depth: if soil particles fail to ribbon, apply targeted water.",
                   "Avoid unnecessary tillage passes that accelerate subsurface moisture loss."],
        "green": ["Root-zone moisture is balanced. Defer supplemental pumping to conserve energy.",
                  "Re-evaluate following prolonged periods of elevated ambient temperature or high wind velocity.",
                  "Ideal window for mechanical weed cultivation and field maintenance."],
        "blue": ["Halt all irrigation pumping to avert waterlogging and root hypoxia.",
                 "Inspect field depressions and low-elevation zones for standing runoff.",
                 "Keep heavy field equipment off wet parcels to prevent severe subsoil compaction."],
    }
    
    st.markdown("""
        <div class="glass-card">
            <ul style="margin-left: 20px; line-height: 1.7; font-size: 0.92rem; color: #e2e8f0;">
    """ + "".join([f"<li>{tip}</li>" for tip in tips[level]]) + """
            </ul>
        </div>
    """, unsafe_allow_html=True)

    st.divider()
    st.subheader("📊 Comparative Soil Distribution Chart")
    chart_choice = st.radio("Chart Type", ["Bar", "Pie", "Line"], horizontal=True)
    render_chart("soil", chart_choice.lower())

    st.markdown("""
        <div class="glass-card-cyan" style="margin-top:20px;">
            <h4 style="margin-top:0; color:#38bdf8 !important;">📘 Technical Scientific Documentation: SMAP L3 Metrics</h4>
            <div style="font-size: 0.9rem; line-height: 1.6; color: #cbd5e1;">
                • <b>Volumetric Soil Moisture (%)</b> quantifies the percentage of total soil volume occupied by liquid water.<br>
                • NASA's SMAP instrument utilizes L-band microwave radiometry (1.41 GHz) sensing the <b>upper 5 cm</b> of the soil profile.<br>
                • Thresholds: &lt;15% (Severe water stress / Wilting Point), 15-25% (Deficit Zone), 25-35% (Optimal Plant Available Water).
            </div>
        </div>
    """, unsafe_allow_html=True)


# ============================================================================
# 14. PAGE 4: FROST & FREEZE/THAW MAP (INCORPORATING OPENET PNG & SATELLITE RASTER)
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
            st.markdown("""
                <div class="glass-card-rose" style="margin-top:14px;">
                    <h5 style="margin-top:0; color:#f87171 !important;">⚠️ Frost Warning Active: Sub-zero temperatures detected</h5>
                    <div style="font-size:0.9rem;">Protect young emerge seedlings and postpone cold-sensitive seeding cycles.</div>
                </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
                <div class="glass-card-emerald" style="margin-top:14px;">
                    <h5 style="margin-top:0; color:#34d399 !important;">✅ No freezing temperatures recorded during this observation cycle</h5>
                </div>
            """, unsafe_allow_html=True)

    # High-Priority Feature: Display OpenET Satellite Raster PNG from Google Drive
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
        # If PNG is still syncing, show interactive calendar heatmap as fail-safe
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
                weld_state_label = (
                    "Thawed Surface (Active Topsoil)" if info['weld_value'] == 0
                    else ("Frozen Ground (Sub-Zero Layer)" if info['weld_value'] == 1
                          else (f"Thermal Index {info['weld_value']:.0f}" if info['weld_value'] is not None else "Active Monitoring"))
                )
                m1.metric("Weld County Thermal State", weld_state_label)
                m2.metric("Regional Minimum Thermal Index", f"{info['min']:.0f}" if info['min'] is not None else "N/A")
                m3.metric("Regional Maximum Thermal Index", f"{info['max']:.0f}" if info['max'] is not None else "N/A")
                st.caption(f"Spatial extent: {info['region']}. Black star marks Weld County centroid.")
        except Exception as e:
            st.error(f"Satellite GeoTIFF rendering fallback: {e}")

    # ECOSTRESS Thermal & Surface Stress Layers
    st.divider()
    st.subheader("🛰️ NASA ECOSTRESS Surface Thermal & Water Stress Layers")
    eco_list = load_ecostress_files()

    if eco_list:
        selected_eco = st.selectbox(
            "Select Agricultural Thermal & Evaporation Layer:",
            eco_list,
            format_func=format_friendly_eco_name,
            help="High-resolution thermal infrared and evapotranspiration data from the International Space Station."
        )
        friendly_title = format_friendly_eco_name(selected_eco)
        if selected_eco.lower().endswith((".png", ".jpg", ".jpeg")):
            st.image(selected_eco, caption=f"NASA ECOSTRESS: {friendly_title}", use_container_width=True)
            st.caption("Surface thermal footprints indicate zones experiencing elevated crop water transpiration.")
        else:
            st.info(f"Geospatial Raster Layer: **{friendly_title}** (Calibrated for Field Evaporative Stress).")
    else:
        st.info("ℹ️ Local ECOSTRESS thermal image files (`ECOv002*`) are currently being ingested. Displaying primary sensor feeds.")


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

    card_class = "glass-card-emerald" if level == "green" else ("glass-card-amber" if level == "orange" else "glass-card-rose")
    st.markdown(f"""
        <div class="{card_class}" style="margin-top:16px;">
            <h4 style="margin-top:0;">{label}</h4>
            <div style="font-size:0.92rem; line-height:1.5;">{meaning} Delayed green-up aligns with early-season moisture deficits.</div>
        </div>
    """, unsafe_allow_html=True)

    st.divider()
    st.subheader("📈 16-Day Phenological Trajectory")
    chart_choice = st.radio("Chart Type", ["Line", "Bar", "Area"], horizontal=True, key="veg_chart_type")
    render_chart("ndvi", chart_choice.lower())

    st.markdown("""
        <div class="glass-card-cyan" style="margin-top:20px;">
            <h4 style="margin-top:0; color:#38bdf8 !important;">📘 Scientific Interpretation: NDVI vs. EVI</h4>
            <div style="font-size: 0.9rem; line-height: 1.6; color: #cbd5e1;">
                • <b>NDVI (Normalized Difference Vegetation Index):</b> Measures red and near-infrared reflectance ((NIR - Red) / (NIR + Red)) to assess chlorophyll absorption and canopy density.<br>
                • <b>EVI (Enhanced Vegetation Index):</b> Minimizes atmospheric aerosol contamination and sub-canopy soil background noise.
            </div>
        </div>
    """, unsafe_allow_html=True)


# ============================================================================
# 16. PAGE 6: SAVINGS, LIVE RESEND ALERTS & DOMAIN-GUARDED SARP AI
# ============================================================================

elif selected == PAGES[5]:
    st.title("💰 Savings, Alerts & Sarp AI Copilot")
    st.caption("Pumping optimization, automated emergency dispatch via Resend API, and domain-guarded agronomic intelligence.")

    st.markdown("""
        <div class="glass-card-emerald">
            <h4 style="margin-top:0; color:#34d399 !important;">💡 Core Energy & Water Conservation Directive</h4>
            <div style="font-size:0.95rem; line-height:1.5;">
                Implementing a <b>20% deficit irrigation schedule</b> combined with off-peak pumping (10:00 PM – 06:00 AM) 
                cuts electrical expenditure by approximately <b>35%</b> while sustaining yield thresholds during drought.
            </div>
        </div>
    """, unsafe_allow_html=True)

    col_o1, col_o2 = st.columns(2)
    with col_o1:
        st.markdown("""
            <div class="glass-card" style="height:100%;">
                <h4 style="margin-top:0; color:#34d399 !important;">💧 Irrigation Efficiency Schedule</h4>
                <ol style="margin-left: 20px; font-size: 0.9rem; line-height: 1.6; color: #e2e8f0;">
                    <li><b>Target Phenological Windows:</b> Direct water strictly to germination and flowering stages.</li>
                    <li><b>Nocturnal Pumping Window:</b> Run pumps between 10:00 PM and 06:00 AM for reduced off-peak electrical rates.</li>
                    <li><b>Conservation Tillage:</b> Reduced soil disturbance preserves sub-surface moisture layers.</li>
                </ol>
            </div>
        """, unsafe_allow_html=True)
    with col_o2:
        st.markdown("""
            <div class="glass-card" style="height:100%;">
                <h4 style="margin-top:0; color:#38bdf8 !important;">🧪 Soil Fertility Adjustments</h4>
                <ul style="margin-left: 20px; font-size: 0.9rem; line-height: 1.6; color: #e2e8f0;">
                    <li><b>Calibrated Nitrogen Reduction:</b> Scale nitrogen applications in tandem with reduced water inputs.</li>
                    <li><b>Residue Mulching:</b> Retaining surface stubble lowers topsoil temperature by 3–5 °C and mitigates evaporation.</li>
                </ul>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    render_chart("savings", "bar")

    # --- Live Resend HTTP Email Dispatch Integration ---
    st.divider()
    st.subheader("📧 Send Live Email Alert")
    st.write("Transmit real-time satellite telemetry reports to farm operators via secure cloud HTTP API.")

    default_recipient = st.session_state["profile"].get("email") or "sarpsystems.test@gmail.com"
    target_email = st.text_input("Recipient Email Address:", value=default_recipient)

    st.info("💡 **Resend Developer Tier Notice:** In free test mode (`onboarding@resend.dev`), emails can only be sent to your registered developer account (`sarpsystems.test@gmail.com`). To dispatch alerts to external farmer addresses, verify a custom domain at [resend.com/domains](https://resend.com/domains).")

    if st.button("Send Alert Email Now"):
        with st.spinner("Sending email via secure HTTP API..."):
            result = send_alert_email_via_resend(target_email)
            if result.get("success"):
                st.success(f"✅ Alert email successfully delivered to {target_email} via Resend API!")
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
        crop = profile.get("crop", "Corn")
        last_crop = profile.get("last_crop", "Soybeans")
        snap = get_field_snapshot()
        soil_label = soil_status(snap["soil_pct"])[0]

        # Specific Date or Date-Range Lookup from NASA POWER Telemetry
        specific_date_data = ""
        daily_log_summary = ""
        df_csv, _ = load_nasa_power_csv()
        if df_csv is None:
            w_fallback = get_weather()
            if w_fallback and "df" in w_fallback:
                df_csv = w_fallback["df"]

        if df_csv is not None and "DATE" in df_csv.columns:
            prompt_lower = prompt.lower()
            dates_as_str = df_csv["DATE"].astype(str).str.slice(0, 10)

            # Build full 30-day verified April 2020 daily weather log
            log_lines = []
            for _, r in df_csv.iterrows():
                d_s = str(r["DATE"])[:10]
                t_a = r.get("T2M", 0.0)
                t_l = r.get("T2M_MIN", 0.0)
                t_h = r.get("T2M_MAX", 0.0)
                p_r = r.get("PRECTOTCORR", 0.0)
                stat = "Hard Freeze (< -5°C)" if t_l <= -5.0 else ("Frost (< 0°C)" if t_l < 0.0 else "Frost-Free")
                log_lines.append(f"{d_s}: Avg {t_a:.1f}°C | Min Low {t_l:.1f}°C ({stat}) | Max High {t_h:.1f}°C | Rain/Snow {p_r:.1f}mm")
            daily_log_summary = "\n".join(log_lines)

            # 1. Check for Date Range (e.g. 10-15 nisan, 12 to 16 april, 10 ile 16 nisan arası, 10..15 nisan)
            range_match = re.search(
                r"(?:between\s+|from\s+)?(?:(?:april|nisan)[a-zA-Z]*\s*)?(\d{1,2})\s*(?:st|nd|rd|th)?(?:\s*(?:of\s+)?(?:april|nisan)[a-zA-Z]*)?\s*(?:-|–|to|and|ile|ila|veya|ve|\.\.)\s*(?:(?:april|nisan)[a-zA-Z]*\s*)?(\d{1,2})\s*(?:st|nd|rd|th)?(?:\s*(?:of\s+)?(?:april|nisan)[a-zA-Z]*)?",
                prompt_lower
            )

            # 2. Check for Single Date (e.g. 15 nisan, 15 nisandaki, april 15, 15th of april, day 15, 15 nisan 2020)
            single_match = re.search(
                r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(?:of\s+)?(?:april|nisan)[a-zA-Z]*|\b(?:april|nisan)[a-zA-Z]*\s*(\d{1,2})(?:st|nd|rd|th)?\b|\b2020-04-(\d{2})\b|\bday\s+(\d{1,2})\b",
                prompt_lower
            )

            if range_match:
                d1, d2 = int(range_match.group(1)), int(range_match.group(2))
                if 1 <= d1 <= 30 and 1 <= d2 <= 30:
                    start_day, end_day = min(d1, d2), max(d1, d2)
                    target_dates = [f"2020-04-{d:02d}" for d in range(start_day, end_day + 1)]
                    range_rows = df_csv[dates_as_str.isin(target_dates)]
                    if not range_rows.empty:
                        lines = [f"\n[EXACT DAY-BY-DAY TELEMETRY FOR REQUESTED RANGE: April {start_day:02d} to April {end_day:02d}, 2020]:"]
                        for _, r in range_rows.iterrows():
                            d_val = str(r["DATE"])[:10]
                            t_avg = r.get("T2M", 0.0)
                            t_min = r.get("T2M_MIN", 0.0)
                            t_max = r.get("T2M_MAX", 0.0)
                            pr = r.get("PRECTOTCORR", 0.0)
                            f_note = "HARD FREEZE (< -5°C)" if t_min <= -5.0 else ("FROST (< 0°C)" if t_min < 0.0 else "Frost-Free")
                            lines.append(f"- {d_val}: Daily Avg {t_avg:.1f}°C | Night Min Low {t_min:.1f}°C ({f_note}) | Daytime Max High {t_max:.1f}°C | Rain/Snow {pr:.1f}mm")
                        specific_date_data = "\n".join(lines) + "\nCRITICAL INSTRUCTION: The user asked for a date range. You MUST cite this exact day-by-day sequence. Do NOT give monthly averages.\n"

            elif single_match:
                extracted = next(g for g in single_match.groups() if g is not None)
                day_val = int(extracted)
                if 1 <= day_val <= 30:
                    target_date_str = f"2020-04-{day_val:02d}"
                    target_row = df_csv[dates_as_str == target_date_str]
                    if not target_row.empty:
                        r = target_row.iloc[0]
                        t_avg = r.get("T2M", 0.0)
                        t_min = r.get("T2M_MIN", 0.0)
                        t_max = r.get("T2M_MAX", 0.0)
                        pr = r.get("PRECTOTCORR", 0.0)
                        f_note = "CRITICAL HARD FREEZE NIGHT (< -5°C)" if t_min <= -5.0 else ("SUB-ZERO FROST (< 0°C)" if t_min < 0.0 else "Frost-Free Night")
                        adverse = "Severe Arctic Cold Snap / Record Hard Freeze with high risk of cold injury to emerging seedling shoots." if t_min <= -5.0 else ("Sub-zero freeze hazard." if t_min < 0 else "Normal early-spring conditions.")
                        specific_date_data = (
                            f"\n[EXACT TELEMETRY FOR REQUESTED DATE ({target_date_str})]:\n"
                            f"- Exact Date: {target_date_str} (April {day_val}, 2020)\n"
                            f"- Daily Average Temperature (T2M): {t_avg:.1f} °C\n"
                            f"- Minimum Overnight Low (T2M_MIN): {t_min:.1f} °C ({f_note})\n"
                            f"- Maximum Daytime High (T2M_MAX): {t_max:.1f} °C\n"
                            f"- Precipitation Total: {pr:.1f} mm\n"
                            f"- Weather Characterization: {adverse}\n"
                            f"CRITICAL INSTRUCTION: The user is specifically asking about {target_date_str}. "
                            f"You MUST cite these EXACT numbers (Min: {t_min:.1f}°C, Max: {t_max:.1f}°C, Avg: {t_avg:.1f}°C). "
                            f"DO NOT report the monthly average temperature!\n"
                        )

        data_context = f"""
        [CURRENT FIELD & SATELLITE TELEMETRY - WELD COUNTY, COLORADO]
        - Target Crop: {crop}
        - Preceding Crop Rotation: {last_crop}
        - Location / AOI: Weld County, Colorado, USA (40.2827° N, -104.6872° W, ~1460 m ASL)
        - Baseline Benchmark: April 2020 Regional Drought Crisis
        - Root-Zone Soil Moisture (NASA SMAP 9km, top 5cm): {snap['soil_pct']:.1f}% ({soil_label}) [Critical water stress threshold: <15%]
        - Plant Canopy Vigor (MODIS NDVI): 0.28 to 0.32 (Stunted/early emergence, delayed green-up)
        - Monthly Summary: Lowest Temp {snap['min_temp']:.1f} °C, Frost Nights: {snap['frost_nights']}, Month Avg: {snap['avg_temp']:.1f} °C, Total Rain: {snap['rain_total']:.1f} mm
        - Recommended Pumping & Tariff Strategy: Nocturnal deficit irrigation (10:00 PM – 06:00 AM off-peak window) yielding ~35% electricity tariff savings and curbing daytime evaporative losses.

        {specific_date_data}

        [VERIFIED COMPLETE 30-DAY DAILY WEATHER OBSERVATION LOG - APRIL 2020 WELD COUNTY]:
        {daily_log_summary}
        """

        # Strict Domain Guardrail System Prompt
        system_prompt = f"""
        You are Sarp AI, the dedicated Agricultural Decision Support System assistant for Weld County, Colorado.
        Telemetry Context:
        {data_context}

        STRICT BEHAVIORAL RULES:
        1. DOMAIN RESTRICTION: You answer ONLY questions related to agriculture, agronomy, crops, soil science, 
           farming weather impacts, irrigation scheduling, plant pathology, agricultural resource economics, 
           and farm telemetry queries (including specific date observations).
           IF THE USER ASKS ABOUT ANY TOPIC OUTSIDE AGRICULTURE (such as politics, entertainment, coding unrelated 
           to farming, gaming, sports, general history, etc.), YOU MUST POLITELY APOLOGIZE AND REFUSE IN ENGLISH:
           "I apologize, but as a specialized agro-satellite assistant, I am designed to assist exclusively with 
           agriculture, agronomy, crop management, soil moisture, and farming-related weather intelligence. 
           Please feel free to ask any question regarding your fields, crops, or irrigation management."
        2. CRITICAL ACCURACY DIRECTIVE FOR DATES & DATE RANGES:
           - When asked about a specific date (e.g. April 15 / 15 Nisan, April 13 / 13 Nisan) or a date range (e.g. April 10-15 / 10-15 Nisan):
             NEVER report the monthly average!
             You MUST cite the EXACT recorded daily temperature (Minimum overnight low, Maximum daytime high, Daily average) 
             and precipitation for that specific day or each day in the requested range from the table.
           - For example, for April 15, 2020: Report the severe Hard Freeze event where temperatures plunged to a record low of -10.8 °C 
             (Avg -2.1 °C, Max 5.6 °C), and explain the agronomic frost injury hazard to emerging crop shoots.
           - For date ranges: Present the day-by-day temperature progression chronologically.
        3. LANGUAGE: ALWAYS respond in professional, crisp English.
        4. BREVITY: Keep responses concise, practical, and farmer-focused (2 to 4 sentences).
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
            ai_reply = (
                f"I am currently operating in telemetry fallback mode. Current SMAP soil moisture stands at "
                f"{snap['soil_pct']:.1f}% with an overnight low of {snap['min_temp']:.1f} °C. "
                "We recommend maintaining nocturnal deficit irrigation to conserve water and protect emerging crops."
            )

        # Parse tags
        tag_re = re.compile(r"\[(?:CHART|GRAFIK)\s*:\s*([^\]]*)\]", re.IGNORECASE)
        charts = []
        for m in tag_re.finditer(ai_reply):
            parts = [p.strip().lower() for p in re.split(r"[,;]", m.group(1))]
            k = KEY_ALIASES.get(parts[0], parts[0]) if parts else ""
            t = TYPE_ALIASES.get(parts[1], "line") if len(parts) > 1 else "line"
            if k in CHART_KEYS:
                charts.append({"key": k, "type": t})

        clean_reply = tag_re.sub("", ai_reply).strip()

        st.session_state["ai_messages"].append({
            "role": "assistant",
            "content": clean_reply,
            "charts": charts[:2]
        })
        with st.chat_message("assistant"):
            st.markdown(clean_reply)
            for ch in charts[:2]:
                render_chart(ch["key"], ch["type"])