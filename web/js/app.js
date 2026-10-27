// Application State
const state = {
  currentTrack: null,
  isDownloading: false,
  downloadPollInterval: null,
  activePreview: null,          // { id, btn }
  devicePollingInterval: null,
  accentColor: '#FFCC00',
  theme: 'dark',
  selectedSource: 'all',
  ymSearchBusy: false,
  trackLoadBusy: false,
  alt: {
    busy: false,
    controller: null,
    results: [],
    shown: 0,
    ref: null                   // { query, duration, track } when launched from a Yandex track
  }
};

const ALT_PAGE_SIZE = 15;
const ALT_PAGE_STEP = 10;

// Shared inline icons (thin outline style, same as the nav bar)
const ICONS = {
  play: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><polygon points="6 4 19 12 6 20 6 4"></polygon></svg>',
  pause: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="9" y1="5" x2="9" y2="19"></line><line x1="15" y1="5" x2="15" y2="19"></line></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>',
  folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>'
};

// DOM Cache
const $ = (id) => document.getElementById(id);
const dom = {
  splash: $('splash-screen'),
  navItems: document.querySelectorAll('.nav-item'),
  screens: document.querySelectorAll('.screen-tab'),
  btnThemeToggle: $('btn-theme-toggle'),
  btnQuickToken: $('btn-quick-token'),
  headerStatus: $('header-user-status'),
  headerStatusText: $('header-status-text'),
  headerPlusIcon: $('header-plus-icon'),

  // Downloader
  trackUrlInput: $('track-url-input'),
  btnPasteClipboard: $('btn-paste-clipboard'),
  btnFetchTrack: $('btn-fetch-track'),
  ymResults: $('ym-search-results'),
  trackHeroCard: $('track-hero-card'),
  trackCoverImg: $('track-cover-img'),
  trackTitle: $('track-title'),
  trackArtist: $('track-artist'),
  trackDuration: $('track-duration'),
  trackAlbum: $('track-album'),
  badgeExplicit: $('badge-explicit'),
  btnDownloadYm: $('btn-download-ym'),
  btnFindUncensored: $('btn-find-uncensored'),
  progressContainer: $('progress-container'),
  progressFill: $('progress-fill'),
  progressPercent: $('progress-percent'),
  progressStage: $('progress-stage-text'),
  progressBytes: $('progress-bytes'),
  progressSpeed: $('progress-speed'),
  resultSuccessCard: $('result-success-card'),
  successFilename: $('success-filename'),
  btnOpenFolderAction: $('btn-open-folder-action'),

  // Uncensored
  altSearchInput: $('alt-search-input'),
  btnTriggerAltSearch: $('btn-trigger-alt-search'),
  altResultsList: $('alt-results-list'),
  altSearchContext: $('alt-search-context'),
  altSourceStatus: $('alt-source-status'),
  sourceFilterPills: $('source-filter-pills'),
  sourcePills: document.querySelectorAll('.source-pill'),
  audioPlayer: $('global-preview-player'),

  // History
  historyList: $('history-items-list'),
  btnRefreshHistory: $('btn-refresh-history'),
  historyFolderLabel: $('history-folder-label'),

  // Settings
  accentPaletteScroll: $('accent-palette-scroll'),
  btnRainbowPicker: $('btn-rainbow-picker'),
  customColorPicker: $('custom-color-picker'),
  settingsAccountName: $('settings-account-name'),
  settingsAccountSub: $('settings-account-sub'),
  settingsStoragePath: $('settings-storage-path'),
  btnOpenDeviceAuth: $('btn-open-device-auth'),
  btnOpenManualAuth: $('btn-open-manual-auth'),
  btnOpenStorageFolder: $('btn-open-storage-folder'),
  spotifyClientId: $('spotify-client-id'),
  spotifyClientSecret: $('spotify-client-secret'),
  spotifyStatus: $('spotify-status'),
  btnSaveSpotify: $('btn-save-spotify'),

  // Modals
  modalDevice: $('modal-device-auth'),
  modalManual: $('modal-manual-auth'),
  deviceCodeVal: $('device-code-val'),
  btnCopyDeviceCode: $('btn-copy-device-code'),
  devicePollStatus: $('device-poll-status'),
  manualTokenInput: $('manual-token-input'),
  btnSubmitManualToken: $('btn-submit-manual-token'),
  btnAuthLogout: $('btn-auth-logout'),
  toastContainer: $('toast-container')
};

// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
  restoreCachedSession();
  initNavigation();
  initAccentPalette();
  initThemeToggle();
  initDownloaderEvents();
  initUncensoredEvents();
  initSettingsEvents();
  initModals();
  initSplashScreen(loadInitialStatus());
});

/* ================= HELPERS ================= */
async function postJson(url, body, signal) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
    signal
  });
  let data = {};
  try { data = await res.json(); } catch (e) {}
  if (!res.ok || data.error) throw new Error(data.error || `Ошибка сервера (${res.status})`);
  return data;
}

function setButtonLoading(btn, loading) {
  if (!btn) return;
  btn.classList.toggle('is-loading', loading);
  btn.disabled = loading;
  btn.setAttribute('aria-busy', loading ? 'true' : 'false');
}

