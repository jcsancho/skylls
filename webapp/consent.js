// Cookie consent for skylls.dev: a banner (Accept all / Only necessary / Customize) and a settings
// panel. The choice is kept in localStorage for 12 months. The only optional thing the site uses is
// Google Fonts ("functional"); it loads only after consent. There are no analytics or marketing cookies.
// Any element with data-cookie-settings reopens the settings, so consent can be changed at any time.
(() => {
  const KEY = "skylls-cookie-consent";
  const VERSION = "1.0";
  const MAX_AGE_MS = 365 * 24 * 3600 * 1000;
  const FONTS = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap";

  function stored() {
    try {
      const data = JSON.parse(localStorage.getItem(KEY));
      if (!data || data.version !== VERSION || Date.now() - Date.parse(data.timestamp) > MAX_AGE_MS) return null;
      return data.preferences;
    } catch {
      return null;
    }
  }

  function loadFonts() {
    if (document.getElementById("skylls-fonts")) return;
    for (const href of ["https://fonts.googleapis.com", "https://fonts.gstatic.com"]) {
      const link = Object.assign(document.createElement("link"), { rel: "preconnect", href });
      if (href.includes("gstatic")) link.crossOrigin = "";
      document.head.appendChild(link);
    }
    document.head.appendChild(Object.assign(document.createElement("link"), { id: "skylls-fonts", rel: "stylesheet", href: FONTS }));
  }

  function apply(prefs) {
    if (prefs.functional) loadFonts();
  }

  const initial = stored();
  if (initial) apply(initial);

  const CSS = `
    .ck-bar { position: fixed; left: 0; right: 0; bottom: 0; z-index: 200; background: #131316; border-top: 2px solid #8b5cf6;
      box-shadow: 0 -12px 40px rgba(0,0,0,.5); font-family: inherit; color: #e4e4e7; animation: ck-up .3s ease-out; }
    .ck-inner { max-width: 1000px; margin: 0 auto; padding: 22px 24px; display: flex; gap: 16px; align-items: flex-start; }
    .ck-icon { flex-shrink: 0; color: #a78bfa; margin-top: 2px; }
    .ck-body { flex: 1; min-width: 0; }
    .ck-title { font-size: 1.05rem; font-weight: 600; color: #fafafa; margin: 0 0 6px; }
    .ck-text { font-size: 0.88rem; line-height: 1.55; color: #a1a1aa; margin: 0 0 14px; }
    .ck-actions { display: flex; flex-wrap: wrap; gap: 10px; }
    .ck-btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 9px 20px; border-radius: 8px;
      font-family: inherit; font-size: 0.86rem; font-weight: 500; line-height: 1.2; cursor: pointer; border: 1px solid transparent; transition: background .15s, border-color .15s; }
    .ck-primary { background: #8b5cf6; color: #fff; }
    .ck-primary:hover { background: #7c3aed; }
    .ck-grey { background: #3f3f46; color: #fafafa; }
    .ck-grey:hover { background: #52525b; }
    .ck-outline { background: transparent; color: #d4d4d8; border-color: #3f3f46; }
    .ck-outline:hover { background: #1a1a1f; border-color: #52525b; }
    .ck-more { margin-top: 10px; font-size: 0.78rem; }
    .ck-more a, .ck-link { color: #a78bfa; text-decoration: underline; }
    .ck-close { flex-shrink: 0; background: none; border: 0; color: #71717a; cursor: pointer; padding: 2px; line-height: 0; }
    .ck-close:hover { color: #fafafa; }
    .ck-overlay { position: fixed; inset: 0; z-index: 200; background: rgba(0,0,0,.6); display: flex; align-items: center;
      justify-content: center; padding: 16px; font-family: inherit; color: #e4e4e7; }
    .ck-modal { background: #131316; border: 1px solid #27272a; border-radius: 16px; box-shadow: 0 24px 64px rgba(0,0,0,.6);
      max-width: 640px; width: 100%; max-height: 90vh; overflow-y: auto; padding: 26px; }
    .ck-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
    .ck-head h2 { display: flex; align-items: center; gap: 10px; margin: 0; font-size: 1.35rem; color: #fafafa; }
    .ck-cat { border: 1px solid #27272a; border-radius: 12px; padding: 14px 16px; margin-top: 12px; }
    .ck-cat-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 6px; }
    .ck-cat-head h3 { display: flex; align-items: center; gap: 10px; margin: 0; font-size: 0.95rem; color: #fafafa; }
    .ck-dot { width: 8px; height: 8px; border-radius: 50%; }
    .ck-cat p { margin: 0; font-size: 0.83rem; line-height: 1.55; color: #a1a1aa; }
    .ck-badge { padding: 3px 10px; border-radius: 999px; font-size: 0.72rem; font-weight: 500; white-space: nowrap; }
    .ck-on { background: rgba(16,185,129,.15); color: #34d399; }
    .ck-off { background: #27272a; color: #a1a1aa; }
    .ck-switch { position: relative; display: inline-block; width: 44px; height: 24px; flex-shrink: 0; cursor: pointer; }
    .ck-switch input { position: absolute; opacity: 0; width: 0; height: 0; }
    .ck-slider { position: absolute; inset: 0; background: #3f3f46; border-radius: 999px; transition: background .2s; }
    .ck-slider::after { content: ""; position: absolute; top: 2px; left: 2px; width: 20px; height: 20px; background: #fff;
      border-radius: 50%; transition: transform .2s; }
    .ck-switch input:checked + .ck-slider { background: #8b5cf6; }
    .ck-switch input:checked + .ck-slider::after { transform: translateX(20px); }
    .ck-switch input:focus-visible + .ck-slider { outline: 2px solid #a78bfa; outline-offset: 2px; }
    .ck-modal .ck-actions { margin-top: 22px; }
    .ck-modal .ck-btn { padding: 11px 20px; }
    .ck-center { text-align: center; margin-top: 14px; font-size: 0.83rem; }
    @keyframes ck-up { from { transform: translateY(100%); } to { transform: none; } }
    @media (max-width: 640px) { .ck-actions { flex-direction: column; } .ck-icon { display: none; } }
  `;

  const ICON_COOKIE = `<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2a10 10 0 1 0 10 10 4 4 0 0 1-5-5 4 4 0 0 1-5-5"/><circle cx="8.5" cy="8.5" r=".8" fill="currentColor"/><circle cx="16" cy="15.5" r=".8" fill="currentColor"/><circle cx="12" cy="17" r=".8" fill="currentColor"/><circle cx="7" cy="14" r=".8" fill="currentColor"/></svg>`;
  const ICON_SHIELD = `<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`;
  const ICON_CHECK = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>`;
  const ICON_GEAR = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>`;
  const ICON_X = (size) => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>`;

  let root = null;

  function el(html) {
    const t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstChild;
  }

  function close() {
    root?.remove();
    root = null;
  }

  function save(prefs) {
    prefs = { necessary: true, functional: !!prefs.functional, analytics: false, marketing: false };
    localStorage.setItem(KEY, JSON.stringify({ preferences: prefs, timestamp: new Date().toISOString(), version: VERSION }));
    close();
    apply(prefs);
  }

  const acceptAll = () => save({ functional: true });
  const acceptNecessary = () => save({ functional: false });

  function showBanner() {
    close();
    root = el(`
      <div class="ck-bar" role="region" aria-label="Cookie consent">
        <div class="ck-inner">
          <span class="ck-icon">${ICON_COOKIE}</span>
          <div class="ck-body">
            <h3 class="ck-title">We respect your privacy</h3>
            <p class="ck-text">skylls.dev only uses the cookies it needs to work, such as keeping you signed in to the dashboard.
              With your consent we also load fonts from Google Fonts, which shares your IP address with Google.
              No analytics, no advertising, no tracking.</p>
            <div class="ck-actions">
              <button type="button" class="ck-btn ck-primary" data-ck="all">${ICON_CHECK} Accept all</button>
              <button type="button" class="ck-btn ck-grey" data-ck="necessary">Only necessary</button>
              <button type="button" class="ck-btn ck-outline" data-ck="settings">${ICON_GEAR} Customize</button>
            </div>
            <div class="ck-more"><a href="/cookies">Learn more in our cookie policy</a></div>
          </div>
          <button type="button" class="ck-close" data-ck="close" aria-label="Close">${ICON_X(20)}</button>
        </div>
      </div>`);
    root.addEventListener("click", (e) => {
      const action = e.target.closest("[data-ck]")?.dataset.ck;
      if (action === "all") acceptAll();
      else if (action === "necessary") acceptNecessary();
      else if (action === "settings") showSettings();
      else if (action === "close") close();
    });
    document.body.appendChild(root);
  }

  function category(dot, title, description, control) {
    return `
      <div class="ck-cat">
        <div class="ck-cat-head">
          <h3><span class="ck-dot" style="background:${dot}"></span>${title}</h3>
          ${control}
        </div>
        <p>${description}</p>
      </div>`;
  }

  function showSettings() {
    close();
    const current = stored() || { functional: false };
    root = el(`
      <div class="ck-overlay">
        <div class="ck-modal" role="dialog" aria-modal="true" aria-labelledby="ck-settings-title">
          <div class="ck-head">
            <h2 id="ck-settings-title">${ICON_SHIELD} Cookie settings</h2>
            <button type="button" class="ck-close" data-ck="cancel" aria-label="Close">${ICON_X(24)}</button>
          </div>
          <p class="ck-text">Choose what skylls.dev may use. Necessary cookies are always on because the site can't work without
            them. You can change your choice at any time from "Cookie settings" at the bottom of every page.</p>
          ${category("#ef4444", "Necessary", "Keep you signed in to the dashboard (<code>skylls_session</code>, encrypted, up to 30 days), protect the GitHub sign-in (<code>skylls_oauth_state</code>, 10 minutes) and remember this choice (stored in your browser, 12 months).",
            `<span class="ck-badge ck-on">Always on</span>`)}
          ${category("#8b5cf6", "Functional", "Load the Inter and JetBrains Mono fonts from Google Fonts. Google receives your IP address and browser details. Without them the site uses your system fonts.",
            `<label class="ck-switch"><input type="checkbox" id="ck-functional" aria-label="Functional"${current.functional ? " checked" : ""}><span class="ck-slider"></span></label>`)}
          ${category("#22d3ee", "Analytics", "skylls.dev does not measure visits or use analytics cookies.", `<span class="ck-badge ck-off">Not used</span>`)}
          ${category("#10b981", "Marketing", "skylls.dev shows no ads and uses no advertising or tracking cookies.", `<span class="ck-badge ck-off">Not used</span>`)}
          <div class="ck-actions">
            <button type="button" class="ck-btn ck-primary" data-ck="save">${ICON_CHECK} Save preferences</button>
            <button type="button" class="ck-btn ck-grey" data-ck="all">Accept all</button>
            <button type="button" class="ck-btn ck-outline" data-ck="cancel">Cancel</button>
          </div>
          <div class="ck-center"><a class="ck-link" href="/cookies">Read the cookie policy</a></div>
        </div>
      </div>`);
    root.addEventListener("click", (e) => {
      if (e.target === root) return cancel();
      const action = e.target.closest("[data-ck]")?.dataset.ck;
      if (action === "save") save({ functional: root.querySelector("#ck-functional").checked });
      else if (action === "all") acceptAll();
      else if (action === "cancel") cancel();
    });
    root.addEventListener("keydown", (e) => { if (e.key === "Escape") cancel(); });
    document.body.appendChild(root);
    root.querySelector("#ck-functional").focus();
  }

  // Cancel goes back to the banner while no choice has been made yet.
  function cancel() {
    if (stored()) close();
    else showBanner();
  }

  function init() {
    document.head.appendChild(Object.assign(document.createElement("style"), { textContent: CSS }));
    document.addEventListener("click", (e) => {
      if (!e.target.closest("[data-cookie-settings]")) return;
      e.preventDefault();
      showSettings();
    });
    if (!stored()) setTimeout(() => { if (!root && !stored()) showBanner(); }, 1000);
  }

  window.skyllsCookieSettings = showSettings;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
