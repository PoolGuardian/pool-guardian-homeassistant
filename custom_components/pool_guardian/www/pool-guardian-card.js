/*
 * Pool Guardian — Lovelace card
 *
 * One card per controller, in place of the 35 entity rows the integration
 * otherwise produces. Read-only, like the integration itself.
 *
 * WHY A CARD AT ALL. A Pool Guardian controller publishes 25 sensors and 10
 * binary sensors. Auto-generated, that is a wall of rows in which "low sensor
 * link went offline" sits between "freeze resume threshold" and "IP address",
 * all in the same grey. The information is present and unreadable. This card
 * exists to answer, at a glance: where is the water, is the pump doing what it
 * should, and does anything need me.
 *
 * NO LIT. HA bundles Lit but does not export it on a stable path for custom
 * cards; the usual workaround reaches into another element's prototype and
 * breaks on frontend upgrades. A plain HTMLElement with a shadow root has no
 * such coupling, and this card re-renders a few dozen nodes every 10 s at
 * worst — which is nothing.
 *
 * THEMING. Every colour resolves from a Home Assistant CSS custom property
 * with a fallback, so a user's theme repaints the card instead of fighting it.
 * The fallbacks are HA's stock light-theme values, used only if a property is
 * genuinely absent.
 */

const CARD_VERSION = "1.1.1";

/* Entity suffixes, by domain.
 *
 * has_entity_name + translation_key means an entity_id is
 * <domain>.<device_slug>_<name_slug>, and the name slugs come from
 * translations/en.json. They are matched on DOMAIN + EXACT SUFFIX, never on
 * "contains": `_low_sensor_water` is a prefix of
 * `_low_sensor_water_temperature`, so a substring match silently binds the
 * temperature sensor to the water-detection slot and the card reports a probe
 * as wet because 22.9 is truthy.
 */
const WANTED = {
  binary_sensor: {
    pump: "_pump",
    lowWater: "_low_sensor_water",
    highWater: "_high_sensor_water",
    lowLink: "_low_sensor_link",
    highLink: "_high_sensor_link",
    freezeEnabled: "_freeze_protection_enabled",
    freezeActive: "_freeze_protection_active",
    freezeWarning: "_freeze_warning",
    freezeLockout: "_freeze_pump_lockout",
    cloud: "_cloud_link",
  },
  sensor: {
    state: "_state",
    mode: "_mode",
    current: "_pump_current",
    lowTemp: "_low_sensor_water_temperature",
    controllerTemp: "_controller_temperature",
    highTemp: "_high_sensor_water_temperature",
    lowFw: "_low_sensor_firmware",
    highFw: "_high_sensor_firmware",
    freezeThreshold: "_freeze_threshold",
    lastDuration: "_last_run_duration",
    lastReason: "_last_run_end_reason",
    lastCurrent: "_last_run_average_current",
    lastFinished: "_last_run_finished",
    rssi: "_wi_fi_signal",
    uptime: "_uptime",
    ip: "_ip_address",
    firmware: "_controller_firmware",
  },
};

const UNAVAILABLE = new Set(["unavailable", "unknown", "", null, undefined]);

const isOn = (s) => s && s.state === "on";
const has = (s) => s && !UNAVAILABLE.has(s.state);
const num = (s) => (has(s) ? Number(s.state) : null);

/* Seconds -> HH:MM:SS, matching the entity. Hours accumulate past 24 rather
 * than rolling over: a 26-hour run is a fault worth seeing as "26:14:03". */
function hms(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds)))
    return "—";
  const t = Math.max(0, Math.round(Number(seconds)));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = t % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

/* The duration entity is now a formatted string, so pass it through; fall back
 * to formatting a number for anyone still on an older integration. */
function durText(stateObj) {
  if (!has(stateObj)) return "—";
  const raw = stateObj.state;
  return /^\d+:\d{2}:\d{2}$/.test(raw) ? raw : hms(raw);
}