function isYandexLink(text) {
  return /music\.yandex\.|^\d+$/i.test(text.trim());
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

function setHeaderStatus(text, color, showPlus) {
  dom.headerStatusText.textContent = text;
  dom.headerStatus.style.color = color;
  dom.headerPlusIcon.classList.toggle('hidden', !showPlus);
}

/* ================= 0. CACHED SESSION RESTORE ================= */
function restoreCachedSession() {
  try {
    const savedTheme = localStorage.getItem('yasave_theme');
    if (savedTheme) {
      document.documentElement.dataset.theme = savedTheme;
      state.theme = savedTheme;
    }
    const savedAccent = localStorage.getItem('yasave_accent');
    if (savedAccent) applyAccentColor(savedAccent);

    const savedUser = localStorage.getItem('yasave_user');
    const hasPlus = localStorage.getItem('yasave_has_plus') === '1';
    if (savedUser) {
      setHeaderStatus(hasPlus ? 'Плюс активен' : 'Авторизован', 'var(--accent)', hasPlus);
      dom.settingsAccountName.textContent = savedUser;
      dom.settingsAccountSub.textContent = hasPlus ? 'Подписка Яндекс Плюс активна' : 'Без подписки';
      if (dom.btnAuthLogout) dom.btnAuthLogout.classList.remove('hidden');
    }
  } catch (e) {
    console.error('Failed to restore cached session:', e);
  }
}

/* ================= 1. SPLASH SCREEN ================= */
// One splash only. It leaves as soon as the initial status is loaded
// (but stays at least briefly so it does not flicker), max 2.2s.
function initSplashScreen(readyPromise) {
  const started = performance.now();
  const MIN_VISIBLE = 450;
  const MAX_VISIBLE = 2200;
  let dismissed = false;

  const dismiss = () => {
    if (dismissed) return;
    dismissed = true;
    document.body.classList.add('app-ready');
    if (dom.splash) {
      dom.splash.classList.add('is-leaving');
      dom.splash.addEventListener('transitionend', () => dom.splash.remove(), { once: true });
      setTimeout(() => dom.splash && dom.splash.remove(), 600);
    }
  };

  const whenReady = () => {
    const wait = Math.max(0, MIN_VISIBLE - (performance.now() - started));
    setTimeout(dismiss, wait);
  };

  Promise.resolve(readyPromise).finally(whenReady);
  setTimeout(dismiss, MAX_VISIBLE);
  if (dom.splash) dom.splash.addEventListener('click', dismiss);
}

/* ================= 2. NAVIGATION & TABS ================= */
function initNavigation() {
  dom.navItems.forEach((btn) => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });
}

function switchTab(tabId) {
  dom.navItems.forEach(item => item.classList.toggle('active', item.dataset.tab === tabId));
  dom.screens.forEach(screen => screen.classList.toggle('active', screen.id === tabId));
  window.scrollTo(0, 0);
  if (tabId === 'tab-history') loadHistory();
}

/* ================= 3. ACCENT PALETTE & THEMES ================= */
function initAccentPalette() {
  document.querySelectorAll('.palette-swatch:not(.rainbow-swatch)').forEach(swatch => {
    swatch.addEventListener('click', () => {
      applyAccentColor(swatch.dataset.color);
      saveAccentColor(swatch.dataset.color);
    });
  });

  if (dom.btnRainbowPicker && dom.customColorPicker) {
    dom.btnRainbowPicker.addEventListener('click', (e) => {
      e.stopPropagation();
      dom.customColorPicker.click();
    });
    const handleCustomColor = (e) => {
      const color = e.target.value.toUpperCase();
      applyAccentColor(color);
      saveAccentColor(color);
    };
    dom.customColorPicker.addEventListener('input', handleCustomColor);
    dom.customColorPicker.addEventListener('change', handleCustomColor);
  }

  enableDragScroll(dom.accentPaletteScroll);
}

// Mouse-drag and wheel horizontal scroll for desktop
function enableDragScroll(container) {
  if (!container) return;
  let isDown = false, startX = 0, scrollLeft = 0, hasDragged = false;

  container.addEventListener('mousedown', (e) => {
    isDown = true;
    hasDragged = false;
    startX = e.pageX;
    scrollLeft = container.scrollLeft;
    container.classList.add('is-dragging');
  });
  const stopDrag = () => {
    if (isDown) {
      isDown = false;
      container.classList.remove('is-dragging');
    }
  };
  window.addEventListener('mouseup', stopDrag);
  window.addEventListener('blur', stopDrag);
  container.addEventListener('mousemove', (e) => {
    if (!isDown) return;
    const walk = e.pageX - startX;
    if (Math.abs(walk) > 3) hasDragged = true;
    container.scrollLeft = scrollLeft - walk;
  });
  container.addEventListener('click', (e) => {
    if (hasDragged) {
      e.preventDefault();
      e.stopPropagation();
      hasDragged = false;
    }
  }, true);
  container.addEventListener('wheel', (e) => {
    if (e.deltaY !== 0 && container.scrollWidth > container.clientWidth) {
      e.preventDefault();
      container.scrollLeft += e.deltaY;
    }
  }, { passive: false });

  // Edge fades only where there is more content to scroll
  const updateEdges = () => {
    const max = container.scrollWidth - container.clientWidth;
    container.classList.toggle('fade-left', container.scrollLeft > 4);
    container.classList.toggle('fade-right', container.scrollLeft < max - 4);
  };
  container.addEventListener('scroll', updateEdges, { passive: true });
  // Also fires when a hidden tab becomes visible (size goes from 0 to real)
  if (window.ResizeObserver) new ResizeObserver(updateEdges).observe(container);
  else window.addEventListener('resize', updateEdges);
  requestAnimationFrame(updateEdges);
}

function saveAccentColor(hexColor) {
  try { localStorage.setItem('yasave_accent', hexColor); } catch (e) {}
  postJson('/api/settings', { accent_color: hexColor }).catch(console.error);
}

