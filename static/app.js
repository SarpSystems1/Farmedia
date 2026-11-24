/* Farmedia web UI: language gate -> profile onboarding -> weather dashboard.
 * Profile is stored in this browser's localStorage (per-viewer; no account system exists).
 */
(() => {
  "use strict";

  const STORE_KEY = "farmedia.v2";
  const S = window.FM_STRINGS;
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

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
    ["view-lang", "view-profile", "view-dash"].forEach((v) => ($("#" + v).hidden = v !== id));
    window.scrollTo(0, 0);
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
    let body = null;
    try { body = await res.json(); } catch { /* non-JSON */ }
    if (!res.ok) {
      const msg = body?.error?.message || (Array.isArray(body?.detail) ? body.detail[0]?.msg : body?.detail) || "";
      const err = new Error(msg || `HTTP ${res.status}`);
      err.status = res.status;
      err.code = body?.error?.code;
      throw err;
    }
    return body;
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
      const g = await api("/api/geocode?" + qs.toString());
      state.coords = { latitude: g.latitude, longitude: g.longitude, display_name: g.display_name, precision: g.precision };
      geoStatus.textContent = t("geo.found", {
        name: esc(g.display_name.split(",").slice(0, 2).join(",")),
        lat: g.latitude.toFixed(4),
        lon: g.longitude.toFixed(4),
        precision: t("prec." + g.precision),
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
      const r = await api("/api/parse-crops", {
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
        precision: t("prec." + (state.coords.precision || "city")),
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
    store.profile = state.profile;
    saveStore(store);
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
      const data = await api("/api/dashboard", { method: "POST", body: JSON.stringify(body) });
      state.lastDash = { data, profile: p };
      renderDashboard(data, p);
    } catch (err) {
      $("#dash-error").textContent = t("dash.load_fail") + (err.message ? ` (${err.message})` : "");
      $("#dash-error").hidden = false;
    } finally {
      $("#dash-loading").hidden = true;
    }
  }

  function renderHeader(p) {
    $("#hello").textContent = t("dash.hello", { name: p.firstName });
    const place = [p.location.district, p.location.city].filter(Boolean).join(", ");
    $("#loc-title").textContent = place || p.location.city;
    const parts = [p.location.state, p.location.country].filter(Boolean).join(", ");
    const c = p.location.coords;
    $("#loc-sub").textContent = `${parts} · ${c ? c.latitude.toFixed(3) + ", " + c.longitude.toFixed(3) : ""}`;
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
      tile("", t("tile.pressure"), num(cur.surface_pressure), u.surface_pressure || "hPa"),
    ].join("");

    const times = daily.time || [];
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

  $("#btn-refresh").addEventListener("click", () => loadDashboard());
  $("#btn-profile").addEventListener("click", () => {
    showView("view-profile");
    fillForm(state.profile);
  });
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

  // ---------- routing ----------
  function route() {
    applyI18n();
    if (!state.lang) return showLanguage();
    if (!state.profile) {
      showView("view-profile");
      fillForm(null);
      return;
    }
    loadDashboard();
  }

  route();
})();