/* "drain_complete" -> "Drain complete". The controller's end reasons are
 * snake_case enum values; safety_abort in particular reads as an accusation
 * until it is spelled out. */
function reason(raw) {
  if (!raw) return "—";
  const special = {
    drain_complete: "Drain complete",
    safety_abort: "Stopped by safety check",
    overtime_autostop: "Stopped on overtime",
    manual_stop: "Stopped manually",
    manual_drain: "Manual drain",
    freeze_protect: "Freeze protection",
  };
  if (special[raw]) return special[raw];
  return String(raw).replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

function fmtTemp(s, hass) {
  const v = num(s);
  if (v === null) return "—";
  const unit = (s.attributes && s.attributes.unit_of_measurement) || "°C";
  return `${v.toFixed(1)}${unit.startsWith("°") ? unit : " " + unit}`;
}

class PoolGuardianCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._built = false;
    this._detailsOpen = false;
  }

  setConfig(config) {
    // DO NOT THROW when device_id is missing.
    //
    // Home Assistant calls setConfig() to build the tile in the "Add card"
    // picker, using getStubConfig() -- which cannot know the device yet. A
    // throw there does not surface as a friendly message: the picker tile
    // renders as a spinner that never resolves and cannot be clicked, so the
    // card is unselectable and the user has no way to reach the editor at all.
    // Observed on first install, 2026-09-06.
    //
    // Throwing is for config that is WRONG. "Not configured yet" is a state
    // the card renders, not an error it raises.
    if (config && config.device_id && typeof config.device_id !== "string") {
      throw new Error("Pool Guardian card: device_id must be a string.");
    }
    this._config = { show_diagnostics: true, ...(config || {}) };
    this._built = false;
  }

  static getConfigElement() {
    return document.createElement("pool-guardian-card-editor");
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return this._config && this._config.show_diagnostics ? 7 : 6;
  }

  static getStubConfig(hass, entities, entitiesFallback) {
    return { type: "custom:pool-guardian-card", device_id: "" };
  }

  /* Resolve every entity on this device once per render.
   *
   * hass.entities is the registry display map and carries device_id, so the
   * card never has to guess which controller an entity belongs to — which
   * matters the moment someone runs two units, where "Pool" and "Spa" differ
   * only by a slug that a rename can change.
   */
  _resolve() {
    const hass = this._hass;
    const wantDevice = this._config.device_id;
    const found = {};

    const registry = hass.entities || {};
    for (const [entityId, entry] of Object.entries(registry)) {
      if (!entry || entry.device_id !== wantDevice) continue;
      const dot = entityId.indexOf(".");
      const domain = entityId.slice(0, dot);
      const objectId = entityId.slice(dot + 1);
      const table = WANTED[domain];
      if (!table) continue;
      for (const [slot, suffix] of Object.entries(table)) {
        // endsWith, not includes — see the note on WANTED.
        if (objectId.endsWith(suffix) && !found[slot]) {
          found[slot] = hass.states[entityId];
        }
      }
    }
    return found;
  }

  _render() {
    if (!this._hass || !this._config) return;

    // The picker preview and a freshly-added card both land here with no
    // device chosen. Say what to do rather than rendering an empty shell.
    if (!this._config.device_id) {
      this.shadowRoot.innerHTML =
        `<style>${STYLES}</style>` +
        `<div class="ha-card"><div class="empty">
           <b>Choose a controller.</b> Pick your Pool Guardian device in the card
           editor, or set <code>device_id</code> in YAML.
         </div></div>`;
      return;
    }

    const e = this._resolve();

    if (!Object.keys(e).length) {
      this.shadowRoot.innerHTML =
        `<style>${STYLES}</style>` +
        `<div class="ha-card"><div class="empty">No Pool Guardian entities found for
         this device. Check that the controller is set up and that device_id is
         correct.</div></div>`;
      return;
    }

    const highWet = isOn(e.highWater);
    const lowWet = isOn(e.lowWater);
    const pumping = isOn(e.pump);
    const lockout = isOn(e.freezeLockout);
    const highOff = e.highLink && !isOn(e.highLink);
    const lowOff = e.lowLink && !isOn(e.lowLink);
    // Attention beats running beats idle. A unit that is pumping AND locked
    // out is a unit you need to look at, so severity wins the tie.
    // No alert count here on purpose: the controller removed active_alerts in
    // 1.0.398, so attention is derived from conditions the device still
    // reports -- a freeze lockout or a sensor that stopped talking.
    const attention = lockout || highOff || lowOff;
    const tone = attention ? "attn" : pumping ? "run" : "idle";
    const stateLabel = attention
      ? lockout
        ? "Locked out"
        : "Attention"
      : has(e.state)
        ? e.state.state
        : pumping
          ? "Pumping"
          : "Idle";

    /* Water line: the only three positions the hardware can distinguish.
     * Percentages are of vessel height, chosen so the line sits clearly
     * between the two probe marks (30% and 70%) rather than on one. */
    const waterPct = highWet ? 86 : lowWet ? 52 : 14;
    const waterLabel = highWet
      ? "Above high"
      : lowWet
        ? "High cleared"
        : "Below low";

    const name =
      this._config.name ||
      (this._hass.devices &&
        this._hass.devices[this._config.device_id] &&
        (this._hass.devices[this._config.device_id].name_by_user ||
          this._hass.devices[this._config.device_id].name)) ||
      "Pool Guardian";

    const sub = [
      has(e.mode) ? e.mode.state : null,
      has(e.firmware) ? e.firmware.state : null,
      has(e.uptime) ? "up " + hms(num(e.uptime)) : null,
    ]
      .filter(Boolean)
      .join(" · ");

    const freezeCell = lockout
      ? `<b class="crit">Lockout</b>`
      : isOn(e.freezeActive)
        ? `<b class="warn">Active</b>`
        : isOn(e.freezeWarning)
          ? `<b class="warn">Warning</b>`
          : isOn(e.freezeEnabled)
            ? `<b class="good">Ready</b>`
            : `<b class="dim">Off</b>`;

    const alertRows = [];
    if (lockout) {
      const t = has(e.freezeThreshold) ? ` at ${fmtTemp(e.freezeThreshold, this._hass)}` : "";
      alertRows.push(`Freeze lockout is holding the pump off${t}.`);
    }
    if (highOff) alertRows.push("High sensor stopped reporting.");
    if (lowOff) alertRows.push("Low sensor stopped reporting.");

    const pumpCell = lockout
      ? `<dd class="crit">Blocked</dd>`
      : pumping
        ? `<dd class="accent">Running</dd>`
        : `<dd class="dim">Off</dd>`;

    const currentVal = has(e.current) ? num(e.current).toFixed(2) : "0.00";

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <div class="ha-card">
        <div class="stripe ${tone}"></div>

        <div class="hdr">
          <div class="hdr-ic" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.7s6 6.4 6 10.4a6 6 0 0 1-12 0c0-4 6-10.4 6-10.4z"/></svg>
          </div>
          <div class="hdr-txt">
            <div class="hdr-name">${name}</div>
            <div class="hdr-sub">${sub || "&nbsp;"}</div>
          </div>
          <span class="pill ${tone}">${stateLabel}</span>
        </div>

        <div class="hero">
          <div class="vessel" role="img"
               aria-label="Water ${waterLabel.toLowerCase()}. High probe
               ${highWet ? "wet" : "dry"}, low probe ${lowWet ? "wet" : "dry"}.">
            <div class="water" style="height:${waterPct}%"></div>
            <div class="probe hi ${highWet ? "wet" : ""}"><span>HIGH</span></div>
            <div class="probe lo ${lowWet ? "wet" : ""}"><span>LOW</span></div>
          </div>
          <dl class="readouts">
            <div class="kv"><dt>Pump</dt>${pumpCell}</div>
            <div class="kv"><dt>Water</dt><dd>${waterLabel}</dd></div>
            <div class="kv"><dt>Current</dt>
              <dd class="${pumping ? "accent" : "dim"}">${currentVal}&nbsp;<small>A</small></dd></div>
            <div class="kv"><dt>Last run</dt>
              <dd>${durText(e.lastDuration)}
                <small>${reason(has(e.lastReason) ? e.lastReason.state : null)}</small></dd></div>
          </dl>
        </div>

        <div class="strip">
          <div class="stat"><b>${fmtTemp(e.highTemp, this._hass)}</b><span>High water</span></div>
          <div class="stat"><b>${fmtTemp(e.lowTemp, this._hass)}</b><span>Low water</span></div>
          <div class="stat"><b>${fmtTemp(e.controllerTemp, this._hass)}</b><span>Controller</span></div>
          <div class="stat">${freezeCell}<span>Freeze</span></div>
        </div>

        ${
          alertRows.length
            ? `<div class="alert">
                 <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2 1 21h22L12 2zm1 14h-2v2h2v-2zm0-7h-2v5h2V9z"/></svg>
                 <span>${alertRows.join(" ")}</span>
               </div>`
            : ""
        }

        ${
          this._config.show_diagnostics
            ? `<details ${this._detailsOpen || attention ? "open" : ""}>
                 <summary>Diagnostics</summary>
                 <dl class="diag">
                   ${this._diagRow("Wi-Fi", e.rssi, (s) => `${num(s)} dBm`)}
                   ${this._diagRow("Cloud", e.cloud, (s) =>
                     isOn(s) ? `<span class="good">Connected</span>` : `<span class="dim">Local only</span>`
                   )}
                   ${this._diagRow("Controller", e.firmware)}
                   ${this._diagRow("High sensor", e.highFw)}
                   ${this._diagRow("Low sensor", e.lowFw)}
                   ${this._diagRow("High link", e.highLink, (s) =>
                     isOn(s) ? `<span class="good">Online</span>` : `<span class="crit">Offline</span>`
                   )}
                   ${this._diagRow("Low link", e.lowLink, (s) =>
                     isOn(s) ? `<span class="good">Online</span>` : `<span class="crit">Offline</span>`
                   )}
                   ${this._diagRow("IP", e.ip)}
                 </dl>
               </details>`
            : ""
        }
      </div>
    `;

    const det = this.shadowRoot.querySelector("details");
    if (det) {
      // Remember the disclosure across re-renders. Without this, every poll
      // slams it shut under whoever is reading it.
      det.addEventListener("toggle", () => {
        this._detailsOpen = det.open;
      });
    }
  }

  _diagRow(label, stateObj, fmt) {
    if (!has(stateObj)) return `<div><dt>${label}</dt><dd class="dim">—</dd></div>`;
    const v = fmt ? fmt(stateObj) : stateObj.state;
    return `<div><dt>${label}</dt><dd>${v}</dd></div>`;
  }
}

const STYLES = `
  :host { display: block; }
  * { box-sizing: border-box; }

  .ha-card {
    background: var(--ha-card-background, var(--card-background-color, #fff));
    border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(16,24,40,.10), 0 1px 2px rgba(16,24,40,.06));
    border: var(--ha-card-border-width, 0) solid var(--ha-card-border-color, transparent);
    color: var(--primary-text-color, #212121);
    font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
    overflow: hidden;
  }

  .empty { padding: 16px; color: var(--secondary-text-color, #6b7280); font-size: .85rem; }

  .stripe { height: 3px; width: 100%; background: transparent; }
  .stripe.run  { background: var(--primary-color, #03a9f4); }
  .stripe.attn { background: var(--error-color, #e53935); }

  .hdr { display: flex; align-items: center; gap: 12px; padding: 14px 16px 12px; }
  .hdr-ic {
    width: 34px; height: 34px; flex: none; border-radius: 50%;
    display: grid; place-items: center;
    background: color-mix(in srgb, var(--primary-color, #03a9f4) 14%, transparent);
    color: var(--primary-color, #03a9f4);
  }
  .hdr-ic svg { width: 19px; height: 19px; display: block; }
  .hdr-txt { min-width: 0; flex: 1; }
  .hdr-name { font-size: 1rem; font-weight: 600; line-height: 1.25; }
  .hdr-sub {
    font-size: .74rem; color: var(--secondary-text-color, #6b7280);
    font-variant-numeric: tabular-nums;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }

  .pill {
    flex: none; font-size: .68rem; font-weight: 700; letter-spacing: .07em;
    text-transform: uppercase; padding: 5px 10px; border-radius: 999px;
    white-space: nowrap; display: inline-flex; align-items: center; gap: 6px;
  }
  .pill::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
  .pill.idle { color: var(--secondary-text-color, #6b7280);
               background: color-mix(in srgb, var(--secondary-text-color, #6b7280) 13%, transparent); }
  .pill.run  { color: var(--primary-color, #03a9f4);
               background: color-mix(in srgb, var(--primary-color, #03a9f4) 14%, transparent); }
  .pill.attn { color: var(--error-color, #e53935);
               background: color-mix(in srgb, var(--error-color, #e53935) 14%, transparent); }

  .hero { display: grid; grid-template-columns: 74px 1fr; gap: 16px; padding: 4px 16px 16px; }

  .vessel {
    position: relative; height: 132px; border-radius: 8px;
    background: color-mix(in srgb, var(--primary-text-color, #212121) 5%, transparent);
    border: 2px solid var(--divider-color, #e3e5e8);
    overflow: hidden;
  }
  .water {
    position: absolute; left: 0; right: 0; bottom: 0;
    background: linear-gradient(180deg,
      color-mix(in srgb, var(--primary-color, #03a9f4) 62%, transparent),
      color-mix(in srgb, var(--primary-color, #03a9f4) 34%, transparent));
    border-top: 2px solid var(--primary-color, #03a9f4);
    transition: height .6s cubic-bezier(.4,0,.2,1);
  }
  .probe { position: absolute; left: 0; right: 0; height: 0;
           border-top: 2px dashed var(--divider-color, #e3e5e8); }
  .probe span {
    position: absolute; right: 3px; top: -8px; font-size: .55rem; font-weight: 700;
    letter-spacing: .06em; color: var(--secondary-text-color, #6b7280);
    background: var(--ha-card-background, var(--card-background-color, #fff));
    padding: 0 3px; border-radius: 3px;
  }
  .probe.hi { top: 30%; }
  .probe.lo { top: 70%; }
  .probe.wet { border-top-color: var(--primary-color, #03a9f4); }
  .probe.wet span { color: var(--primary-color, #03a9f4); }

  .readouts { display: flex; flex-direction: column; gap: 11px; min-width: 0; margin: 0; }
  .kv { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
  .kv dt { font-size: .68rem; font-weight: 700; letter-spacing: .08em;
           text-transform: uppercase; color: var(--secondary-text-color, #6b7280); }
  .kv dd { margin: 0; font-size: .95rem; font-weight: 600;
           font-variant-numeric: tabular-nums; text-align: right; }
  .kv dd small { display: block; font-weight: 400; font-size: .7rem;
                 color: var(--secondary-text-color, #6b7280); }

  .accent { color: var(--primary-color, #03a9f4); }
  .good   { color: var(--success-color, #43a047); }
  .warn   { color: var(--warning-color, #f59e0b); }
  .crit   { color: var(--error-color, #e53935); }
  .dim    { color: var(--secondary-text-color, #6b7280); }

  .strip { display: grid; grid-template-columns: repeat(4, 1fr);
           border-top: 1px solid var(--divider-color, #e3e5e8); }
  .stat { padding: 11px 8px; text-align: center;
          border-right: 1px solid var(--divider-color, #e3e5e8); }
  .stat:last-child { border-right: 0; }
  .stat b { display: block; font-size: .95rem; font-weight: 600;
            font-variant-numeric: tabular-nums; }
  .stat span { display: block; font-size: .6rem; font-weight: 700; letter-spacing: .07em;
               text-transform: uppercase; color: var(--secondary-text-color, #6b7280);
               margin-top: 2px; }

  .alert {
    border-top: 1px solid var(--divider-color, #e3e5e8);
    padding: 10px 16px; font-size: .8rem; display: flex; align-items: flex-start; gap: 8px;
    color: var(--error-color, #e53935);
    background: color-mix(in srgb, var(--error-color, #e53935) 7%, transparent);
  }
  .alert svg { width: 15px; height: 15px; flex: none; margin-top: 2px; }

  details { border-top: 1px solid var(--divider-color, #e3e5e8); }
  summary {
    padding: 10px 16px; cursor: pointer; list-style: none;
    font-size: .7rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
    color: var(--secondary-text-color, #6b7280); display: flex; align-items: center; gap: 7px;
  }
  summary::-webkit-details-marker { display: none; }
  summary::before {
    content: ""; width: 0; height: 0; border-left: 4px solid currentColor;
    border-top: 3.5px solid transparent; border-bottom: 3.5px solid transparent;
    transition: transform .18s ease;
  }
  details[open] summary::before { transform: rotate(90deg); }
  summary:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: -2px; }

  .diag { padding: 0 16px 14px; margin: 0;
          display: grid; grid-template-columns: repeat(2, 1fr); gap: 7px 16px; }
  .diag div { display: flex; justify-content: space-between; gap: 8px; font-size: .76rem; }
  .diag dt { color: var(--secondary-text-color, #6b7280); }
  .diag dd { margin: 0; font-variant-numeric: tabular-nums; }

  @media (prefers-reduced-motion: reduce) {
    * { transition: none !important; }
  }
`;

/* Visual editor.
 *
 * One control, because the card has one required setting. ha-device-picker is
 * a frontend element HA already loads on the dashboard editor, filtered to
 * this integration so the list is the user's controllers and nothing else --
 * a bare device_id text field would mean telling people to dig an opaque hash
 * out of a URL.
 */
class PoolGuardianCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...(config || {}) };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _emit(config) {
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config },
        bubbles: true,
        composed: true,
      })
    );
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._picker) {
      this.innerHTML = "";

      const wrap = document.createElement("div");
      wrap.style.cssText = "display:flex;flex-direction:column;gap:12px;padding:8px 0";

      this._picker = document.createElement("ha-device-picker");
      this._picker.label = "Pool Guardian controller";
      this._picker.includeDomains = ["sensor", "binary_sensor"];
      // Restrict to this integration so the picker lists controllers only.
      this._picker.deviceFilter = (device) =>
        (device.identifiers || []).some((id) => id[0] === "pool_guardian");
      this._picker.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        this._config = { ...this._config, device_id: ev.detail.value };
        this._emit(this._config);
      });
      wrap.appendChild(this._picker);

      const diag = document.createElement("ha-formfield");
      diag.label = "Show diagnostics section";
      this._diag = document.createElement("ha-switch");
      this._diag.addEventListener("change", () => {
        this._config = { ...this._config, show_diagnostics: this._diag.checked };
        this._emit(this._config);
      });
      diag.appendChild(this._diag);
      wrap.appendChild(diag);

      this.appendChild(wrap);
    }

    this._picker.hass = this._hass;
    this._picker.value = this._config.device_id || "";
    this._diag.checked = this._config.show_diagnostics !== false;
  }
}

customElements.define("pool-guardian-card-editor", PoolGuardianCardEditor);
customElements.define("pool-guardian-card", PoolGuardianCard);

// Registers the card in the "Add card" picker.
window.customCards = window.customCards || [];
window.customCards.push({
  type: "pool-guardian-card",
  name: "Pool Guardian",
  description: "Water level, pump and health for one Pool Guardian controller.",
  preview: false,
  documentationURL: "https://github.com/PoolGuardian/pool-guardian-homeassistant",
});

console.info(
  `%c POOL-GUARDIAN-CARD %c ${CARD_VERSION} `,
  "color:#fff;background:#03a9f4;font-weight:700",
  "color:#03a9f4;background:transparent"
);