function applyAccentColor(hexColor) {
  if (!hexColor) return;
  state.accentColor = hexColor;

  let r = 0, g = 0, b = 0;
  const hex = hexColor.replace('#', '');
  if (hex.length === 3) {
    r = parseInt(hex[0] + hex[0], 16);
    g = parseInt(hex[1] + hex[1], 16);
    b = parseInt(hex[2] + hex[2], 16);
  } else if (hex.length === 6) {
    r = parseInt(hex.substring(0, 2), 16);
    g = parseInt(hex.substring(2, 4), 16);
    b = parseInt(hex.substring(4, 6), 16);
  }
  const lum = 0.299 * r + 0.587 * g + 0.114 * b;
  const contrastText = lum > 145 ? '#070a14' : '#ffffff';

  const { h, s, l } = hexToHSL(hexColor);
  const isMonochrome = (s < 35 && l > 70) || s < 18 || l < 10 || l > 93;
  let gradientStr, glowStr, subtleStr;

  if (isMonochrome) {
    if (l > 75) {
      gradientStr = 'linear-gradient(135deg, #ffffff 0%, #cbd5e1 100%)';
      glowStr = 'rgba(255, 255, 255, 0.40)';
      subtleStr = 'rgba(255, 255, 255, 0.14)';
    } else if (l < 25) {
      gradientStr = 'linear-gradient(135deg, #1e293b 0%, #475569 100%)';
      glowStr = 'rgba(255, 255, 255, 0.22)';
      subtleStr = 'rgba(255, 255, 255, 0.10)';
    } else {
      gradientStr = `linear-gradient(135deg, ${hexColor} 0%, #475569 100%)`;
      glowStr = `rgba(${r}, ${g}, ${b}, 0.35)`;
      subtleStr = `rgba(${r}, ${g}, ${b}, 0.14)`;
    }
  } else {
    const h2 = (h - 16 + 360) % 360;
    const s2 = Math.max(s - 8, 20);
    const l2 = Math.max(l - 6, 18);
    gradientStr = `linear-gradient(135deg, hsl(${h}, ${s}%, ${l}%), hsl(${h2}, ${s2}%, ${l2}%))`;
    glowStr = `hsla(${h}, ${s}%, ${l}%, 0.40)`;
    subtleStr = `hsla(${h}, ${s}%, ${l}%, 0.15)`;
  }

  const root = document.documentElement;
  root.style.setProperty('--accent-h', h);
  root.style.setProperty('--accent-s', `${s}%`);
  root.style.setProperty('--accent-l', `${l}%`);
  root.style.setProperty('--accent', hexColor);
  root.style.setProperty('--accent-contrast', contrastText);
  root.style.setProperty('--accent-gradient', gradientStr);
  root.style.setProperty('--accent-glow', glowStr);
  root.style.setProperty('--accent-subtle', subtleStr);

  let matchedPreset = false;
  document.querySelectorAll('.palette-swatch:not(.rainbow-swatch)').forEach(el => {
    const isMatch = el.dataset.color && el.dataset.color.toLowerCase() === hexColor.toLowerCase();
    el.classList.toggle('active', isMatch);
    if (isMatch) matchedPreset = true;
  });
  if (dom.btnRainbowPicker) dom.btnRainbowPicker.classList.toggle('active', !matchedPreset);
  if (dom.customColorPicker) dom.customColorPicker.value = hexColor;
}

function hexToHSL(hex) {
  let r = 0, g = 0, b = 0;
  if (hex.length === 4) {
    r = '0x' + hex[1] + hex[1]; g = '0x' + hex[2] + hex[2]; b = '0x' + hex[3] + hex[3];
  } else if (hex.length === 7) {
    r = '0x' + hex[1] + hex[2]; g = '0x' + hex[3] + hex[4]; b = '0x' + hex[5] + hex[6];
  }
  r /= 255; g /= 255; b /= 255;
  const cmin = Math.min(r, g, b), cmax = Math.max(r, g, b), delta = cmax - cmin;
  let h = 0;
  if (delta === 0) h = 0;
  else if (cmax === r) h = ((g - b) / delta) % 6;
  else if (cmax === g) h = (b - r) / delta + 2;
  else h = (r - g) / delta + 4;
  h = Math.round(h * 60);
  if (h < 0) h += 360;
  let l = (cmax + cmin) / 2;
  let s = delta === 0 ? 0 : delta / (1 - Math.abs(2 * l - 1));
  s = +(s * 100).toFixed(1);
  l = +(l * 100).toFixed(1);
  return { h, s, l };
}

function initThemeToggle() {
  dom.btnThemeToggle.addEventListener('click', () => {
    const nextTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = nextTheme;
    state.theme = nextTheme;
    try { localStorage.setItem('yasave_theme', nextTheme); } catch (e) {}
    postJson('/api/settings', { theme: nextTheme }).catch(console.error);
    showToast(`Включена ${nextTheme === 'dark' ? 'тёмная' : 'светлая'} тема`);
  });
}

