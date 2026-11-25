"""Crop knowledge base and free-text crop parser (Turkish + English)."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Crop:
    id: str
    tr: str
    en: str
    family: str
    frost_c: float  # air temperature at/below which damage is likely
    heat_c: float  # daily max above which heat stress is likely
    water: str  # "low" | "medium" | "high"
    aliases: tuple[str, ...] = ()


# (id, tr, en, family, frost_c, heat_c, water, extra aliases)
_RAW: list[tuple[str, str, str, str, float, float, str, tuple[str, ...]]] = [
    ("wheat", "Buğday", "Wheat", "cereal", -10, 35, "medium", ()),
    ("barley", "Arpa", "Barley", "cereal", -10, 35, "low", ()),
    ("corn", "Mısır", "Corn", "cereal", 1, 36, "high", ("maize",)),
    ("rice", "Çeltik", "Rice", "cereal", 5, 35, "high", ("pirinç", "pirinc")),
    ("oat", "Yulaf", "Oat", "cereal", -8, 32, "medium", ("oats",)),
    ("sunflower", "Ayçiçeği", "Sunflower", "sunflower", -1, 35, "medium", ("aycicegi",)),
    ("cotton", "Pamuk", "Cotton", "mallow", 2, 38, "high", ()),
    ("tomato", "Domates", "Tomato", "nightshade", 1, 34, "high", ("tomatoes",)),
    ("pepper", "Biber", "Pepper", "nightshade", 1, 34, "medium", ("peppers", "chili", "capsicum")),
    ("eggplant", "Patlıcan", "Eggplant", "nightshade", 2, 35, "high", ("aubergine",)),
    ("potato", "Patates", "Potato", "nightshade", 0, 30, "high", ("potatoes",)),
    ("tobacco", "Tütün", "Tobacco", "nightshade", 2, 35, "medium", ()),
    ("cucumber", "Salatalık", "Cucumber", "cucurbit", 1, 34, "high", ("hiyar",)),
    ("watermelon", "Karpuz", "Watermelon", "cucurbit", 1, 38, "medium", ()),
    ("melon", "Kavun", "Melon", "cucurbit", 1, 38, "medium", ()),
    ("zucchini", "Kabak", "Zucchini", "cucurbit", 1, 34, "high", ("squash", "pumpkin", "balkabağı")),
    ("lettuce", "Marul", "Lettuce", "aster", -2, 28, "medium", ("salata",)),
    ("spinach", "Ispanak", "Spinach", "amaranth", -6, 28, "medium", ()),
    ("onion", "Soğan", "Onion", "allium", -5, 32, "medium", ("onions",)),
    ("garlic", "Sarımsak", "Garlic", "allium", -8, 32, "low", ()),
    ("carrot", "Havuç", "Carrot", "umbellifer", -3, 32, "medium", ("carrots",)),
    ("cabbage", "Lahana", "Cabbage", "brassica", -5, 30, "medium", ()),
    ("broccoli", "Brokoli", "Broccoli", "brassica", -3, 30, "medium", ()),
    ("cauliflower", "Karnabahar", "Cauliflower", "brassica", -2, 28, "medium", ()),
    ("bean", "Fasulye", "Bean", "legume", 1, 32, "medium", ("beans", "taze fasulye")),
    ("pea", "Bezelye", "Pea", "legume", -3, 28, "medium", ("peas",)),
    ("chickpea", "Nohut", "Chickpea", "legume", -8, 35, "low", ("chickpeas",)),
    ("lentil", "Mercimek", "Lentil", "legume", -8, 35, "low", ("lentils",)),
    ("alfalfa", "Yonca", "Alfalfa", "legume", -8, 35, "medium", ("lucerne",)),
    ("sugarbeet", "Şeker Pancarı", "Sugar Beet", "beet", -3, 35, "medium", ("pancar", "sugar beet")),
    ("olive", "Zeytin", "Olive", "tree-olive", -7, 40, "low", ("olives",)),
    ("grape", "Üzüm", "Grape", "vine", -1, 40, "low", ("bağ", "grapes", "vineyard", "asma")),
    ("apple", "Elma", "Apple", "rosaceae", -2, 35, "medium", ("apples",)),
    ("pear", "Armut", "Pear", "rosaceae", -2, 35, "medium", ("pears",)),
    ("cherry", "Kiraz", "Cherry", "rosaceae", -2, 35, "medium", ("cherries", "vişne", "visne")),
    ("peach", "Şeftali", "Peach", "rosaceae", -2, 36, "medium", ("peaches", "nectarine", "nektarin")),
    ("apricot", "Kayısı", "Apricot", "rosaceae", -1.5, 38, "low", ("apricots", "kayisi")),
    ("plum", "Erik", "Plum", "rosaceae", -2, 36, "medium", ("plums",)),
    ("almond", "Badem", "Almond", "rosaceae", -1.5, 38, "low", ("almonds",)),
    ("strawberry", "Çilek", "Strawberry", "rosaceae", -2, 30, "high", ("strawberries",)),
    ("hazelnut", "Fındık", "Hazelnut", "birch", -3, 35, "medium", ("hazelnuts", "findik")),
    ("walnut", "Ceviz", "Walnut", "walnut", -2, 38, "medium", ("walnuts",)),
    ("pistachio", "Antep Fıstığı", "Pistachio", "cashew", -3, 40, "low", ("fıstık", "pistachios")),
    ("fig", "İncir", "Fig", "mulberry", -4, 40, "low", ("figs",)),
    ("pomegranate", "Nar", "Pomegranate", "loosestrife", -5, 40, "low", ("pomegranates",)),
    ("orange", "Portakal", "Orange", "citrus", -2, 38, "high", ("oranges", "narenciye", "citrus")),
    ("lemon", "Limon", "Lemon", "citrus", -2, 38, "high", ("lemons",)),
    ("mandarin", "Mandalina", "Mandarin", "citrus", -2, 38, "high", ("mandarins", "tangerine")),
    ("pomelo", "Altıntopak", "Pomelo", "citrus", -2, 38, "medium",
     ("pummelo", "altintopak", "altın topak", "altin topak")),
    ("tea", "Çay", "Tea", "tea", -2, 35, "high", ()),
    ("mint", "Nane", "Mint", "mint", 0, 32, "medium", ()),
    ("basil", "Fesleğen", "Basil", "mint", 2, 32, "medium", ("feslegen",)),
    # Tropical / exotic crops
    ("dragonfruit", "Ejder Meyvesi", "Dragon Fruit", "cactus", 2, 40, "low",
     ("pitaya", "pitahaya", "ejdermeyvesi", "dragon fruit", "dragonfruit", "pitaya meyvesi")),
    ("passionfruit", "Çarkıfelek", "Passion Fruit", "passionflower", 3, 34, "medium",
     ("carkifelek", "markisa", "maracuja", "maracuya", "passiflora", "pasiflora",
      "passion fruit", "passionfruit", "passion flower")),
    ("mango", "Mango", "Mango", "sumac", 5, 40, "medium", ("mangos", "mangoes")),
    ("avocado", "Avokado", "Avocado", "laurel", 0, 36, "high", ("avocados", "avokado")),
    ("banana", "Muz", "Banana", "banana", 5, 38, "high", ("bananas", "muzlar")),
    ("guava", "Guava", "Guava", "myrtle", 2, 38, "medium", ("guavas", "guava meyvesi")),
    ("pineapple", "Ananas", "Pineapple", "bromeliad", 2, 36, "low",
     ("pineapples", "ananas meyvesi")),
]

CROPS: dict[str, Crop] = {
    r[0]: Crop(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in _RAW
}

_TR_MAP = str.maketrans("ışğüöçâîû", "isguocaiu")


def _norm(text: str) -> str:
    text = text.replace("İ", "i").replace("I", "ı").lower()
    return text.translate(_TR_MAP).strip()


# normalized alias -> crop id
_ALIASES: dict[str, str] = {}
for _c in CROPS.values():
    for _name in (_c.tr, _c.en, _c.id, *_c.aliases):
        _ALIASES[_norm(_name)] = _c.id

_SPLIT_RE = re.compile(r"[,;\n/+&|]+|\s+(?:ve|and|ile|with)\s+", re.IGNORECASE)
_NOISE_RE = re.compile(
    r"\d+(?:[.,]\d+)?|\b(?:donum|da|dekar|decare|decares|dunam|ha|hektar|hectare|acre|"
    r"adet|tane|agaci|agac|bahcesi|tarlasi|ekimi|ekili|ektim|ektik|diktim|"
    r"planted|field|orchard|trees|tree|of|the|bir)\b|[()%.:-]"
)


def _match_token(token: str) -> str | None:
    if token in _ALIASES:
        return _ALIASES[token]
    # alias contained as a whole word/prefix ("kirmizi biber", "domatesler", "bugdayi")
    best: tuple[int, str] | None = None
    for alias, cid in _ALIASES.items():
        if len(alias) < 3:
            continue
        pat = r"(?:^|\s)" + re.escape(alias)
        if re.search(pat, token) and (best is None or len(alias) > best[0]):
            best = (len(alias), cid)
    if best:
        return best[1]
    # fuzzy match for typos ("domtaes", "wheet")
    for word in token.split():
        close = difflib.get_close_matches(word, _ALIASES.keys(), n=1, cutoff=0.8)
        if close:
            return _ALIASES[close[0]]
    return None


def parse_crops(text: str | None, lang: str = "tr") -> dict[str, Any]:
    """Parse a free-text crop list into recognised crops and unrecognised leftovers."""
    recognized: list[dict[str, Any]] = []
    unknown: list[str] = []
    seen: set[str] = set()
    if not text:
        return {"crops": recognized, "unknown": unknown}

    for raw in _SPLIT_RE.split(text):
        raw = raw.strip()
        if not raw:
            continue
        token = re.sub(r"\s+", " ", _NOISE_RE.sub(" ", _norm(raw))).strip()
        if not token:
            continue
        cid = _match_token(token)
        if cid is None:
            unknown.append(raw)
        elif cid not in seen:
            seen.add(cid)
            c = CROPS[cid]
            recognized.append(
                {
                    "id": c.id,
                    "name": c.tr if lang == "tr" else c.en,
                    "family": c.family,
                    "frost_c": c.frost_c,
                    "heat_c": c.heat_c,
                    "water": c.water,
                }
            )
    return {"crops": recognized, "unknown": unknown}
