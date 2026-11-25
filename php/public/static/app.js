/* Farmedia web UI: language gate -> profile onboarding -> weather dashboard.
 * Profile is stored in this browser's localStorage (per-viewer; no account system exists).
 */
(() => {
  "use strict";

  const STORE_KEY = "farmedia.v2";
  const S = window.FM_STRINGS;
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  // Sarp AI charts currently on the page. Each one redraws when the theme changes.
  const liveSarpCharts = new Set();

  // ---------- storage (every access guarded) ----------
  function loadStore() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; } catch { return {}; }
  }
  function saveStore(data) {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(data)); } catch { /* private mode: keep in memory */ }
  }

  const store = loadStore();
  const state = {
    lang: store.lang || null,
    profile: store.profile || null,
    coords: null,          // { latitude, longitude, display_name, precision } for the current form
    lastDash: null,        // last dashboard payload, for re-render on language switch
  };

  // ---------- i18n ----------
  function t(key, vars = {}) {
    const dict = S[state.lang] || S.en;
    let s = dict[key] ?? S.en[key] ?? key;
    for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, v);
    return s;
  }
  function applyI18n() {
    document.documentElement.lang = state.lang || "en";
    $$("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
    $$("[data-i18n-ph]").forEach((el) => (el.placeholder = t(el.dataset.i18nPh)));
    $$("[data-i18n-title]").forEach((el) => (el.title = t(el.dataset.i18nTitle)));
    $$("[data-i18n-aria]").forEach((el) => el.setAttribute("aria-label", t(el.dataset.i18nAria)));
    $("#btn-lang").textContent = state.lang === "tr" ? "EN" : "TR";
  }
  function setLang(lang) {
    state.lang = lang;
    store.lang = lang;
    saveStore(store);
    applyI18n();
  }

  // ---------- helpers ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v, d = 0) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "–" : Number(v).toFixed(d));
  const dateLocale = () => (state.lang === "tr" ? "tr-TR" : "en-GB");

  function showView(id) {
    ["view-lang", "view-auth", "view-profile", "view-dash", "view-settings"].forEach((v) => ($("#" + v).hidden = v !== id));
    placeProfileForm(id === "view-settings");
    syncSarp();
    window.scrollTo(0, 0);
  }

  // The profile form lives in #view-profile during onboarding and in Settings > Profile
  // afterwards. Moving the same node (not a copy) keeps all existing form handlers working.
  function placeProfileForm(inSettings) {
    const host = $("#profile-host");
    const submit = $("#profile-form button[type=submit]");
    if (inSettings && form.parentElement !== host) host.appendChild(form);
    if (!inSettings && form.parentElement !== $("#view-profile")) $("#view-profile").prepend(form);
    form.classList.toggle("in-settings", inSettings);
    submit.dataset.i18n = inSettings ? "common.save" : "profile.save";
    submit.textContent = t(submit.dataset.i18n);
  }

  // Bearer header for the PHP endpoints that need a signed-in user. Empty when signed out.
  const authHeaders = () => (acc.token ? { Authorization: "Bearer " + acc.token } : {});

  // Parses a JSON response. HTTP errors become Error objects with .status and .code.
  async function readBody(res) {
    let body = null;
    try { body = await res.json(); } catch { /* non-JSON, e.g. 204 No Content */ }
    if (!res.ok) {
      const msg = body?.error?.message || (Array.isArray(body?.detail) ? body.detail[0]?.msg : body?.detail) || "";
      const err = new Error(msg || `HTTP ${res.status}`);
      err.status = res.status;
      err.code = body?.error?.code;
      throw err;
    }
    return body;
  }

  async function api(path, opts = {}) {
    let res;
    try {
      res = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...opts,
      });
    } catch {
      throw new Error("network");
    }
    return readBody(res);
  }

  // ---------- 1. language gate ----------
  function showLanguage() {
    showView("view-lang");
  }
  $$("[data-pick-lang]").forEach((btn) =>
    btn.addEventListener("click", () => {
      setLang(btn.dataset.pickLang);
      route();
    })
  );

  // ---------- 2. profile ----------
  const form = $("#profile-form");
  const farmSection = $("#farm-section");
  const photoPreview = $("#photo-preview");
  const photoPlaceholder = $("#photo-placeholder");
  const photoRemove = $("#photo-remove");
  const formError = $("#form-error");
  const geoStatus = $("#geo-status");
  let photoData = null;
  const LOCATION_FIELDS = ["#f-country", "#f-state", "#f-city", "#f-district"];

  function currentRole() {
    return $("input[name=role]:checked").value;
  }
  function syncRoleSection() {
    farmSection.hidden = currentRole() !== "farm";
  }
  $$("input[name=role]").forEach((r) => r.addEventListener("change", syncRoleSection));

  function setPhoto(dataUrl) {
    photoData = dataUrl;
    if (dataUrl) {
      photoPreview.src = dataUrl;
      photoPreview.hidden = false;
      photoPlaceholder.hidden = true;
      photoRemove.hidden = false;
    } else {
      photoPreview.removeAttribute("src");
      photoPreview.hidden = true;
      photoPlaceholder.hidden = false;
      photoRemove.hidden = true;
      $("#f-photo").value = "";
    }
  }

  // Downscale the chosen image to 256px so it fits comfortably in localStorage.
  function resizeImage(file) {
    return new Promise((resolve, reject) => {
      if (!file || file.size > 5 * 1024 * 1024 || !file.type.startsWith("image/")) return reject(new Error("photo"));
      const reader = new FileReader();
      reader.onerror = () => reject(new Error("photo"));
      reader.onload = () => {
        const img = new Image();
        img.onerror = () => reject(new Error("photo"));
        img.onload = () => {
          const max = 256;
          const scale = Math.min(1, max / Math.max(img.width, img.height));
          const c = document.createElement("canvas");
          c.width = Math.round(img.width * scale);
          c.height = Math.round(img.height * scale);
          c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
          resolve(c.toDataURL("image/jpeg", 0.85));
        };
        img.src = reader.result;
      };
      reader.readAsDataURL(file);
    });
  }

  $("#f-photo").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      setPhoto(await resizeImage(file));
      formError.hidden = true;
    } catch {
      showFormError(t("err.photo"));
    }
  });
  photoRemove.addEventListener("click", () => setPhoto(null));

  function showFormError(msg) {
    formError.textContent = msg;
    formError.hidden = false;
    formError.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  // Changing any location field invalidates previously detected coordinates.
  LOCATION_FIELDS.forEach((sel) =>
    $(sel).addEventListener("input", () => {
      state.coords = null;
      geoStatus.textContent = "";
      geoStatus.className = "geo-status";
    })
  );

  $("#geo-btn").addEventListener("click", async () => {
    const country = $("#f-country").value.trim();
    const city = $("#f-city").value.trim();
    if (!country || !city) {
      geoStatus.textContent = t("err.location_first");
      geoStatus.className = "geo-status err";
      return;
    }
    const btn = $("#geo-btn");
    btn.disabled = true;
    geoStatus.textContent = t("geo.detecting");
    geoStatus.className = "geo-status";
    const qs = new URLSearchParams({
      country,
      state: $("#f-state").value.trim(),
      city,
      district: $("#f-district").value.trim(),
      lang: state.lang || "en",
    });
    try {
      const g = await api("/api/geocode.php?" + qs.toString(), { headers: authHeaders() });
      const precision = effectivePrecision(g.precision, $("#f-district").value);
      state.coords = { latitude: g.latitude, longitude: g.longitude, display_name: g.display_name, precision, country_code: g.country_code || null };
      geoStatus.textContent = t("geo.found", {
        name: esc(g.display_name.split(",").slice(0, 2).join(",")),
        lat: g.latitude.toFixed(4),
        lon: g.longitude.toFixed(4),
        precision: t("prec." + precision),
      });
      geoStatus.className = "geo-status ok";
    } catch (err) {
      state.coords = null;
      geoStatus.textContent = err.status === 404 ? t("geo.notfound") : t("geo.fail");
      geoStatus.className = "geo-status err";
    } finally {
      btn.disabled = false;
    }
  });

  // Live crop parsing: chips show what was recognised, yellow for unknown text.
  const cropFields = [
    ["#f-last-crops", "#chips-last"],
    ["#f-current-crops", "#chips-current"],
    ["#f-next-crops", "#chips-next"],
  ];
  const parseTimers = new Map();
  async function parseInto(textSel, chipsSel) {
    const text = $(textSel).value;
    const chips = $(chipsSel);
    if (!text.trim()) { chips.innerHTML = ""; return; }
    try {
      const r = await api("/api/parse-crops.php", {
        headers: { "Content-Type": "application/json", ...authHeaders() },
        method: "POST",
        body: JSON.stringify({ text, lang: state.lang || "en" }),
      });
      chips.innerHTML =
        r.crops.map((c) => `<span class="chip">${esc(c.name)}</span>`).join("") +
        r.unknown.map((u) => `<span class="chip unk" title="${esc(t("chip.unknown"))}">${esc(u)}</span>`).join("");
    } catch {
      chips.innerHTML = "";
    }
  }
  cropFields.forEach(([textSel, chipsSel]) =>
    $(textSel).addEventListener("input", () => {
      clearTimeout(parseTimers.get(textSel));
      parseTimers.set(textSel, setTimeout(() => parseInto(textSel, chipsSel), 350));
    })
  );

  // Changing any location field makes the detected coordinates stale. Saving is blocked until they are detected again,
  // so the dashboard can never centre on a place the user no longer shows in the form.
  ["#f-country", "#f-state", "#f-city", "#f-district"].forEach((sel) =>
    $(sel).addEventListener("input", () => {
      if (!state.coords) return;
      state.coords = null;
      geoStatus.textContent = t("geo.stale");
      geoStatus.className = "geo-status err";
    })
  );

  // The precision label names the finest place level the user actually filled in. A missing
  // district is never reported as "district" precision, so the form does not say "İlçe" for a city search.
  function effectivePrecision(precision, district) {
    if (precision === "district" && !(district || "").trim()) return "city";
    return precision || "city";
  }

  function fillForm(p) {
    $("#f-first").value = p?.firstName || "";
    $("#f-last").value = p?.lastName || "";
    $("#f-email").value = p?.email || "";
    $(`input[name=role][value=${p?.role || "hobby"}]`).checked = true;
    $("#f-country").value = p?.location?.country || "";
    $("#f-state").value = p?.location?.state || "";
    $("#f-city").value = p?.location?.city || "";
    $("#f-district").value = p?.location?.district || "";
    $("#f-size").value = p?.farmSize ?? "";
    $("#f-last-crops").value = p?.crops?.last || "";
    $("#f-current-crops").value = p?.crops?.current || "";
    $("#f-next-crops").value = p?.crops?.next || "";
    state.coords = p?.location?.coords || null;
    if (state.coords) {
      geoStatus.textContent = t("geo.found", {
        name: esc((state.coords.display_name || "").split(",").slice(0, 2).join(",")),
        lat: state.coords.latitude.toFixed(4),
        lon: state.coords.longitude.toFixed(4),
        precision: t("prec." + effectivePrecision(state.coords.precision, p?.location?.district)),
      });
      geoStatus.className = "geo-status ok";
    } else {
      geoStatus.textContent = "";
      geoStatus.className = "geo-status";
    }
    setPhoto(p?.photo || null);
    syncRoleSection();
    cropFields.forEach(([textSel, chipsSel]) => parseInto(textSel, chipsSel));
    $("#profile-cancel").hidden = !state.profile;
  }

  function validate() {
    const required = ["#f-first", "#f-last", "#f-email", "#f-country", "#f-city"];
    let ok = true;
    required.forEach((sel) => {
      const el = $(sel);
      const empty = !el.value.trim();
      el.classList.toggle("invalid", empty);
      if (empty) ok = false;
    });
    const email = $("#f-email");
    if (email.value.trim() && !/^[^\s@]+@gmail\.com$/i.test(email.value.trim())) {
      email.classList.add("invalid");
      showFormError(t("err.email"));
      return false;
    }
    if (!ok) { showFormError(t("err.required")); return false; }
    if (!state.coords) { showFormError(t("err.coords_first")); return false; }
    return true;
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    formError.hidden = true;
    if (!validate()) return;
    const role = currentRole();
    const size = $("#f-size").value.trim();
    state.profile = {
      firstName: $("#f-first").value.trim(),
      lastName: $("#f-last").value.trim(),
      email: $("#f-email").value.trim(),
      photo: photoData,
      role,
      location: {
        country: $("#f-country").value.trim(),
        state: $("#f-state").value.trim(),
        city: $("#f-city").value.trim(),
        district: $("#f-district").value.trim(),
        coords: state.coords,
      },
      farmSize: role === "farm" && size ? Number(size) : null,
      crops: role === "farm"
        ? {
            last: $("#f-last-crops").value.trim(),
            current: $("#f-current-crops").value.trim(),
            next: $("#f-next-crops").value.trim(),
          }
        : { last: "", current: "", next: "" },
    };
    touchProfile();
    scheduleSync();
    route();
  });

  $("#profile-cancel").addEventListener("click", () => route());

  // ---------- 3. dashboard ----------
  const WMO_ICON = (c) => {
    if (c === 0) return "☀️";
    if (c <= 2) return "🌤️";
    if (c === 3) return "☁️";
    if (c === 45 || c === 48) return "🌫️";
    if (c >= 51 && c <= 67) return "🌧️";
    if (c >= 71 && c <= 77) return "🌨️";
    if (c >= 80 && c <= 82) return "🌦️";
    if (c >= 95) return "⛈️";
    return "🌡️";
  };
  const wmoText = (c) => {
    const key = "wmo." + c;
    const s = t(key);
    return s === key ? "" : s;
  };

  async function loadDashboard() {
    const p = state.profile;
    if (!p?.location?.coords) {
      showView("view-profile");
      fillForm(p);
      return;
    }
    showView("view-dash");
    $("#dash-error").hidden = true;
    $("#dash-body").hidden = true;
    $("#dash-loading").hidden = false;
    renderHeader(p);
    if (!sarpCityEdited) $("#sarp-city").value = p.location.city || "";

    const body = {
      latitude: p.location.coords.latitude,
      longitude: p.location.coords.longitude,
      lang: state.lang || "en",
      role: p.role,
      farm_size: p.farmSize,
      crops_last: p.crops?.last || "",
      crops_current: p.crops?.current || "",
      crops_next: p.crops?.next || "",
    };
    try {
      const data = await api("/api/dashboard.php", { method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() }, body: JSON.stringify(body) });
      state.lastDash = { data, profile: p, lang: state.lang };
      renderDashboard(data, p);
      loadMarket(p); // not awaited: supplier lookup is slow and must not block the weather view
    } catch (err) {
      $("#dash-error").textContent = t("dash.load_fail") + (err.message ? ` (${err.message})` : "");
      $("#dash-error").hidden = false;
    } finally {
      $("#dash-loading").hidden = true;
    }
  }

  function renderHeader(p) {
    $("#hello").textContent = t("dash.hello", { name: p.firstName });
    // Title: district and city when the district is filled in, otherwise city, otherwise country.
    // Empty or null fields are dropped, never shown as blanks or "undefined".
    const place = [p.location.district, p.location.city].filter((v) => v && v.trim()).join(", ");
    $("#loc-title").textContent = place || p.location.city || p.location.country || "";
    const parts = [p.location.state, p.location.country].filter((v) => v && v.trim()).join(", ");
    const c = p.location.coords;
    const coordText = c ? `${c.latitude.toFixed(3)}, ${c.longitude.toFixed(3)}` : "";
    $("#loc-sub").textContent = [parts, coordText].filter(Boolean).join(" · ");
    $("#hero-meta").innerHTML = `<span class="pill">${esc(t(p.role === "farm" ? "dash.role_farm" : "dash.role_hobby"))}</span>` +
      (p.role === "farm" && p.farmSize ? `<span class="pill">${esc(t("dash.farm_size", { size: p.farmSize }))}</span>` : "");

    const nameEl = $("#user-name");
    nameEl.textContent = `${p.firstName} ${p.lastName}`.trim();
    const img = $("#user-photo");
    const initials = $("#user-initials");
    if (p.photo) {
      img.src = p.photo; img.hidden = false; initials.hidden = true;
    } else {
      img.hidden = true; initials.hidden = false;
      initials.textContent = ((p.firstName[0] || "") + (p.lastName[0] || "")).toUpperCase() || "🌱";
    }
  }

  function tile(cls, label, value, unit, sub, icon = "") {
    return `<div class="tile ${cls}">${icon ? `<span class="ico">${icon}</span>` : ""}<div>
      <div class="lbl">${esc(label)}</div>
      <div class="val">${value}${unit ? ` <small>${esc(unit)}</small>` : ""}</div>
      ${sub ? `<div class="sub">${esc(sub)}</div>` : ""}</div></div>`;
  }

  function renderDashboard({ forecast, insights, crops }, p) {
    const cur = forecast.current || {};
    const u = forecast.current_units || {};
    const daily = forecast.daily || {};
    const fmtDate = (iso, i) =>
      i === 0 ? t("day.today") : new Date(iso + "T12:00:00").toLocaleDateString(dateLocale(), { weekday: "short", day: "numeric", month: "short" });

    $("#tiles").innerHTML = [
      tile("main", t("tile.temp"), num(cur.temperature_2m, 1), u.temperature_2m || "°C",
        t("tile.feels", { v: num(cur.apparent_temperature, 1) + "°" }), wmoText(cur.weather_code), WMO_ICON(cur.weather_code)),
      tile("", t("tile.humidity"), num(cur.relative_humidity_2m), "%"),
      tile("", t("tile.wind"), num(cur.wind_speed_10m, 1), u.wind_speed_10m || "km/h",
        t("tile.gusts", { v: num(cur.wind_gusts_10m, 1) + " " + (u.wind_gusts_10m || "km/h") })),
      tile("", t("tile.rain"), num(cur.precipitation, 1), u.precipitation || "mm"),
      tile("", t("tile.pressure"), num(cur.pressure_msl, 0), u.pressure_msl || "hPa"),
    ].join("");

    const times = (daily.time || []).slice(0, getUi().forecastDays);
    $("#wx-body").innerHTML = times.map((d, i) => {
      const min = daily.temperature_2m_min?.[i];
      const max = daily.temperature_2m_max?.[i];
      const minCls = min <= 0 ? "cold" : "";
      const maxCls = max >= 35 ? "hot" : "";
      return `<tr>
        <td>${esc(fmtDate(d, i))}</td>
        <td>${WMO_ICON(daily.weather_code?.[i])} ${esc(wmoText(daily.weather_code?.[i]))}</td>
        <td class="${minCls}">${num(min, 1)}</td>
        <td class="${maxCls}">${num(max, 1)}</td>
        <td>${num(daily.precipitation_sum?.[i], 1)}</td>
        <td>${num(daily.precipitation_probability_max?.[i])}</td>
        <td>${num(daily.wind_speed_10m_max?.[i], 0)}</td>
        <td>${num(daily.uv_index_max?.[i], 1)}</td>
      </tr>`;
    }).join("");

    // farm summary
    const farmSec = $("#crop-summary");
    farmSec.hidden = p.role !== "farm";
    if (p.role === "farm") {
      const row = (label, parsed) => `<div class="farm-row"><b>${esc(label)}</b>${
        parsed.crops.map((c) => `<span class="chip">${esc(c.name)}</span>`).join("") +
        parsed.unknown.map((u) => `<span class="chip unk">${esc(u)}</span>`).join("") ||
        "<span class='muted small'>–</span>"}</div>`;
      $("#farm-card").innerHTML =
        `<div class="farm-row"><b>${esc(t("dash.farm_size", { size: p.farmSize ?? "–" }))}</b></div>` +
        row(t("profile.crops_last"), crops.last) +
        row(t("profile.crops_current"), crops.current) +
        row(t("profile.crops_next"), crops.next);
    }

    const rec = insights.filter((i) => i.type === "recommend");
    const avoid = insights.filter((i) => i.type === "avoid");
    const card = (i) => `<article class="icard ${esc(i.severity)}">
      <span class="ico">${esc(i.icon)}</span><h3>${esc(i.title)}</h3><p>${esc(i.text)}</p></article>`;
    $("#cards-rec").innerHTML = rec.map(card).join("") || `<div class="empty">${esc(t("dash.empty_insights"))}</div>`;
    $("#cards-avoid").innerHTML = avoid.map(card).join("") || `<div class="empty">${esc(t("dash.empty_insights"))}</div>`;

    $("#dash-body").hidden = false;
  }

  // ---------- 3b. local suppliers & cost insights ----------
  const safeHttp = (u) => (/^https?:\/\//i.test(u || "") ? u : "");
  const telHref = (ph) => {
    const d = String(ph || "").replace(/[^\d+]/g, "");
    return d ? "tel:" + d : "";
  };
  // Formats in the region's currency and locale, e.g. "₺1.200", "1.200 €", "$1,200".
  const money = (n, cur) => {
    try {
      return new Intl.NumberFormat(cur.locale, { style: "currency", currency: cur.code, maximumFractionDigits: 0 }).format(n);
    } catch {
      return `${Math.round(n).toLocaleString(cur.locale)} ${cur.code}`;
    }
  };
  const CAT_ICON = { seed: "🌾", machinery: "🚜", inputs: "🧪", garden: "🪴" };

  async function loadMarket(p) {
    const c = p.location.coords;
    $("#market-suppliers").innerHTML =
      `<div class="loading small"><span class="spinner"></span><span>${esc(t("mkt.loading"))}</span></div>`;
    $("#market-costs").innerHTML = "";
    // Centre = the geocoded point for the place the user chose; radius follows its precision on the server.
    const qs = new URLSearchParams({
      latitude: c.latitude,
      longitude: c.longitude,
      lang: state.lang || "en",
      precision: c.precision || "city",
      city: p.location.city || "",
      state: p.location.state || "",
      country: p.location.country || "",
      country_code: c.country_code || "",
    });
    if (p.role === "farm" && p.farmSize) qs.set("farm_size", p.farmSize);
    try {
      renderMarket(await api("/api/market.php?" + qs.toString(), { headers: authHeaders() }), p);
    } catch {
      $("#market-suppliers").innerHTML = `<div class="alert warn">${esc(t("mkt.unavailable"))}</div>`;
    }
  }

  function supplierCard(i) {
    const name = i.name || t("mkt.cat." + i.category);
    const links = [];
    if (telHref(i.phone)) links.push(`<a href="${esc(telHref(i.phone))}">${esc(t("mkt.call"))}: ${esc(i.phone)}</a>`);
    if (safeHttp(i.website)) links.push(`<a href="${esc(safeHttp(i.website))}" target="_blank" rel="noopener">${esc(t("mkt.website"))}</a>`);
    if (safeHttp(i.osm_url)) links.push(`<a href="${esc(i.osm_url)}" target="_blank" rel="noopener">${esc(t("mkt.map"))}</a>`);
    return `<article class="icard info sup">
      <span class="ico">${CAT_ICON[i.category] || "🧺"}</span>
      <div class="sup-body">
        <h3>${esc(name)}</h3>
        <p>${esc(t("mkt.cat." + i.category))} · ${esc(t("mkt.km", { km: i.distance_km }))}</p>
        ${i.address ? `<p>${esc(i.address)}</p>` : ""}
        ${i.opening_hours ? `<p class="small">${esc(i.opening_hours)}</p>` : ""}
        ${links.length ? `<p class="links">${links.join(" · ")}</p>` : ""}
      </div>
    </article>`;
  }

  function renderMarket(m, p) {
    const sup = m.suppliers || { status: "unavailable", items: [] };
    const linkFor = Object.fromEntries((m.search_links || []).map((l) => [l.category, l.url]));
    let html = "";
    if (sup.status === "needs_place") {
      html += `<div class="empty">${esc(t("mkt.needs_place"))}</div>`;
    } else if (sup.status !== "ok") {
      html += `<div class="alert warn">${esc(t("mkt.unavailable"))}</div>`;
    } else if (!sup.items.length) {
      html += `<div class="empty">${esc(t("mkt.none", { km: m.radius_km }))}</div>`;
    } else {
      html += `<div class="cards">${sup.items.map(supplierCard).join("")}</div>`;
    }
    html += `<h3 class="sub-h">${esc(t("mkt.search_title"))}</h3><div class="link-row">` +
      ["seed", "machinery", "inputs"].map((cat) =>
        linkFor[cat] ? `<a class="btn sm ghost" href="${esc(safeHttp(linkFor[cat]))}" target="_blank" rel="noopener">${esc(t("mkt.search." + cat))}</a>` : ""
      ).join("") +
      (m.coop_url ? `<a class="btn sm ghost" href="${esc(safeHttp(m.coop_url))}" target="_blank" rel="noopener">${esc(t("mkt.coop"))}</a>` : "") +
      `</div>`;
    $("#market-suppliers").innerHTML = html;

    const c = m.costs;
    const tips = c.tips.map((tip) => `<article class="icard good">
        <span class="ico">${esc(tip.icon)}</span><h3>${esc(tip.title)}</h3><p>${esc(tip.text)}</p></article>`).join("");
    if (!c.benchmarks) {
      $("#market-costs").innerHTML = `
        <p class="alert warn">${esc(t("mkt.costs_unavailable"))}</p>
        <h3 class="sub-h">${esc(t("mkt.tips"))}</h3>
        <div class="cards">${tips}</div>`;
      return;
    }
    const cur = c.currency;
    const hasFarm = !!c.total;
    const rows = c.estimates.map((e) => `<tr>
        <td>${esc(e.icon)} ${esc(e.label)}</td>
        <td>${money(e.min_per_decare, cur)} – ${money(e.max_per_decare, cur)}</td>
        ${hasFarm ? `<td>${money(e.total_min, cur)} – ${money(e.total_max, cur)}</td>` : ""}
      </tr>`).join("");
    const totalRow = hasFarm
      ? `<tr class="total"><td><b>${esc(t("mkt.total_label"))}</b></td><td></td><td><b>${money(c.total.min, cur)} – ${money(c.total.max, cur)}</b></td></tr>`
      : "";
    $("#market-costs").innerHTML = `
      <div class="table-wrap"><table class="costs">
        <thead><tr><th>${esc(t("mkt.col_input"))}</th><th>${esc(t("mkt.col_per_decare"))}</th>
          ${hasFarm ? `<th>${esc(t("mkt.col_farm"))}</th>` : ""}</tr></thead>
        <tbody>${rows}${totalRow}</tbody>
      </table></div>
      <p class="hint">${esc(t("mkt.costs_note"))}</p>
      <h3 class="sub-h">${esc(t("mkt.tips"))}</h3>
      <div class="cards">${tips}</div>`;
  }

  $("#btn-refresh").addEventListener("click", () => loadDashboard());
  // ---------- 4. settings ----------
  const DEFAULT_UI = { theme: "system", density: "comfortable", forecastDays: 7 };
  const getUi = () => ({ ...DEFAULT_UI, ...(store.ui || {}) });

  // Light/dark follows the OS unless the user picked one; "system" removes the override.
  function applyUi() {
    const ui = getUi();
    if (ui.theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.dataset.theme = ui.theme;
    document.body.classList.toggle("density-compact", ui.density === "compact");
    refreshSarpCharts();   // chart colours come from the theme tokens, so a theme change redraws them
  }
  // A local edit: marks the profile as changed and schedules a push when signed in.
  function setUi(patch) {
    writeUi(patch);
    touchProfile();
    scheduleSync();
  }
  // Display preferences only, with no sync bookkeeping. Used when a cloud copy is applied.
  function writeUi(patch) {
    store.ui = { ...getUi(), ...patch };
    saveStore(store);
    applyUi();
  }

  function renderPrefs() {
    const ui = getUi();
    const current = {
      theme: ui.theme,
      density: ui.density,
      forecastDays: String(ui.forecastDays),
      lang: state.lang || "en",
    };
    $$("[data-pref]").forEach((group) => {
      const value = current[group.dataset.pref];
      $$("button", group).forEach((b) => b.setAttribute("aria-checked", String(b.dataset.value === value)));
    });
  }

  $$(".seg[data-pref]").forEach((group) =>
    group.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-value]");
      if (!b) return;
      const key = group.dataset.pref;
      if (key === "lang") setLang(b.dataset.value);
      else if (key === "forecastDays") setUi({ forecastDays: Number(b.dataset.value) });
      else setUi({ [key]: b.dataset.value });
      renderPrefs();
    })
  );

  function selectSettingsTab(tab) {
    $$(".tab[data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    $$("[data-panel]").forEach((p) => (p.hidden = p.dataset.panel !== tab));
    if (tab === "account") refreshAccount();
  }
  $$(".tab[data-tab]").forEach((b) => b.addEventListener("click", () => selectSettingsTab(b.dataset.tab)));

  function openSettings(tab = "profile") {
    showView("view-settings");
    selectSettingsTab(tab);
    if (tab === "profile") fillForm(state.profile);
    renderPrefs();
  }

  // Leaving Settings: if the language changed, the weather insights must be fetched again in it.
  function closeSettings() {
    if (!state.profile) return route();
    if (!state.lastDash || state.lastDash.lang !== state.lang) return loadDashboard();
    showView("view-dash");
  }

  $("#btn-profile").addEventListener("click", () => openSettings("profile"));
  $("#btn-settings").addEventListener("click", () => openSettings("profile"));
  $("#settings-back").addEventListener("click", () => closeSettings());
  $("#btn-lang").addEventListener("click", () => {
    const onProfile = !$("#view-profile").hidden;
    const draft = onProfile ? collectDraft() : null;
    setLang(state.lang === "tr" ? "en" : "tr");
    if (onProfile) fillForm(draft);
    else if (state.profile) loadDashboard();
  });

  // partial form values, used when switching language mid-onboarding
  function collectDraft() {
    return { role: currentRole(), firstName: $("#f-first").value, lastName: $("#f-last").value, email: $("#f-email").value,
      location: { country: $("#f-country").value, state: $("#f-state").value, city: $("#f-city").value, district: $("#f-district").value, coords: state.coords },
      farmSize: $("#f-size").value, crops: { last: $("#f-last-crops").value, current: $("#f-current-crops").value, next: $("#f-next-crops").value }, photo: photoData };
  }

  // ---------- 4b. accounts: sign-in, sign-up, sessions and cloud sync ----------
  // Tokens live in sessionStorage: they end with the tab. The profile itself is in the cloud, so the
  // next sign-in (on this or another device) brings it back. The server rotates refresh tokens on
  // every use, so each refresh stores the new one.
  const SESSION_KEY = "farmedia.session";
  const CONSENT_BOXES = {
    alert_email_consent: "#consent-alert-email",
    alert_sms_consent: "#consent-alert-sms",
    marketing_email_consent: "#consent-marketing-email",
    do_not_sell: "#consent-do-not-sell",
  };
  const acc = { token: null, refresh: null, email: null };

  function writeSession(token, refresh) {
    acc.token = token || null;
    acc.refresh = refresh || null;
    try {
      if (token) sessionStorage.setItem(SESSION_KEY, JSON.stringify({ a: token, r: refresh || null }));
      else sessionStorage.removeItem(SESSION_KEY);
    } catch { /* private mode: keep in memory only */ }
  }
  (function loadSession() {
    try {
      const s = JSON.parse(sessionStorage.getItem(SESSION_KEY) || "null");
      if (s && s.a) writeSession(s.a, s.r || null);
    } catch { /* unreadable: stay signed out */ }
  })();

  function setStatus(el, msg, kind = "") {
    el.textContent = msg;
    el.className = "geo-status" + (kind ? " " + kind : "");
  }

  function fillConsents(profile) {
    for (const [key, sel] of Object.entries(CONSENT_BOXES)) $(sel).checked = profile?.[key] === true;
  }

  function renderAccount() {
    const signedIn = !!acc.token;
    $("#acc-guest").hidden = signedIn;
    $("#acc-user").hidden = !signedIn;
    $("#acc-who").textContent = signedIn && acc.email ? t("acc.signed_in_as", { email: acc.email }) : "";
  }

  // Drops the local session. msgKey, if given, is shown in the account panel.
  function signedOut(msgKey) {
    writeSession(null);
    acc.email = null;
    fillConsents(null);
    renderAccount();
    if (msgKey) setStatus($("#acc-login-status"), t(msgKey), "err");
  }

  // 401 means the session is gone: sign out and say so. Other errors show the given message.
  function failWithAuth(err, el, msgKey) {
    if (err.status === 401) return signedOut("acc.session_expired");
    setStatus(el, t(msgKey), "err");
  }

  // One refresh at a time: if several calls fail together, they share the same refresh.
  // Returns true (new session), false (no session to refresh or it was rejected) or "network".
  let refreshing = null;
  async function refreshSession() {
    if (!acc.refresh) return false;
    if (!refreshing) {
      refreshing = (async () => {
        try {
          const r = await api("/api/auth/refresh.php", { method: "POST", body: JSON.stringify({ refresh_token: acc.refresh }) });
          writeSession(r.session.access_token, r.session.refresh_token);
          return true;
        } catch (err) {
          return err.message === "network" ? "network" : false;
        } finally {
          refreshing = null;
        }
      })();
    }
    return refreshing;
  }

  // fetch with the bearer token. On 401 it refreshes once and retries. If the refresh is rejected the
  // user is signed out, unless keepSessionOn401 is set (used for a wrong password on account deletion).
  async function authedFetch(path, opts = {}, retried = false) {
    const { keepSessionOn401, ...init } = opts;
    const headers = { ...(init.headers || {}), Authorization: "Bearer " + acc.token };
    if (init.body) headers["Content-Type"] = "application/json";
    let res;
    try {
      res = await fetch(path, { ...init, headers });
    } catch {
      throw new Error("network");
    }
    if (res.status !== 401 || retried) return res;
    const refreshed = await refreshSession();
    if (refreshed === true) return authedFetch(path, opts, true);
    if (refreshed === "network") throw new Error("network");
    if (!keepSessionOn401) signedOut("acc.session_expired");
    return res;
  }

  async function authed(path, opts = {}) {
    const res = await authedFetch(path, opts);
    return readBody(res);
  }

  // Signed-in user's email, plus the cloud profile row (RLS limits it to this user).
  async function loadAccount() {
    const me = await authed("/api/auth/me.php");
    acc.email = me.user?.email || null;
    return me;
  }

  async function refreshAccount() {
    renderAccount();
    if (!acc.token) return;
    try {
      const me = await loadAccount();
      fillConsents(me.profile);
      renderAccount();
    } catch (err) {
      failWithAuth(err, $("#consent-status"), "err.generic");
    }
  }

  // ---- cloud profile sync ----
  // Last change wins. A cloud row updated after this device's last edit replaces the local profile.
  // Otherwise the local profile is pushed up. Photos stay on the device that set them.
  const isNewer = (a, b) => !!a && (!b || Date.parse(a) > Date.parse(b));
  let syncTimer = null;

  function touchProfile() {
    if (!state.profile) return;
    state.profile.updatedAt = new Date().toISOString();
    store.profile = state.profile;
    saveStore(store);
  }

  function profileForCloud(p) {
    return {
      first_name: p.firstName,
      last_name: p.lastName,
      role: p.role === "farm" ? "farm" : "hobby",
      farm_size: p.role === "farm" && p.farmSize ? Number(p.farmSize) : undefined, // dropped from JSON if absent
      location: { ...p.location },
      crops: { ...p.crops },
      preferences: { theme: getUi().theme, density: getUi().density, forecastDays: Number(getUi().forecastDays) },
    };
  }

  // Replaces the local profile and preferences with the cloud copy.
  function adoptCloud(cloud) {
    const loc = cloud.location || {};
    const crops = cloud.crops || {};
    state.profile = {
      firstName: cloud.first_name || "",
      lastName: cloud.last_name || "",
      email: cloud.email || acc.email || "",
      photo: state.profile?.photo || null,
      role: cloud.role === "farm" ? "farm" : "hobby",
      location: {
        country: loc.country || "", state: loc.state || "", city: loc.city || "",
        district: loc.district || "", coords: loc.coords || null,
      },
      farmSize: cloud.farm_size ?? null,
      crops: { last: crops.last || "", current: crops.current || "", next: crops.next || "" },
      updatedAt: cloud.updated_at,
    };
    store.profile = state.profile;
    saveStore(store);
    const prefs = cloud.preferences || {};
    const ui = {};
    if (["system", "light", "dark"].includes(prefs.theme)) ui.theme = prefs.theme;
    if (["comfortable", "compact"].includes(prefs.density)) ui.density = prefs.density;
    if ([3, 5, 7].includes(prefs.forecastDays)) ui.forecastDays = prefs.forecastDays;
    if (Object.keys(ui).length) writeUi(ui);   // writeUi, not setUi: this must not count as a local edit
  }

  async function pushProfile() {
    if (!acc.token || !state.profile) return;
    setStatus($("#sync-status"), t("sync.saving"));
    try {
      const r = await authed("/api/profile.php", { method: "PATCH", body: JSON.stringify(profileForCloud(state.profile)) });
      if (r?.profile?.updated_at && state.profile) {
        state.profile.updatedAt = r.profile.updated_at;   // server time, so the two clocks agree next time
        store.profile = state.profile;
        saveStore(store);
      }
      setStatus($("#sync-status"), t("sync.saved"), "ok");
    } catch (err) {
      if (err.status === 401) return;   // already signed out
      setStatus($("#sync-status"), t("sync.failed"), "err");
    }
  }

  // Called after every local edit. Waits briefly so typing does not send a request per keystroke.
  function scheduleSync() {
    if (!acc.token) return;
    clearTimeout(syncTimer);
    syncTimer = setTimeout(() => pushProfile(), 800);
  }

  async function syncAfterSignIn() {
    const me = await loadAccount();
    const cloud = me.profile;
    const cloudHasProfile = !!(cloud && cloud.location && (cloud.location.city || cloud.location.coords));
    if (cloudHasProfile && (!state.profile || isNewer(cloud.updated_at, state.profile.updatedAt))) {
      adoptCloud(cloud);
      setStatus($("#sync-status"), t("sync.pulled"), "ok");
    } else if (state.profile) {
      await pushProfile();
    }
    renderAccount();
  }

  // Runs after sign-in or sign-up with a session. A failed sync keeps the session and shows the state.
  let syncedThisLoad = false;
  async function finishSignIn() {
    syncedThisLoad = true;
    try {
      await syncAfterSignIn();
    } catch (err) {
      if (err.status !== 401) setStatus($("#sync-status"), t("sync.failed"), "err");
    }
    route();
  }

  // ---- Settings > Account: consents, data export, deletion ----
  $("#acc-open-auth").addEventListener("click", () => showAuth("signin"));

  $("#acc-logout").addEventListener("click", () => {
    const token = acc.token;
    signedOut();
    if (token) {
      // Revokes this device's session on the server. The local profile stays on this device.
      fetch("/api/auth/logout.php", { method: "POST", headers: { Authorization: "Bearer " + token } }).catch(() => {});
    }
    setStatus($("#consent-status"), "");
    setStatus($("#rights-status"), "");
    setStatus($("#delete-status"), "");
  });

  $("#consent-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const status = $("#consent-status");
    const body = {};
    for (const [key, sel] of Object.entries(CONSENT_BOXES)) body[key] = $(sel).checked;
    setStatus(status, t("common.loading"));
    try {
      await authed("/api/profile.php", { method: "PATCH", body: JSON.stringify(body) });
      setStatus(status, t("acc.consents_saved"), "ok");
    } catch (err) {
      failWithAuth(err, status, "acc.save_fail");
    }
  });

  $("#btn-export").addEventListener("click", async () => {
    const status = $("#rights-status");
    setStatus(status, t("common.loading"));
    try {
      const res = await authedFetch("/api/profile/export.php");
      if (!res.ok) throw Object.assign(new Error("export"), { status: res.status });
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = "farmedia-export.json";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setStatus(status, "");
    } catch (err) {
      failWithAuth(err, status, "err.generic");
    }
  });

  $("#delete-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const status = $("#delete-status");
    const password = $("#delete-password").value;
    if (!password) return setStatus(status, t("acc.password_required"), "err");
    if (!window.confirm(t("acc.delete_confirm"))) return;
    setStatus(status, t("common.loading"));
    try {
      // keepSessionOn401: a wrong password and an expired session both return 401. The message covers
      // both, and the user stays signed in so they can try again.
      const res = await authedFetch("/api/account.php", {
        method: "DELETE", body: JSON.stringify({ password }), keepSessionOn401: true,
      });
      if (!res.ok) throw Object.assign(new Error("delete"), { status: res.status });
    } catch {
      return setStatus(status, t("acc.delete_fail"), "err");
    }
    $("#delete-password").value = "";
    signedOut();
    setStatus($("#acc-login-status"), t("acc.deleted"), "ok");
  });

  // ---- auth view: separate Sign in and Sign up forms, right after the language gate ----
  let signupFor = null;     // country|locale the consent boxes were built for
  let signupReq = null;     // last /api/legal/requirements response

  function showAuth(tab = "signin") {
    showView("view-auth");
    selectAuthTab(tab);
  }

  function selectAuthTab(tab) {
    $$("[data-auth-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.authTab === tab)));
    $("#form-signin").hidden = tab !== "signin";
    $("#form-signup").hidden = tab !== "signup";
    if (tab === "signup") loadSignupRequirements();
  }
  $$("[data-auth-tab]").forEach((b) => b.addEventListener("click", () => selectAuthTab(b.dataset.authTab)));
  $("#su-country").addEventListener("change", () => loadSignupRequirements(true));

  const REQUIRED_LABEL = {
    terms: "auth.consent.terms",
    privacy_policy: "auth.consent.privacy_policy",
    kvkk_explicit: "auth.consent.kvkk_explicit",
    kvkk_transfer: "auth.consent.kvkk_transfer",
  };
  const OPTIONAL_LABEL = {
    alert_email: "acc.alert_email",
    alert_sms: "acc.alert_sms",
    marketing_email: "acc.marketing_email",
    do_not_sell: "acc.do_not_sell",
  };

  // Shows the consents the chosen country requires, plus the current document versions and links.
  async function loadSignupRequirements(force = false) {
    const country = $("#su-country").value;
    const locale = state.lang === "tr" ? "tr" : "en";
    const key = country + "|" + locale;
    if (!force && signupFor === key) return;
    $("#su-submit").disabled = true;
    try {
      const r = await api(`/api/legal/requirements.php?country=${encodeURIComponent(country)}&locale=${locale}`);
      signupReq = r;
      renderSignupConsents(r);
      signupFor = key;
      $("#su-submit").disabled = !r.ready;
      setStatus($("#su-status"), r.ready ? "" : t("auth.not_ready"), r.ready ? "" : "err");
    } catch {
      signupFor = null;
      setStatus($("#su-status"), t("auth.requirements_fail"), "err");
    }
  }

  function renderSignupConsents(r) {
    const required = r.required_consents.map((c) =>
      `<label class="check"><input type="checkbox" name="consent" value="${esc(c)}"><span>${esc(t(REQUIRED_LABEL[c] || c))}</span></label>`);
    const optional = r.optional_consents.map((c) =>
      `<label class="check"><input type="checkbox" name="consent" value="${esc(c)}"><span>${esc(t(OPTIONAL_LABEL[c] || c))}</span></label>`);
    $("#su-consents").innerHTML = required.join("") +
      (optional.length ? `<p class="hint">${esc(t("auth.optional_hint"))}</p>` + optional.join("") : "");
    const links = [];
    if (r.documents.terms) links.push(`<a href="${esc(safeHttp(r.documents.terms.url))}" target="_blank" rel="noopener">${esc(t("auth.doc_terms"))}</a> (${esc(r.documents.terms.version)})`);
    if (r.documents.privacy) links.push(`<a href="${esc(safeHttp(r.documents.privacy.url))}" target="_blank" rel="noopener">${esc(t("auth.doc_privacy"))}</a> (${esc(r.documents.privacy.version)})`);
    $("#su-docs").innerHTML = links.join(" · ");
  }

  // Sign-in. Errors: wrong password or unknown email (generic), email not yet confirmed (own message).
  $("#form-signin").addEventListener("submit", async (e) => {
    e.preventDefault();
    const status = $("#si-status");
    const email = $("#si-email").value.trim();
    const password = $("#si-password").value;
    if (!email || !password) return setStatus(status, t("err.required"), "err");
    setStatus(status, t("acc.signing_in"));
    let r;
    try {
      r = await api(`/api/auth/login.php?lang=${state.lang === "tr" ? "tr" : "en"}`, {
        method: "POST", body: JSON.stringify({ email, password }),
      });
    } catch (err) {
      let msg = t("err.generic");
      if (err.code === "email_not_confirmed") msg = t("auth.not_confirmed");
      else if (err.status === 401) msg = t("acc.signin_fail");
      return setStatus(status, msg, "err");
    }
    $("#si-password").value = "";
    writeSession(r.session.access_token, r.session.refresh_token);
    setStatus(status, "");
    await finishSignIn();
  });

  // Sign-up. The server re-checks every consent and version, so the client checks are only for feedback.
  $("#form-signup").addEventListener("submit", async (e) => {
    e.preventDefault();
    const status = $("#su-status");
    const first = $("#su-first").value.trim();
    const last = $("#su-last").value.trim();
    const email = $("#su-email").value.trim();
    const password = $("#su-password").value;
    if (!first || !last || !email || !password) return setStatus(status, t("err.required"), "err");
    if (password.length < 6) return setStatus(status, t("auth.password_short"), "err");
    if (password !== $("#su-password2").value) return setStatus(status, t("auth.password_mismatch"), "err");
    if (!signupReq) return setStatus(status, t("auth.requirements_fail"), "err");

    const boxes = Object.fromEntries([...$$("#su-consents input[name=consent]")].map((i) => [i.value, i.checked]));
    if (signupReq.required_consents.some((c) => !boxes[c])) return setStatus(status, t("auth.consent_missing"), "err");

    const docs = signupReq.documents;
    const body = {
      email, password, first_name: first, last_name: last,
      country: $("#su-country").value,
      locale: state.lang === "tr" ? "tr" : "en",
      terms_version: docs.terms?.version || "",
      privacy_version: docs.privacy?.version || "",
      terms_accepted: !!boxes.terms,
      privacy_accepted: !!boxes.privacy_policy,
      kvkk_explicit: !!boxes.kvkk_explicit,
      kvkk_transfer: !!boxes.kvkk_transfer,
      alert_email: !!boxes.alert_email,
      alert_sms: !!boxes.alert_sms,
      marketing_email: !!boxes.marketing_email,
      do_not_sell: !!boxes.do_not_sell,
    };
    setStatus(status, t("auth.signing_up"));
    let r;
    try {
      r = await api(`/api/auth/register.php?lang=${body.locale}`, { method: "POST", body: JSON.stringify(body) });
    } catch (err) {
      return setStatus(status, err.message && err.status ? err.message : t("err.generic"), "err");
    }
    $("#su-password").value = "";
    $("#su-password2").value = "";
    setStatus(status, "");
    if (r.session) {
      writeSession(r.session.access_token, r.session.refresh_token);
      await finishSignIn();
      return;
    }
    // Email confirmation is on: the account exists, but it cannot sign in until the link is clicked.
    $("#si-email").value = email;
    setStatus($("#si-status"), t("auth.check_email"), "ok");
    selectAuthTab("signin");
  });

  $("#auth-skip").addEventListener("click", () => {
    store.authSkipped = true;
    saveStore(store);
    route();
  });

  // ---------- 5. Sarp AI advisor chat ----------
  // Posts to POST /api/sarp-ai.php (PHP, Claude) with the question, the chosen city and the current language.
  // The chat is shown on the dashboard only. Messages live in the page and are not stored.
  let sarpOpen = false;
  let sarpBusy = false;
  let sarpCityEdited = false;
  const sarpLog = $("#sarp-log");

  // Show the floating button on the dashboard, and the panel only while it is open.
  function syncSarp() {
    const onDash = !$("#view-dash").hidden;
    $("#sarp-open").hidden = !onDash || sarpOpen;
    $("#sarp-panel").hidden = !onDash || !sarpOpen;
    $("#sarp-open").setAttribute("aria-expanded", String(sarpOpen));
  }
  function openSarp() {
    sarpOpen = true;
    syncSarp();
    updateSarpShareNote();
    $("#sarp-input").focus();
  }
  function closeSarp() {
    sarpOpen = false;
    syncSarp();
    $("#sarp-open").focus();
  }
  $("#sarp-open").addEventListener("click", openSarp);
  $("#sarp-close").addEventListener("click", closeSarp);

  // Expand the panel for longer answers and charts; the label says what the button will do.
  $("#sarp-expand").addEventListener("click", () => {
    const panel = $("#sarp-panel");
    const expanded = !panel.classList.contains("expanded");
    panel.classList.toggle("expanded", expanded);
    const label = t(expanded ? "sarp.collapse" : "sarp.expand");
    const btn = $("#sarp-expand");
    btn.setAttribute("aria-expanded", String(expanded));
    btn.title = label;
    btn.setAttribute("aria-label", label);
  });

  // Quick chips ask a ready-made question straight away, in the current language.
  $$("[data-sarp-chip]").forEach((chip) =>
    chip.addEventListener("click", () => {
      if (sarpBusy) return;
      $("#sarp-input").value = t("sarp.q_" + chip.dataset.sarpChip);
      $("#sarp-form").requestSubmit();
    })
  );
  $("#sarp-city").addEventListener("input", () => (sarpCityEdited = true));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && sarpOpen) closeSarp(); });

  // Enter sends; Shift+Enter inserts a new line.
  $("#sarp-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      $("#sarp-form").requestSubmit();
    }
  });

  // ---- Sarp AI charts ----
  // The model writes a line such as:
  //   Chart: Line chart – X ekseni “Hafta”, Y ekseni “Yağış (mm)”, veri noktaları 12, 4, 25, 8.
  // parseChartLine turns it into a spec. Labels come from a "Label: value" list above it when the
  // values match; otherwise they are numbered. Lines that cannot be parsed stay as plain text.
  const CHART_LINE = /^(\*\*|__)?\s*(chart|grafik)\s*:/i;
  const CHART_JS_URL = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js";
  // Series colours are the palette tokens --series-1..6 (style.css, validated in data-viz palette.md).
  // The constant is only a fallback if the stylesheet did not load.
  const SERIES_FALLBACK = ["#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17"];
  const LINE_LIKE = ["line", "bar", "area"];

  function chartType(text) {
    const s = text.slice(0, 40).toLowerCase();   // the chart type is named first
    if (/doughnut|donut|halka/.test(s)) return "doughnut";
    if (/\bpie\b|pasta/.test(s)) return "pie";
    if (/\barea\b|\balan grafi/.test(s)) return "area";
    if (/\bbar\b|column|sütun|çubuk/.test(s)) return "bar";
    return "line";
  }

  // Reads X ekseni / Y ekseni (or X axis / Y-axis) titles, quoted or as far as a comma or "data".
  function axisTitle(text, axis) {
    const re = axis === "x"
      ? /\bx[\s-]*(?:ekseni|axis)\s*[:=]?\s*/i
      : /\by[\s-]*(?:ekseni|axis)\s*[:=]?\s*/i;
    const m = re.exec(text);
    if (!m) return "";
    const rest = text.slice(m.index + m[0].length);
    const quoted = rest.match(/^[“"‘']([^”"’']+)[”"’']/);
    if (quoted) return quoted[1].trim();
    return rest.split(/[,;]|\s(?:ve|and)\s|veri|data/i)[0].trim().replace(/\.$/, "");
  }

  // Numbers after "veri noktaları" / "data points" / "values". Comma decimals ("1,5") are accepted;
  // a comma followed by a space is a list separator.
  function dataPoints(text) {
    const m = /(?:veri\s+noktalar[ıi]|veriler|data\s*points|values|değerler|data)\s*[:=\-–]?\s*(.+)$/i.exec(text);
    if (!m) return [];
    return [...m[1].matchAll(/-?\d+(?:,\d+)?(?:\.\d+)?/g)].map((x) => parseFloat(x[0].replace(",", ".")));
  }

  // Finds "Label: 12 mm" list items above the chart and keeps the labels when their values match.
  function labelsFromList(lines, values) {
    const pairs = [];
    for (const raw of lines) {
      const m = /^\s*[-*•]\s+(.+)$/.exec(raw);
      if (!m) continue;
      const item = /^(.+?):\s*\**\s*(-?\d+(?:,\d+)?(?:\.\d+)?)/.exec(m[1].replace(/\*\*/g, ""));
      if (item) pairs.push({ label: item[1].trim(), value: parseFloat(item[2].replace(",", ".")) });
    }
    for (let s = 0; s + values.length <= pairs.length; s++) {
      if (values.every((v, k) => Math.abs(pairs[s + k].value - v) < 1e-9)) {
        return pairs.slice(s, s + values.length).map((p) => p.label);
      }
    }
    return null;
  }

  // Markdown tables in the answer, as { start, end, head, rows }.
  function tableAt(lines, start) {
    if (!/^\s*\|/.test(lines[start] || "") || !isTableSep((lines[start + 1] || "").trim())) return null;
    const head = splitRow(lines[start].trim());
    const rows = [];
    let end = start + 1;
    for (let k = start + 2; k < lines.length && /^\s*\|/.test(lines[k]); k++) {
      rows.push(splitRow(lines[k].trim()));
      end = k;
    }
    return { start, end, head, rows };
  }
  function tablesIn(lines) {
    const found = [];
    for (let k = 0; k < lines.length; k++) {
      const table = tableAt(lines, k);
      if (table) { found.push(table); k = table.end; }
    }
    return found;
  }
  // The table closest to the chart line (within 6 lines), preferring the one just below it.
  function tableNear(lines, c) {
    const tables = tablesIn(lines);
    return tables.find((tb) => tb.start > c && tb.start - c <= 6)
      || tables.filter((tb) => tb.end < c && c - tb.end <= 6).pop() || null;
  }
  const numberIn = (cell) => {
    const m = /^-?\d+(?:,\d+)?(?:\.\d+)?/.exec(String(cell || "").replace(/\*\*/g, "").trim());
    return m ? parseFloat(m[0].replace(",", ".")) : null;
  };

  // Series from a table: the first column is the x axis, every later numeric column is a series.
  function chartFromTable(table) {
    const series = [];
    for (let j = 1; j < table.head.length && series.length < 4; j++) {
      const data = table.rows.map((r) => numberIn(r[j]));
      if (data.length >= 2 && data.every((v) => v !== null)) series.push({ name: table.head[j], data });
    }
    if (!series.length) return null;
    const labels = table.rows.map((r) => (numberIn(r[0]) !== null ? `${table.head[0]} ${r[0]}` : r[0]));
    return {
      xLabel: table.head[0],
      yLabel: series.length === 1 ? series[0].name : "",
      labels,
      series,
    };
  }

  // Chart line data comes first: numbers after "veri noktaları" with labels from the list above.
  // Otherwise the nearest markdown table supplies the data. Anything else stays text.
  function parseChartLine(line, allLines, c) {
    const body = line.replace(CHART_LINE, "").replace(/\*\*/g, "").trim();
    const type = chartType(body);
    const values = dataPoints(body);
    if (values.length >= 2) {
      const xLabel = axisTitle(body, "x");
      const yLabel = axisTitle(body, "y");
      const labels = labelsFromList(allLines, values) ||
        values.map((_, i) => (xLabel ? `${xLabel} ${i + 1}` : String(i + 1)));
      return {
        type,
        title: [yLabel, xLabel].filter(Boolean).join(" · "),
        xLabel,
        yLabel,
        labels,
        series: [{ name: yLabel || t("sarp.chart_value"), data: values }],
      };
    }
    const table = tableNear(allLines, c);
    const fromTable = table && chartFromTable(table);
    if (!fromTable) return null;
    const yLabel = fromTable.yLabel || axisTitle(body, "y");
    return {
      ...fromTable,
      type,
      yLabel,
      title: [yLabel, fromTable.xLabel].filter(Boolean).join(" · "),
      series: fromTable.series.map((s) => ({ ...s, name: s.name || yLabel || t("sarp.chart_value") })),
    };
  }

  // Chart.js is loaded only when a chart is actually needed. If the CDN is unreachable the
  // chart line stays as readable text.
  let chartJsReady = null;
  function loadChartJs() {
    if (window.Chart) return Promise.resolve(window.Chart);
    if (!chartJsReady) {
      chartJsReady = new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = CHART_JS_URL;
        s.async = true;
        s.onload = () => (window.Chart ? resolve(window.Chart) : reject(new Error("chart")));
        s.onerror = () => { s.remove(); chartJsReady = null; reject(new Error("chart")); };
        document.head.appendChild(s);
      });
    }
    return chartJsReady;
  }

  const cssVar = (name, fallback) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  const seriesColors = () => SERIES_FALLBACK.map((c, i) => cssVar("--series-" + (i + 1), c));

  // Pies stop being readable past about six slices: keep five and fold the rest into "Other".
  function foldPie(spec) {
    if ((spec.type !== "pie" && spec.type !== "doughnut") || spec.labels.length <= 6) return spec;
    const data = spec.series[0].data;
    return {
      ...spec,
      labels: spec.labels.slice(0, 5).concat(t("sarp.other")),
      series: [{ ...spec.series[0], data: data.slice(0, 5).concat(data.slice(5).reduce((a, b) => a + b, 0)) }],
    };
  }

  // Mark specs: 2px lines with small markers; bars get rounded data ends and a 2px surface gap;
  // hover is per bar and per slice, and a crosshair on lines and areas.
  function chartConfig(spec, type, colors, surface) {
    const pie = type === "pie" || type === "doughnut";
    const bar = type === "bar";
    const muted = cssVar("--muted", "#5d6b60");
    const grid = cssVar("--line", "#dfe7dc");
    const color = (i) => colors[i % colors.length];
    const datasets = pie
      ? [{
          label: spec.series[0].name,
          data: spec.series[0].data,
          backgroundColor: spec.labels.map((_, i) => color(i)),
          borderColor: surface,
          borderWidth: 2,
        }]
      : spec.series.map((s, i) => bar
          ? {
              label: s.name,
              data: s.data,
              backgroundColor: color(i),
              borderColor: surface,
              borderWidth: 2,
              borderRadius: 4,
              borderSkipped: "bottom",   // rounds the data end (top), keeps the baseline square
            }
          : {
              label: s.name,
              data: s.data,
              borderColor: color(i),
              backgroundColor: type === "area" ? color(i) + "33" : color(i),
              fill: type === "area",
              tension: 0.3,
              borderWidth: 2,
              pointRadius: 4,
              pointHoverRadius: 7,
            });
    const axis = (title) => ({
      title: { display: !!title, text: title, color: muted },
      ticks: { color: muted },
      grid: { color: grid, lineWidth: 1 },
      border: { color: grid },
    });
    return {
      type: type === "area" ? "line" : type,
      data: { labels: spec.labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: pie || bar ? { mode: "nearest", intersect: true } : { mode: "index", intersect: false },
        plugins: {
          title: { display: !!spec.title, text: spec.title, color: muted },
          legend: { display: pie || spec.series.length > 1, labels: { color: muted } },
        },
        scales: pie ? {} : {
          x: axis(spec.xLabel),
          y: { ...axis(spec.yLabel), beginAtZero: bar || type === "area" },
        },
      },
    };
  }

  // Table twin of a chart: the same numbers without colour. Built with textContent because the
  // labels come from the model's answer.
  function chartTable(spec) {
    const details = document.createElement("details");
    details.className = "sarp-chart-data";
    const summary = document.createElement("summary");
    summary.textContent = t("sarp.table_toggle");
    const table = document.createElement("table");
    const headRow = table.createTHead().insertRow();
    [spec.xLabel || "", ...spec.series.map((s) => s.name)].forEach((text) => {
      const th = document.createElement("th");
      th.scope = "col";
      th.textContent = text;
      headRow.appendChild(th);
    });
    const body = table.createTBody();
    spec.labels.forEach((label, r) => {
      const row = body.insertRow();
      const th = document.createElement("th");
      th.scope = "row";
      th.textContent = label;
      row.appendChild(th);
      spec.series.forEach((s) => {
        row.insertCell().textContent = s.data[r] === undefined ? "" : Number(s.data[r]).toLocaleString(dateLocale());
      });
    });
    details.append(summary, table);
    return details;
  }

  // Redraws every chart still on the page (theme or OS colour-scheme change). Detached ones are dropped.
  function refreshSarpCharts() {
    for (const entry of liveSarpCharts) {
      if (entry.holder.isConnected) entry.redraw();
      else liveSarpCharts.delete(entry);
    }
  }
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", refreshSarpCharts);

  async function drawSarpChart(holder, rawSpec) {
    const spec = foldPie(rawSpec);
    let Chart;
    try { Chart = await loadChartJs(); }
    catch { holder.appendChild(chartTable(spec)); return; }   // no chart library: the numbers still show as a table
    if (!holder.isConnected) return;
    const pie = spec.type === "pie" || spec.type === "doughnut";
    const options = LINE_LIKE.map((v) => `<option value="${v}"${v === spec.type ? " selected" : ""}>${esc(t("sarp.type_" + v))}</option>`).join("");
    holder.innerHTML =
      `<div class="sarp-chart-tools">` +
      (pie ? "" : `<label>${esc(t("sarp.chart_type"))} <select>${options}</select></label>`) +
      `<button type="button" class="sarp-png" title="${esc(t("sarp.chart_png"))}">${esc(t("sarp.chart_png_label"))}</button></div>` +
      `<div class="sarp-chart-canvas"><canvas role="img" aria-label="${esc(spec.title || spec.type)}"></canvas></div>`;
    const canvas = holder.querySelector("canvas");
    let chart = null;
    let current = spec.type;
    const draw = (type) => {
      current = type;
      if (chart) chart.destroy();
      chart = new Chart(canvas, chartConfig(spec, type, seriesColors(), cssVar("--surface", "#ffffff")));
    };
    const select = holder.querySelector("select");
    if (select) select.addEventListener("change", () => draw(select.value));
    holder.querySelector(".sarp-png").addEventListener("click", () => {
      const a = document.createElement("a");
      a.href = canvas.toDataURL("image/png");
      a.download = (spec.title || "farmedia-chart").replace(/[^\p{L}\p{N}]+/gu, "-").slice(0, 60) + ".png";
      a.click();
    });
    holder.appendChild(chartTable(spec));
    liveSarpCharts.add({ holder, redraw: () => draw(current) });
    draw(spec.type);
  }

  // A ```chart block holding JSON: {"type","title","xLabel","yLabel","labels":[...],"series":[{"name","data":[...]}]}.
  // Anything malformed or inconsistent is not a chart, so it stays as text.
  function parseChartJson(text) {
    let data;
    try { data = JSON.parse(text); } catch { return null; }
    if (!data || !Array.isArray(data.labels) || data.labels.length < 2 || data.labels.length > 40) return null;
    const labels = data.labels.map((l) => String(l).slice(0, 40));
    const series = (Array.isArray(data.series) ? data.series : [])
      .filter((s) => s && Array.isArray(s.data) && s.data.length === labels.length &&
        s.data.every((v) => typeof v === "number" && Number.isFinite(v)))
      .slice(0, 4)
      .map((s) => ({ name: String(s.name || "").slice(0, 60), data: s.data }));
    if (!series.length) return null;
    const xLabel = String(data.xLabel || "").slice(0, 60);
    const yLabel = String(data.yLabel || "").slice(0, 60);
    const type = ["line", "bar", "area", "pie", "doughnut"].includes(data.type) ? data.type : "line";
    return {
      type,
      title: String(data.title || [yLabel, xLabel].filter(Boolean).join(" · ")).slice(0, 120),
      xLabel,
      yLabel,
      labels,
      series: series.map((s) => ({ ...s, name: s.name || yLabel || t("sarp.chart_value") })),
    };
  }

  // Splits a Sarp AI answer into HTML and chart specs. Chart lines and ```chart blocks that parse
  // become placeholders, which renderMarkdown turns into chart holders.
  function renderAnswer(src) {
    // Models often write no-break spaces (U+202F, U+00A0) inside "Hafta 1" or "12 mm". Plain spaces
    // keep labels comparable and the text tidy.
    const lines = String(src || "").replace(/[\u00a0\u202f\u2007\u2009]/g, " ").replace(/\r/g, "").split("\n");
    const charts = [];
    const out = [];
    for (let c = 0; c < lines.length; c++) {
      const trimmed = lines[c].trim();
      if (/^```\s*chart\s*$/i.test(trimmed)) {
        let end = c + 1;
        while (end < lines.length && lines[end].trim() !== "```") end++;
        const spec = end < lines.length ? parseChartJson(lines.slice(c + 1, end).join("\n")) : null;
        if (spec) {
          charts.push({ ...spec, raw: spec.title || t("sarp.chart_value") });
          out.push(`@@chart:${charts.length - 1}@@`);
          c = end;
          continue;
        }
      }
      if (CHART_LINE.test(trimmed)) {
        const spec = parseChartLine(trimmed, lines, c);
        if (spec) {
          charts.push({ ...spec, raw: trimmed });
          out.push(`@@chart:${charts.length - 1}@@`);
          continue;
        }
      }
      out.push(lines[c]);
    }
    return { html: renderMarkdown(out.join("\n"), charts), charts };
  }

  // Plain text and a small markdown subset (headings, bold, lists, tables). Escaped first, so model
  // output can never inject HTML.
  const mdInline = (s) => s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
  const isTableSep = (l) => /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$/.test(l);
  const splitRow = (l) => l.replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

  function renderMarkdown(src, charts = []) {
    const lines = esc(src).replace(/\r/g, "").split("\n").map((l) => l.trim());
    let html = "";
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!line) { i++; continue; }

      const ph = /^@@chart:(\d+)@@$/.exec(line);
      if (ph) {
        // Holder with the readable chart line as fallback; drawSarpChart replaces it when Chart.js loads.
        html += `<div class="sarp-chart" data-chart="${ph[1]}"><p class="chart-note">${esc(charts[+ph[1]].raw)}</p></div>`;
        i++;
        continue;
      }

      if (line.startsWith("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        const head = splitRow(line);
        const rows = [];
        i += 2;
        while (i < lines.length && lines[i].startsWith("|")) { rows.push(splitRow(lines[i])); i++; }
        html += `<div class="table-wrap"><table><thead><tr>${head.map((c) => `<th>${mdInline(c)}</th>`).join("")}</tr></thead><tbody>${
          rows.map((r) => `<tr>${r.map((c) => `<td>${mdInline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
        continue;
      }
      if (/^#{1,6}\s/.test(line)) { html += `<h4>${mdInline(line.replace(/^#{1,6}\s/, ""))}</h4>`; i++; continue; }
      if (/^[-*]\s/.test(line)) {
        const items = [];
        while (i < lines.length && /^[-*]\s/.test(lines[i])) { items.push(`<li>${mdInline(lines[i].slice(2))}</li>`); i++; }
        html += `<ul>${items.join("")}</ul>`;
        continue;
      }
      if (/^\d+\.\s/.test(line)) {
        const items = [];
        while (i < lines.length && /^\d+\.\s/.test(lines[i])) { items.push(`<li>${mdInline(lines[i].replace(/^\d+\.\s/, ""))}</li>`); i++; }
        html += `<ol>${items.join("")}</ol>`;
        continue;
      }
      if (CHART_LINE.test(line)) { html += `<p class="chart-note">${mdInline(line)}</p>`; i++; continue; }
      html += `<p>${mdInline(line)}</p>`;
      i++;
    }
    return html;
  }

  function sarpAppend(cls, html) {
    const div = document.createElement("div");
    div.className = "sarp-msg " + cls;
    div.innerHTML = html;
    sarpLog.appendChild(div);
    sarpLog.scrollTop = sarpLog.scrollHeight;
    return div;
  }

  // Map the server's error code to a friendly message in the current language.
  function sarpErrorKey(err) {
    if (err.status === 401) return "acc.session_expired";   // Sarp AI needs a signed-in user
    if (err.code === "not_configured") return "sarp.not_configured";
    if (err.code === "upstream_timeout" || err.code === "upstream_failure") return "sarp.unavailable";
    return "sarp.fail";
  }

  $("#sarp-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#sarp-input");
    const question = input.value.trim();
    if (!question || sarpBusy) return;
    const city = $("#sarp-city").value.trim();
    input.value = "";
    sarpAppend("user", `<p>${esc(question)}</p>`);
    const pending = sarpAppend("bot", `<span class="spinner"></span> ${esc(t("sarp.thinking"))}`);

    sarpBusy = true;
    $("#sarp-send").disabled = true;
    try {
      const r = await api("/api/sarp-ai.php", {
        headers: { "Content-Type": "application/json", ...authHeaders() },
        method: "POST",
        body: JSON.stringify({
          question,
          city: city || null,
          country_code: state.profile?.location?.coords?.country_code || null,
          lang: state.lang === "tr" ? "tr" : "en",
          farm_context: sarpFarmContext(),
        }),
      });
      const { html, charts } = renderAnswer(r.sarp_ai_answer);
      pending.innerHTML = html;
      charts.forEach((spec, i) => {
        const holder = pending.querySelector(`.sarp-chart[data-chart="${i}"]`);
        if (holder) drawSarpChart(holder, spec);
      });
    } catch (err) {
      pending.classList.add("err");
      pending.textContent = t(sarpErrorKey(err));
    } finally {
      sarpBusy = false;
      $("#sarp-send").disabled = false;
      sarpLog.scrollTop = sarpLog.scrollHeight;
    }
  });

  // ---------- 6. privacy: consent banner, legal modal, footer ----------
  // Stored choice shape: { v, at, ai_farm_share }. Bump PRIVACY_VERSION when the legal texts or
  // what gets shared change, so every visitor is asked again.
  const PRIVACY_VERSION = 1;
  const privacyChoice = () => (store.privacy && store.privacy.v === PRIVACY_VERSION ? store.privacy : null);
  function savePrivacy(aiFarmShare) {
    store.privacy = { v: PRIVACY_VERSION, at: new Date().toISOString(), ai_farm_share: !!aiFarmShare };
    saveStore(store);
    updateSarpShareNote();
  }

  // Farm details go to Sarp AI only with the user's explicit opt-in (KVKK: transfer abroad).
  function sarpFarmContext() {
    const p = state.profile;
    if (!p || !privacyChoice()?.ai_farm_share) return null;
    return {
      role: p.role === "farm" ? "farm" : "hobby",
      farm_size: p.role === "farm" && p.farmSize ? Number(p.farmSize) : null,
      crops_last: p.crops?.last || "",
      crops_current: p.crops?.current || "",
      crops_next: p.crops?.next || "",
    };
  }
  function updateSarpShareNote() {
    $("#sarp-share").textContent = t(privacyChoice()?.ai_farm_share ? "sarp.share_on" : "sarp.share_off");
  }

  const banner = $("#cb-banner");
  let bannerOpen = false;   // true when reopened from Settings, even after a choice was made
  // The banner waits for a language choice, so its text is never in a language the user did not pick.
  function syncBanner() {
    banner.hidden = !(state.lang && (bannerOpen || !privacyChoice()));
  }
  function openBanner() {
    bannerOpen = true;
    $("#cb-ai-share").checked = !!privacyChoice()?.ai_farm_share;
    syncBanner();
  }
  function closeBanner(aiFarmShare) {
    savePrivacy(aiFarmShare);
    bannerOpen = false;
    syncBanner();
  }
  $("#cb-save").addEventListener("click", () => closeBanner($("#cb-ai-share").checked));
  $("#cb-essential").addEventListener("click", () => closeBanner(false));
  $("#cb-reopen").addEventListener("click", () => openBanner());

  // Legal texts come from i18n; each paragraph is separated by a blank line in the source string.
  const LEGAL_DOCS = { kvkk: "legal.kvkk", privacy: "legal.privacy", cookies: "legal.cookies" };
  const legalModal = $("#legal-modal");
  function openLegal(doc) {
    const key = LEGAL_DOCS[doc];
    if (!key) return;
    $("#legal-title").textContent = t(key + ".title");
    $("#legal-body").innerHTML =
      t(key + ".body").split(/\n\n+/).map((p) => `<p>${esc(p)}</p>`).join("") +
      `<p class="legal-draft">${esc(t("legal.draft_note"))}</p>`;
    $("#legal-body").scrollTop = 0;
    if (!legalModal.open) legalModal.showModal();
  }
  $$("[data-legal]").forEach((b) => b.addEventListener("click", () => openLegal(b.dataset.legal)));
  $("#legal-close").addEventListener("click", () => legalModal.close());
  // A click on the backdrop lands on the dialog itself, because the inner box covers its content.
  legalModal.addEventListener("click", (e) => { if (e.target === legalModal) legalModal.close(); });

  // ---------- routing ----------
  function route() {
    applyUi();
    applyI18n();
    syncBanner();
    if (!state.lang) return showLanguage();
    if (acc.token && !syncedThisLoad) return finishSignIn();   // signed in on an earlier page load
    if (!acc.token && !state.profile && !store.authSkipped) return showAuth("signin");
    if (!state.profile) {
      showView("view-profile");
      fillForm(null);
      return;
    }
    loadDashboard();
  }

  route();
})();