/* ================= 4. INITIAL STATUS ================= */
async function loadInitialStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();

    if (data.accent_color) {
      applyAccentColor(data.accent_color);
      try { localStorage.setItem('yasave_accent', data.accent_color); } catch (e) {}
    }
    if (data.theme) {
      document.documentElement.dataset.theme = data.theme;
      state.theme = data.theme;
      try { localStorage.setItem('yasave_theme', data.theme); } catch (e) {}
    }

    if (data.is_valid && data.user_name) {
      const cleanName = data.user_name.replace(/\s*\((?:Плюс активен|Без подписки)[^)]*\)/i, '').trim();
      const displayName = cleanName || data.user_name;
      setHeaderStatus(data.has_plus ? 'Плюс активен' : 'Авторизован', 'var(--accent)', data.has_plus);
      dom.settingsAccountName.textContent = displayName;
      dom.settingsAccountSub.textContent = data.has_plus ? 'Подписка Яндекс Плюс активна' : 'Без подписки';
      if (dom.btnAuthLogout) dom.btnAuthLogout.classList.remove('hidden');
      try {
        localStorage.setItem('yasave_user', displayName);
        localStorage.setItem('yasave_has_plus', data.has_plus ? '1' : '0');
      } catch (e) {}
    } else {
      setHeaderStatus('Требуется вход', 'var(--danger)', false);
      dom.settingsAccountName.textContent = 'Не авторизован';
      dom.settingsAccountSub.textContent = 'Войдите, чтобы скачивать в 320 kbps';
      if (dom.btnAuthLogout) dom.btnAuthLogout.classList.add('hidden');
      try {
        localStorage.removeItem('yasave_user');
        localStorage.removeItem('yasave_has_plus');
      } catch (e) {}
    }

    if (data.download_dir) {
      dom.settingsStoragePath.textContent = data.download_dir;
      dom.settingsStoragePath.title = data.download_dir;
      dom.historyFolderLabel.textContent = `Загрузки сохранены в: ${data.download_dir}`;
    }

    if (data.spotify_client_id && dom.spotifyClientId) dom.spotifyClientId.value = data.spotify_client_id;
    setSpotifyStatus(data.spotify_configured ? 'ok' : 'none');
  } catch (err) {
    console.error('Failed to load initial status:', err);
  }
}

/* ================= 5. DOWNLOADER (link or text search) ================= */
function initDownloaderEvents() {
  dom.btnPasteClipboard.addEventListener('click', async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        dom.trackUrlInput.value = text.trim();
        handleDownloadInput();
      }
    } catch {
      showToast('Вставьте ссылку вручную', 'info');
    }
  });

  dom.btnFetchTrack.addEventListener('click', handleDownloadInput);
  dom.trackUrlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') handleDownloadInput();
  });

  dom.btnDownloadYm.addEventListener('click', startYmDownload);

  dom.btnFindUncensored.addEventListener('click', () => {
    const t = state.currentTrack;
    if (!t) return;
    const query = `${t.artist} ${t.title}`;
    dom.altSearchInput.value = query;
    state.alt.ref = { query, duration: t.duration || 0, track: t };
    switchTab('tab-uncensored');
    triggerAltSearch();
  });

  dom.btnOpenFolderAction.addEventListener('click', openDownloadFolder);
  dom.btnOpenStorageFolder.addEventListener('click', openDownloadFolder);
}

function handleDownloadInput() {
  const text = dom.trackUrlInput.value.trim();
  if (!text) {
    showToast('Введите ссылку или название трека', 'error');
    return;
  }
  if (isYandexLink(text)) {
    dom.ymResults.classList.add('hidden');
    loadTrack(text);
  } else {
    searchYandex(text);
  }
}

async function searchYandex(query) {
  if (state.ymSearchBusy) return;
  state.ymSearchBusy = true;
  setButtonLoading(dom.btnFetchTrack, true);
  dom.ymResults.classList.remove('hidden');
  dom.ymResults.innerHTML = `<div class="ym-results-empty"><span class="spinner"></span>Ищем в Яндекс Музыке...</div>`;

  try {
    const data = await postJson('/api/ym_search', { query });
    renderYmResults(data.tracks || []);
  } catch (err) {
    dom.ymResults.innerHTML = `<div class="ym-results-empty is-error">${escapeHtml(err.message)}</div>`;
  } finally {
    state.ymSearchBusy = false;
    setButtonLoading(dom.btnFetchTrack, false);
  }
}

function renderYmResults(tracks) {
  if (!tracks.length) {
    dom.ymResults.innerHTML = `<div class="ym-results-empty">Ничего не найдено. Попробуйте другой запрос.</div>`;
    return;
  }
  dom.ymResults.innerHTML = `
    <div class="ym-results-head">
      <span>Найдено в Яндекс Музыке</span>
      <button type="button" class="ym-results-close" aria-label="Скрыть">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
      </button>
    </div>
    <div class="ym-results-list"></div>`;
  dom.ymResults.querySelector('.ym-results-close').addEventListener('click', () => dom.ymResults.classList.add('hidden'));

  const list = dom.ymResults.querySelector('.ym-results-list');
  tracks.forEach((t, i) => {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'ym-row appear';
    row.style.setProperty('--i', Math.min(i, 12));
    row.innerHTML = `
      <img class="ym-row-cover" src="${escapeHtml(t.thumb_url || 'assets/cover.jpg')}" alt="" loading="lazy">
      <span class="ym-row-text">
        <span class="ym-row-title">${escapeHtml(t.title)}</span>
        <span class="ym-row-artist">${escapeHtml(t.artist)}</span>
      </span>
      ${t.explicit ? '<span class="badge badge-explicit">E</span>' : ''}
      <span class="ym-row-dur">${escapeHtml(t.duration_str)}</span>`;
    row.addEventListener('click', async () => {
      list.querySelectorAll('.ym-row').forEach(r => r.classList.remove('selected'));
      row.classList.add('selected');
      const ok = await loadTrack(t.id);
      if (ok) dom.ymResults.classList.add('hidden');
    });
    list.appendChild(row);
  });
}

async function loadTrack(urlOrId) {
  if (state.trackLoadBusy) return false;
  state.trackLoadBusy = true;
  setButtonLoading(dom.btnFetchTrack, true);
  dom.trackHeroCard.classList.add('is-loading');

  try {
    const data = await postJson('/api/track_info', { url: String(urlOrId) });
    const t = data.track;
    state.currentTrack = t;

    dom.trackHeroCard.classList.remove('empty-state');
    dom.trackTitle.textContent = t.title;
    dom.trackArtist.textContent = t.artist;
    dom.trackDuration.textContent = t.duration_str;
    dom.trackAlbum.textContent = t.album || (t.year ? `Релиз ${t.year}` : 'Сингл');
    if (t.cover_url) dom.trackCoverImg.src = t.cover_url;
    dom.badgeExplicit.classList.toggle('hidden', !t.explicit);

    dom.btnDownloadYm.disabled = false;
    dom.btnFindUncensored.disabled = false;
    dom.resultSuccessCard.classList.add('hidden');

    dom.trackHeroCard.classList.remove('pop');
    void dom.trackHeroCard.offsetWidth;
    dom.trackHeroCard.classList.add('pop');
    return true;
  } catch (err) {
    showToast(err.message, 'error');
    return false;
  } finally {
    state.trackLoadBusy = false;
    setButtonLoading(dom.btnFetchTrack, false);
    dom.trackHeroCard.classList.remove('is-loading');
  }
}

async function startYmDownload() {
  if (!state.currentTrack || state.isDownloading) return;
  beginDownloadUi('Запуск загрузки...');
  try {
    await postJson('/api/download_ym', { track_info: state.currentTrack });
    startDownloadPolling();
  } catch (err) {
    endDownloadUi(false);
    showToast(err.message, 'error');
  }
}

function beginDownloadUi(text) {
  state.isDownloading = true;
  dom.btnDownloadYm.disabled = true;
  dom.btnFindUncensored.disabled = true;
  dom.progressContainer.classList.remove('hidden');
  dom.resultSuccessCard.classList.add('hidden');
  updateProgress(0, 0, 0, text, '');
}

function endDownloadUi(keepProgress) {
  state.isDownloading = false;
  dom.btnDownloadYm.disabled = !state.currentTrack;
  dom.btnFindUncensored.disabled = !state.currentTrack;
  if (!keepProgress) dom.progressContainer.classList.add('hidden');
}

function startDownloadPolling() {
  if (state.downloadPollInterval) clearInterval(state.downloadPollInterval);

  state.downloadPollInterval = setInterval(async () => {
    try {
      const res = await fetch('/api/download_progress');
      const p = await res.json();
      updateProgress(p.percent, p.downloaded_mb, p.total_mb, p.status, p.speed);

      if (p.complete) {
        clearInterval(state.downloadPollInterval);
        endDownloadUi(true);
        const filename = p.filepath ? p.filepath.split(/[\\/]/).pop() : 'Трек сохранён';
        dom.successFilename.textContent = filename;
        dom.resultSuccessCard.classList.remove('hidden');
        showToast('Скачивание завершено', 'success');
      } else if (p.error) {
        clearInterval(state.downloadPollInterval);
        endDownloadUi(true);
        showToast(`Ошибка: ${p.error}`, 'error');
      }
    } catch {
      // transient network errors
    }
  }, 250);
}

function updateProgress(percent, dlMb, totMb, statusText, speedText) {
  const pct = Number(percent) || 0;
  dom.progressFill.style.width = `${pct}%`;
  dom.progressPercent.textContent = `${pct.toFixed(1)}%`;
  dom.progressStage.textContent = statusText || 'Загрузка...';
  dom.progressBytes.textContent = totMb > 0 ? `${Number(dlMb).toFixed(1)} / ${Number(totMb).toFixed(1)} МБ` : '';
  dom.progressSpeed.textContent = speedText || '';
}

/* ================= 6. UNCENSORED SEARCH ================= */
const SOURCE_META = {
  'Yandex Music': { cls: 'source-badge-ym', label: 'Яндекс' },
  'YouTube Music': { cls: 'source-badge-yt', label: 'YT Music' },
  'YouTube': { cls: 'source-badge-yt', label: 'YouTube' },
  'SoundCloud': { cls: 'source-badge-sc', label: 'SoundCloud' },
  'Spotify': { cls: 'source-badge-sp', label: 'Spotify' },
  'Deezer': { cls: 'source-badge-dz', label: 'Deezer' },
  'iTunes': { cls: 'source-badge-it', label: 'iTunes' }
};

const SOURCE_NAMES = {
  yandex: 'Яндекс Музыка',
  youtube: 'YouTube',
  soundcloud: 'SoundCloud',
  spotify: 'Spotify'
};

function initUncensoredEvents() {
  dom.btnTriggerAltSearch.addEventListener('click', () => triggerAltSearch());
  dom.altSearchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') triggerAltSearch();
  });

  dom.sourcePills.forEach(pill => {
    pill.addEventListener('click', () => {
      if (pill.classList.contains('active')) return;
      dom.sourcePills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      state.selectedSource = pill.dataset.source;
      if (dom.altSearchInput.value.trim()) triggerAltSearch({ force: true });
    });
  });

  enableDragScroll(dom.sourceFilterPills);
}

async function triggerAltSearch(opts = {}) {
  const query = dom.altSearchInput.value.trim();
  if (!query) {
    showToast('Введите запрос для поиска', 'error');
    return;
  }
  // Search button is locked while loading; a chip change restarts the search.
  if (state.alt.busy && !opts.force) return;
  if (state.alt.controller) state.alt.controller.abort();

  // Reference track only applies while the query is the one built from it
  const ref = state.alt.ref && state.alt.ref.query === query ? state.alt.ref : null;
  if (!ref) state.alt.ref = null;

  const controller = new AbortController();
  state.alt.controller = controller;
  state.alt.busy = true;
  setButtonLoading(dom.btnTriggerAltSearch, true);
  stopPreview();

  if (ref) {
    dom.altSearchContext.innerHTML = `Альтернативы для <b>${escapeHtml(ref.track.artist)} — ${escapeHtml(ref.track.title)}</b> · ${escapeHtml(ref.track.duration_str)}. Совпадения по длительности — выше.`;
    dom.altSearchContext.classList.remove('hidden');
  } else {
    dom.altSearchContext.classList.add('hidden');
  }

  const sourceName = state.selectedSource === 'all' ? 'всех источниках' : SOURCE_NAMES[state.selectedSource];
  dom.altSourceStatus.classList.add('hidden');
  dom.altResultsList.innerHTML = `
    <div class="empty-placeholder">
      <span class="spinner spinner-lg"></span>
      <p>Ищем в ${escapeHtml(sourceName)}...</p>
    </div>`;

  try {
    const data = await postJson('/api/search_uncensored', {
      query,
      source: state.selectedSource,
      ref_duration: ref ? ref.duration : 0
    }, controller.signal);
    if (controller !== state.alt.controller) return;
    state.alt.results = data.candidates || [];
    state.alt.shown = 0;
    renderSourceStatus(data.sources || {});
    renderAltCandidates(true);
  } catch (err) {
    if (err.name === 'AbortError') return;
    dom.altResultsList.innerHTML = `
      <div class="empty-placeholder is-error">
        ${ICONS.alert}
        <p>${escapeHtml(err.message)}</p>
      </div>`;
  } finally {
    if (controller === state.alt.controller) {
      state.alt.busy = false;
      state.alt.controller = null;
      setButtonLoading(dom.btnTriggerAltSearch, false);
    }
  }
}

function renderSourceStatus(sources) {
  const entries = Object.entries(sources);
  if (!entries.length) {
    dom.altSourceStatus.classList.add('hidden');
    return;
  }
  dom.altSourceStatus.innerHTML = entries.map(([name, s]) => {
    const label = SOURCE_NAMES[name] || name;
    if (s.error) {
      return `<span class="source-status is-error" title="${escapeHtml(s.error)}">${escapeHtml(label)}: ${escapeHtml(shortError(name, s.error))}</span>`;
    }
    if (s.fallback) {
      const why = s.reason ? `Spotify недоступен (${s.reason}), метаданные из ${s.fallback}` : `Метаданные из ${s.fallback}`;
      return `<span class="source-status is-fallback" title="${escapeHtml(why)}">${escapeHtml(label)} → ${escapeHtml(s.fallback)} · ${s.count}</span>`;
    }
    return `<span class="source-status">${escapeHtml(label)} · ${s.count}</span>`;
  }).join('');
  dom.altSourceStatus.classList.remove('hidden');
}

function shortError(source, msg) {
  if (source === 'spotify' && /Каталоги недоступны/i.test(msg)) return 'каталоги недоступны';
  if (source === 'yandex' && /регионе|VPN/i.test(msg)) return 'недоступно без входа';
  if (source === 'yandex' && /токен|token|Unauthorized/i.test(msg)) return 'нужен вход';
  return 'ошибка';
}

function renderAltCandidates(reset) {
  const list = state.alt.results;
  if (!list.length) {
    dom.altResultsList.innerHTML = `
      <div class="empty-placeholder">
        ${ICONS.search}
        <p>Ничего не найдено. Попробуйте другой источник или запрос.</p>
      </div>`;
    return;
  }

  if (reset) dom.altResultsList.innerHTML = '';
  const oldMore = dom.altResultsList.querySelector('.show-more-btn');
  if (oldMore) oldMore.remove();

  const from = state.alt.shown;
  const to = Math.min(list.length, from === 0 ? ALT_PAGE_SIZE : from + ALT_PAGE_STEP);
  for (let i = from; i < to; i++) {
    dom.altResultsList.appendChild(buildCandidateCard(list[i], i - from));
  }
  state.alt.shown = to;

  if (to < list.length) {
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'liquid-button btn-glass-accent show-more-btn';
    more.textContent = `Показать ещё (${list.length - to})`;
    more.addEventListener('click', () => renderAltCandidates(false));
    dom.altResultsList.appendChild(more);
  }
}

function buildCandidateCard(c, index) {
  const card = document.createElement('div');
  card.className = 'liquid-card candidate-card appear';
  card.style.setProperty('--i', Math.min(index, 10));

  const meta = SOURCE_META[c.source] || { cls: 'source-badge-yt', label: c.source || 'Web' };
  const metaTitle = c.audio_source ? `Метаданные: ${meta.label}` : `Источник: ${meta.label}`;
  const badges = [`<span class="badge ${meta.cls}" title="${escapeHtml(metaTitle)}">${escapeHtml(meta.label)}</span>`];
  if (c.audio_source) badges.push(`<span class="badge badge-muted" title="Аудио берётся с ${escapeHtml(c.audio_source)}">аудио: ${escapeHtml(c.audio_source)}</span>`);
  if (c.is_explicit) badges.push('<span class="badge badge-explicit">18+ Explicit</span>');
  if ((c.match_tags || []).includes('duration_match')) badges.push('<span class="badge badge-match">Длительность совпадает</span>');

  const thumb = c.thumbnail ? `<img class="candidate-thumb" src="${escapeHtml(c.thumbnail)}" alt="" loading="lazy">` : '';

  card.innerHTML = `
    <div class="candidate-top-row">
      ${thumb}
      <div class="candidate-heading">
        <span class="candidate-title">${escapeHtml(c.title)}</span>
        <span class="candidate-channel">${escapeHtml(c.artist || c.channel || '')}</span>
      </div>
      <span class="candidate-dur">${escapeHtml(c.duration_str || '')}</span>
    </div>
    <div class="candidate-meta-row">${badges.join('')}</div>
    <div class="candidate-actions">
      <button type="button" class="liquid-button btn-glass-sm btn-play-preview">
        <span class="play-icon">${ICONS.play}</span>
        <span class="play-label">Слушать</span>
      </button>
      <button type="button" class="liquid-button btn-glow-primary btn-dl-candidate">
        ${ICONS.download}
        <span>Скачать</span>
      </button>
    </div>`;

  const btnPlay = card.querySelector('.btn-play-preview');
  btnPlay.addEventListener('click', () => toggleAudioPreview(c, btnPlay));
  card.querySelector('.btn-dl-candidate').addEventListener('click', () => downloadAlternativeCandidate(c));
  return card;
}

function setPreviewButton(btn, mode) {
  if (!btn) return;
  const icon = btn.querySelector('.play-icon');
  const label = btn.querySelector('.play-label');
  btn.classList.toggle('is-loading', mode === 'loading');
  btn.classList.toggle('is-playing', mode === 'playing');
  if (mode === 'loading') {
    icon.innerHTML = '<span class="spinner"></span>';
    label.textContent = 'Загрузка';
  } else if (mode === 'playing') {
    icon.innerHTML = ICONS.pause;
    label.textContent = 'Пауза';
  } else {
    icon.innerHTML = ICONS.play;
    label.textContent = 'Слушать';
  }
}

function stopPreview() {
  dom.audioPlayer.pause();
  if (state.activePreview) setPreviewButton(state.activePreview.btn, 'idle');
  state.activePreview = null;
}

async function toggleAudioPreview(candidate, btnEl) {
  if (state.activePreview && state.activePreview.id === candidate.id) {
    stopPreview();
    return;
  }
  stopPreview();
  state.activePreview = { id: candidate.id, btn: btnEl };
  setPreviewButton(btnEl, 'loading');

  try {
    const data = await postJson('/api/get_preview_url', { candidate });
    if (!state.activePreview || state.activePreview.id !== candidate.id) return;
    dom.audioPlayer.src = data.preview_url;
    await dom.audioPlayer.play();
    setPreviewButton(btnEl, 'playing');
    dom.audioPlayer.onended = () => stopPreview();
  } catch (err) {
    if (state.activePreview && state.activePreview.id === candidate.id) {
      setPreviewButton(btnEl, 'idle');
      state.activePreview = null;
    }
    showToast(err.message || 'Не удалось воспроизвести', 'error');
  }
}

async function downloadAlternativeCandidate(candidate) {
  if (state.isDownloading) {
    showToast('Дождитесь окончания текущей загрузки', 'info');
    return;
  }
  stopPreview();

  // Original Yandex tags are applied only when the search was started from that track
  const ymTrack = state.alt.ref && candidate.source !== 'Yandex Music' ? state.alt.ref.track : null;

  switchTab('tab-download');
  beginDownloadUi('Подготовка загрузки...');

  try {
    await postJson('/api/download_alternative', { candidate, ym_track: ymTrack });
    startDownloadPolling();
  } catch (err) {
    endDownloadUi(false);
    showToast(err.message, 'error');
  }
}

/* ================= 7. HISTORY ================= */
async function loadHistory() {
  dom.historyList.innerHTML = `
    <div class="empty-placeholder">
      <span class="spinner spinner-lg"></span>
      <p>Загрузка библиотеки...</p>
    </div>`;

  try {
    const res = await fetch('/api/history');
    const data = await res.json();

    if (!data.history || data.history.length === 0) {
      dom.historyList.innerHTML = `<div class="empty-placeholder">${ICONS.folder}<p>В папке пока нет скачанных треков</p></div>`;
      return;
    }

    dom.historyList.innerHTML = '';
    data.history.forEach((item, i) => {
      const card = document.createElement('div');
      card.className = 'liquid-card candidate-card appear';
      card.style.setProperty('--i', Math.min(i, 10));
      card.innerHTML = `
        <div class="candidate-top-row">
          <div class="candidate-heading">
            <span class="candidate-title">${escapeHtml(item.title || item.filename)}</span>
            <span class="candidate-channel">${escapeHtml(item.artist || 'Неизвестный исполнитель')}</span>
          </div>
          <span class="candidate-dur">${escapeHtml(item.size_mb)} МБ</span>
        </div>
        <div class="candidate-actions">
          <button type="button" class="liquid-button btn-glass-sm btn-reveal-file">
            ${ICONS.folder}
            <span>Открыть папку</span>
          </button>
        </div>`;
      card.querySelector('.btn-reveal-file').addEventListener('click', openDownloadFolder);
      dom.historyList.appendChild(card);
    });
  } catch (err) {
    dom.historyList.innerHTML = `<div class="empty-placeholder is-error">${ICONS.alert}<p>Ошибка: ${escapeHtml(err.message)}</p></div>`;
  }
}

dom.btnRefreshHistory.addEventListener('click', loadHistory);

/* ================= 8. SYSTEM / FOLDER ================= */
async function openDownloadFolder() {
  try {
    await postJson('/api/open_folder', {});
    showToast('Папка загрузок открыта', 'success');
  } catch (err) {
    showToast('Не удалось открыть папку', 'error');
  }
}

/* ================= 9. SETTINGS: SPOTIFY ================= */
function setSpotifyStatus(kind, text) {
  if (!dom.spotifyStatus) return;
  dom.spotifyStatus.classList.toggle('is-ok', kind === 'ok');
  dom.spotifyStatus.classList.toggle('is-error', kind === 'error');
  dom.spotifyStatus.textContent = text || (kind === 'ok' ? 'Ваши ключи' : kind === 'error' ? 'Ключи не приняты' : 'Встроенные ключи');
}

function initSettingsEvents() {
  if (!dom.btnSaveSpotify) return;
  dom.btnSaveSpotify.addEventListener('click', async () => {
    setButtonLoading(dom.btnSaveSpotify, true);
    try {
      const data = await postJson('/api/spotify_credentials', {
        client_id: dom.spotifyClientId.value.trim(),
        client_secret: dom.spotifyClientSecret.value.trim()
      });
      dom.spotifyClientSecret.value = '';
      if (!data.configured) dom.spotifyClientId.value = '';
      setSpotifyStatus(data.configured ? 'ok' : 'none');
      showToast(data.configured ? 'Используются ваши ключи Spotify' : 'Используются встроенные ключи', 'success');
    } catch (err) {
      setSpotifyStatus('error');
      setTimeout(() => loadInitialStatus(), 2500);
      showToast(err.message, 'error');
    } finally {
      setButtonLoading(dom.btnSaveSpotify, false);
    }
  });
}

/* ================= 10. MODALS & AUTH ================= */
function initModals() {
  const openDevice = () => {
    openModal(dom.modalDevice);
    startDeviceAuthFlow();
  };
  dom.btnQuickToken.addEventListener('click', openDevice);
  dom.btnOpenDeviceAuth.addEventListener('click', openDevice);
  dom.btnOpenManualAuth.addEventListener('click', () => openModal(dom.modalManual));

  document.querySelectorAll('[data-close-modal]').forEach(btn => {
    btn.addEventListener('click', () => {
      closeModal(document.getElementById(btn.dataset.closeModal));
      stopDeviceAuthPolling();
    });
  });

  dom.btnCopyDeviceCode.addEventListener('click', () => {
    const code = dom.deviceCodeVal.textContent;
    if (code && code !== '------') {
      navigator.clipboard.writeText(code);
      showToast('Код скопирован', 'success');
    }
  });

  dom.btnSubmitManualToken.addEventListener('click', async () => {
    const token = dom.manualTokenInput.value.trim();
    if (!token) {
      showToast('Введите токен', 'error');
      return;
    }
    setButtonLoading(dom.btnSubmitManualToken, true);
    try {
      const data = await postJson('/api/auth/save_token', { token });
      if (!data.success) throw new Error(data.error || 'Неверный токен');
      showToast(`Успешно: ${data.account}`, 'success');
      closeModal(dom.modalManual);
      loadInitialStatus();
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setButtonLoading(dom.btnSubmitManualToken, false);
    }
  });

  if (dom.btnAuthLogout) {
    dom.btnAuthLogout.addEventListener('click', async () => {
      try {
        await postJson('/api/auth/logout', {});
        try {
          localStorage.removeItem('yasave_user');
          localStorage.removeItem('yasave_has_plus');
        } catch (e) {}
        showToast('Вы вышли из аккаунта', 'info');
        loadInitialStatus();
      } catch (err) {
        showToast('Ошибка при выходе: ' + err.message, 'error');
      }
    });
  }
}

function openModal(el) { el.classList.add('active'); }
function closeModal(el) { el.classList.remove('active'); }

async function startDeviceAuthFlow() {
  dom.deviceCodeVal.textContent = '...';
  dom.devicePollStatus.textContent = 'Генерация кода устройства...';
  dom.devicePollStatus.style.color = '';
  try {
    const data = await postJson('/api/auth/device_code', {});
    dom.deviceCodeVal.textContent = data.user_code;
    dom.devicePollStatus.textContent = 'Ожидание подтверждения на ya.ru/device...';
    startDeviceAuthPolling(data.device_code);
  } catch (err) {
    dom.devicePollStatus.textContent = `Ошибка: ${err.message}`;
  }
}

function startDeviceAuthPolling(deviceCode) {
  stopDeviceAuthPolling();
  state.devicePollingInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/auth/poll_token?code=${encodeURIComponent(deviceCode)}`);
      const data = await res.json();
      if (data.success && data.token) {
        stopDeviceAuthPolling();
        dom.devicePollStatus.textContent = 'Успешная авторизация';
        dom.devicePollStatus.style.color = 'var(--success)';
        showToast('Авторизация успешна', 'success');
        setTimeout(() => {
          closeModal(dom.modalDevice);
          loadInitialStatus();
        }, 1200);
      } else if (data.expired) {
        stopDeviceAuthPolling();
        dom.devicePollStatus.textContent = 'Время действия кода истекло.';
      }
    } catch {
      // transient poll errors
    }
  }, 4000);
}

function stopDeviceAuthPolling() {
  if (state.devicePollingInterval) {
    clearInterval(state.devicePollingInterval);
    state.devicePollingInterval = null;
  }
}

/* ================= 11. TOASTS ================= */
function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span class="toast-dot" aria-hidden="true"></span><span class="toast-text"></span>`;
  toast.querySelector('.toast-text').textContent = message;
  dom.toastContainer.appendChild(toast);
  while (dom.toastContainer.children.length > 3) dom.toastContainer.firstChild.remove();
  setTimeout(() => toast.remove(), 3500);
}
