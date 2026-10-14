// Application State
const state = {
  currentTrack: null,
  isDownloading: false,
  downloadPollInterval: null,
  activePreviewId: null,
  devicePollingInterval: null,
  accentColor: '#FFCC00',
  theme: 'dark',
  selectedSource: 'all'
};

// DOM Cache
const dom = {
  splash: document.getElementById('splash-screen'),
  navItems: document.querySelectorAll('.nav-item'),
  screens: document.querySelectorAll('.screen-tab'),
  btnThemeToggle: document.getElementById('btn-theme-toggle'),
  btnQuickToken: document.getElementById('btn-quick-token'),
  headerStatus: document.getElementById('header-user-status'),
  
  // Downloader elements
  trackUrlInput: document.getElementById('track-url-input'),
  btnPasteClipboard: document.getElementById('btn-paste-clipboard'),
  btnFetchTrack: document.getElementById('btn-fetch-track'),
  trackHeroCard: document.getElementById('track-hero-card'),
  trackCoverImg: document.getElementById('track-cover-img'),
  trackTitle: document.getElementById('track-title'),
  trackArtist: document.getElementById('track-artist'),
  trackDuration: document.getElementById('track-duration'),
  trackAlbum: document.getElementById('track-album'),
  badgeExplicit: document.getElementById('badge-explicit'),
  btnDownloadYm: document.getElementById('btn-download-ym'),
  btnFindUncensored: document.getElementById('btn-find-uncensored'),
  progressContainer: document.getElementById('progress-container'),
  progressFill: document.getElementById('progress-fill'),
  progressPercent: document.getElementById('progress-percent'),
  progressStage: document.getElementById('progress-stage-text'),
  progressBytes: document.getElementById('progress-bytes'),
  progressSpeed: document.getElementById('progress-speed'),
  resultSuccessCard: document.getElementById('result-success-card'),
  successFilename: document.getElementById('success-filename'),
  btnOpenFolderAction: document.getElementById('btn-open-folder-action'),
  
  // Uncensored elements
  altSearchInput: document.getElementById('alt-search-input'),
  btnTriggerAltSearch: document.getElementById('btn-trigger-alt-search'),
  altResultsList: document.getElementById('alt-results-list'),
  audioPlayer: document.getElementById('global-preview-player'),

  // History elements
  historyList: document.getElementById('history-items-list'),
  btnRefreshHistory: document.getElementById('btn-refresh-history'),
  historyFolderLabel: document.getElementById('history-folder-label'),

  // Settings elements
  swatches: document.querySelectorAll('.palette-swatch'),
  accentPaletteScroll: document.getElementById('accent-palette-scroll'),
  btnRainbowPicker: document.getElementById('btn-rainbow-picker'),
  customColorPicker: document.getElementById('custom-color-picker'),
  settingsAccountName: document.getElementById('settings-account-name'),
  settingsAccountSub: document.getElementById('settings-account-sub'),
  settingsStoragePath: document.getElementById('settings-storage-path'),
  btnOpenDeviceAuth: document.getElementById('btn-open-device-auth'),
  btnOpenManualAuth: document.getElementById('btn-open-manual-auth'),
  btnOpenStorageFolder: document.getElementById('btn-open-storage-folder'),

  // Modals
  modalDevice: document.getElementById('modal-device-auth'),
  modalManual: document.getElementById('modal-manual-auth'),
  deviceCodeVal: document.getElementById('device-code-val'),
  btnCopyDeviceCode: document.getElementById('btn-copy-device-code'),
  devicePollStatus: document.getElementById('device-poll-status'),
  manualTokenInput: document.getElementById('manual-token-input'),
  btnSubmitManualToken: document.getElementById('btn-submit-manual-token'),
  btnAuthLogout: document.getElementById('btn-auth-logout'),
  // Uncensored source filter pills
  sourceFilterPills: document.getElementById('source-filter-pills'),
  sourcePills: document.querySelectorAll('.source-pill'),
  toastContainer: document.getElementById('toast-container')
};

// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
  restoreCachedSession();
  initSplashScreen();
  initNavigation();
  initAccentPalette();
  initThemeToggle();
  initDownloaderEvents();
  initUncensoredEvents();
  initModals();
  loadInitialStatus();
});

/* ================= 0. INSTANT ZERO-FLICKER CACHED SESSION RESTORE ================= */
function restoreCachedSession() {
  try {
    const savedTheme = localStorage.getItem('yasave_theme');
    if (savedTheme) {
      document.documentElement.dataset.theme = savedTheme;
      state.theme = savedTheme;
    }

    const savedAccent = localStorage.getItem('yasave_accent');
    if (savedAccent) {
      applyAccentColor(savedAccent);
    }

    const savedUser = localStorage.getItem('yasave_user');
    const hasPlus = localStorage.getItem('yasave_has_plus') === '1';
    if (savedUser) {
      dom.headerStatus.textContent = hasPlus ? '★ Плюс активен' : 'Авторизован';
      dom.headerStatus.style.color = 'var(--accent)';
      dom.settingsAccountName.textContent = savedUser;
      dom.settingsAccountSub.textContent = hasPlus ? 'Подписка Яндекс Плюс активна' : 'Без подписки';
      if (dom.btnAuthLogout) dom.btnAuthLogout.classList.remove('hidden');
    }
  } catch (e) {
    console.error('Failed to restore cached session:', e);
  }
}

/* ================= 1. SPLASH SCREEN (MINIMALIST TELEGRAM / YOUTUBE STYLE) ================= */
function initSplashScreen() {
  const dismiss = () => {
    if (dom.splash && !dom.splash.classList.contains('hidden')) {
      dom.splash.classList.add('hidden');
    }
  };

  // Minimalist smooth auto-transition after 1.25s
  setTimeout(dismiss, 1250);

  if (dom.splash) dom.splash.addEventListener('click', dismiss);
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === 'Escape' || e.key === ' ') dismiss();
  });
}

/* ================= 2. NAVIGATION & TABS ================= */
function initNavigation() {
  dom.navItems.forEach((btn, index) => {
    btn.addEventListener('click', () => {
      switchTab(btn.dataset.tab, index);
    });
  });
}

function switchTab(tabId, index) {
  // Update buttons
  dom.navItems.forEach(item => item.classList.remove('active'));
  const activeBtn = Array.from(dom.navItems).find(b => b.dataset.tab === tabId);
  if (activeBtn) activeBtn.classList.add('active');

  // Update screens
  dom.screens.forEach(screen => {
    screen.classList.remove('active');
    if (screen.id === tabId) {
      screen.classList.add('active');
    }
  });

  // Lazy tab loads
  if (tabId === 'tab-history') {
    loadHistory();
  }
}

/* ================= 3. ACCENT PALETTE & THEMES ================= */
function initAccentPalette() {
  const swatches = document.querySelectorAll('.palette-swatch:not(.rainbow-swatch)');
  swatches.forEach(swatch => {
    swatch.addEventListener('click', () => {
      const color = swatch.dataset.color;
      applyAccentColor(color);
      saveAccentColor(color);
    });
  });

  // Rainbow color wheel picker
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

  // Enable smooth mouse dragging & wheel scroll for PC desktop
  enableDragScroll(dom.accentPaletteScroll);
}

// Universal smooth mouse-drag and wheel horizontal scroll helper for PC
function enableDragScroll(container) {
  if (!container) return;
  let isDown = false;
  let startX = 0;
  let scrollLeft = 0;
  let hasDragged = false;

  container.addEventListener('mousedown', (e) => {
    isDown = true;
    hasDragged = false;
    startX = e.pageX - container.offsetLeft;
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
    const x = e.pageX - container.offsetLeft;
    const walk = (x - startX);
    if (Math.abs(walk) > 3) {
      hasDragged = true;
    }
    container.scrollLeft = scrollLeft - walk;
  });

  // Capture phase: prevent child button click if user was drag-scrolling
  container.addEventListener('click', (e) => {
    if (hasDragged) {
      e.preventDefault();
      e.stopPropagation();
    }
  }, true);

  // Wheel horizontal scrolling (convert vertical mouse wheel into horizontal scroll)
  container.addEventListener('wheel', (e) => {
    if (e.deltaY !== 0) {
      e.preventDefault();
      container.scrollLeft += e.deltaY;
    }
  }, { passive: false });
}

function saveAccentColor(hexColor) {
  try {
    localStorage.setItem('yasave_accent', hexColor);
  } catch (e) {}

  fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ accent_color: hexColor })
  }).catch(console.error);
}

function applyAccentColor(hexColor) {
  if (!hexColor) return;
  state.accentColor = hexColor;

  // 1. Calculate RGB & Perceived Luminance
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

  // 2. Calculate HSL
  const hsl = hexToHSL(hexColor);
  const { h, s, l } = hsl;

  // 3. Handle corner cases (white, platinum, gray, black, custom colors)
  const isMonochrome = (s < 35 && l > 70) || s < 18 || l < 10 || l > 93;
  let gradientStr = '';
  let glowStr = '';
  let subtleStr = '';

  if (isMonochrome) {
    // Elegant monochrome / frosted platinum / silver / dark slate
    if (l > 75) {
      // White & Light Platinum (e.g. #E2E8F0, #FFFFFF)
      gradientStr = 'linear-gradient(135deg, #ffffff 0%, #cbd5e1 100%)';
      glowStr = 'rgba(255, 255, 255, 0.45)';
      subtleStr = 'rgba(255, 255, 255, 0.16)';
    } else if (l < 25) {
      // Dark Charcoal / Black (e.g. #000000, #1e293b)
      gradientStr = 'linear-gradient(135deg, #1e293b 0%, #475569 100%)';
      glowStr = 'rgba(255, 255, 255, 0.25)';
      subtleStr = 'rgba(255, 255, 255, 0.10)';
    } else {
      // Middle Gray / Slate (e.g. #808080, #94a3b8)
      gradientStr = `linear-gradient(135deg, ${hexColor} 0%, #475569 100%)`;
      glowStr = `rgba(${r}, ${g}, ${b}, 0.35)`;
      subtleStr = `rgba(${r}, ${g}, ${b}, 0.14)`;
    }
  } else {
    // Vibrant & Colorful (Red, Gold, Purple, Cyan, Emerald, etc.)
    const h2 = (h - 16 + 360) % 360;
    const s2 = Math.max(s - 8, 20);
    const l2 = Math.max(l - 6, 18);
    gradientStr = `linear-gradient(135deg, hsl(${h}, ${s}%, ${l}%), hsl(${h2}, ${s2}%, ${l2}%))`;
    glowStr = `hsla(${h}, ${s}%, ${l}%, 0.42)`;
    subtleStr = `hsla(${h}, ${s}%, ${l}%, 0.16)`;
  }

  // Set CSS Custom Properties directly
  const root = document.documentElement;
  root.style.setProperty('--accent-h', h);
  root.style.setProperty('--accent-s', `${s}%`);
  root.style.setProperty('--accent-l', `${l}%`);
  root.style.setProperty('--accent', hexColor);
  root.style.setProperty('--accent-contrast', contrastText);
  root.style.setProperty('--accent-gradient', gradientStr);
  root.style.setProperty('--accent-glow', glowStr);
  root.style.setProperty('--accent-subtle', subtleStr);

  // Update active preset swatch state
  const swatches = document.querySelectorAll('.palette-swatch:not(.rainbow-swatch)');
  let matchedPreset = false;
  swatches.forEach(swatchEl => {
    const isMatch = swatchEl.dataset.color && swatchEl.dataset.color.toLowerCase() === hexColor.toLowerCase();
    swatchEl.classList.toggle('active', isMatch);
    if (isMatch) matchedPreset = true;
  });

  // If custom color, highlight the rainbow swatch
  if (dom.btnRainbowPicker) {
    dom.btnRainbowPicker.classList.toggle('active', !matchedPreset);
  }
  if (dom.customColorPicker) {
    dom.customColorPicker.value = hexColor;
  }
}

function hexToHSL(hex) {
  let r = 0, g = 0, b = 0;
  if (hex.length === 4) {
    r = "0x" + hex[1] + hex[1];
    g = "0x" + hex[2] + hex[2];
    b = "0x" + hex[3] + hex[3];
  } else if (hex.length === 7) {
    r = "0x" + hex[1] + hex[2];
    g = "0x" + hex[3] + hex[4];
    b = "0x" + hex[5] + hex[6];
  }
  r /= 255; g /= 255; b /= 255;
  const cmin = Math.min(r,g,b), cmax = Math.max(r,g,b), delta = cmax - cmin;
  let h = 0, s = 0, l = 0;
  if (delta === 0) h = 0;
  else if (cmax === r) h = ((g - b) / delta) % 6;
  else if (cmax === g) h = (b - r) / delta + 2;
  else h = (r - g) / delta + 4;
  h = Math.round(h * 60);
  if (h < 0) h += 360;
  l = (cmax + cmin) / 2;
  s = delta === 0 ? 0 : delta / (1 - Math.abs(2 * l - 1));
  s = +(s * 100).toFixed(1);
  l = +(l * 100).toFixed(1);
  return { h, s, l };
}

function initThemeToggle() {
  dom.btnThemeToggle.addEventListener('click', () => {
    const current = document.documentElement.dataset.theme;
    const nextTheme = current === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = nextTheme;
    state.theme = nextTheme;

    try {
      localStorage.setItem('yasave_theme', nextTheme);
    } catch (e) {}

    fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme: nextTheme })
    }).catch(console.error);

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
      dom.headerStatus.textContent = data.has_plus ? '★ Плюс активен' : 'Авторизован';
      dom.headerStatus.style.color = 'var(--accent)';
      dom.settingsAccountName.textContent = displayName;
      dom.settingsAccountSub.textContent = data.has_plus ? 'Подписка Яндекс Плюс активна' : 'Без подписки';
      if (dom.btnAuthLogout) dom.btnAuthLogout.classList.remove('hidden');

      try {
        localStorage.setItem('yasave_user', displayName);
        localStorage.setItem('yasave_has_plus', data.has_plus ? '1' : '0');
      } catch (e) {}
    } else {
      dom.headerStatus.textContent = 'Требуется вход';
      dom.headerStatus.style.color = '#ff453a';
      dom.settingsAccountName.textContent = 'Не авторизован';
      dom.settingsAccountSub.textContent = 'Нажмите для входа';
      if (dom.btnAuthLogout) dom.btnAuthLogout.classList.add('hidden');

      try {
        localStorage.removeItem('yasave_user');
        localStorage.removeItem('yasave_has_plus');
      } catch (e) {}
    }

    if (data.download_dir) {
      dom.settingsStoragePath.textContent = data.download_dir;
      dom.historyFolderLabel.textContent = `Загрузки сохранены в: ${data.download_dir}`;
    }
  } catch (err) {
    console.error('Failed to load initial status:', err);
  }
}

/* ================= 5. DOWNLOADER EVENTS ================= */
function initDownloaderEvents() {
  // Paste from clipboard
  dom.btnPasteClipboard.addEventListener('click', async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        dom.trackUrlInput.value = text.trim();
        fetchTrackInfo();
      }
    } catch {
      showToast('Вставьте ссылку вручную', 'info');
    }
  });

  // Search button
  dom.btnFetchTrack.addEventListener('click', fetchTrackInfo);
  dom.trackUrlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') fetchTrackInfo();
  });

  // Download YM Button
  dom.btnDownloadYm.addEventListener('click', startYmDownload);

  // Switch to uncensored search button
  dom.btnFindUncensored.addEventListener('click', () => {
    if (state.currentTrack) {
      dom.altSearchInput.value = `${state.currentTrack.artist} ${state.currentTrack.title}`;
      switchTab('tab-uncensored', 1);
      triggerAltSearch();
    }
  });

  // Open folder action button
  dom.btnOpenFolderAction.addEventListener('click', openDownloadFolder);
  dom.btnOpenStorageFolder.addEventListener('click', openDownloadFolder);
}

async function fetchTrackInfo() {
  const url = dom.trackUrlInput.value.trim();
  if (!url) {
    showToast('Введите ссылку на трек!', 'error');
    return;
  }

  dom.btnFetchTrack.disabled = true;
  dom.btnFetchTrack.style.opacity = '0.5';
  showToast('Поиск трека в Яндекс Музыке...', 'info');

  try {
    const res = await fetch('/api/track_info', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    const data = await res.json();

    if (!res.ok || data.error) {
      throw new Error(data.error || 'Трек не найден');
    }

    const t = data.track;
    state.currentTrack = t;

    // Render Hero Track Card
    dom.trackHeroCard.classList.remove('empty-state');
    dom.trackTitle.textContent = t.title;
    dom.trackArtist.textContent = t.artist;
    dom.trackDuration.textContent = t.duration_str;
    dom.trackAlbum.textContent = t.album || (t.year ? `Релиз ${t.year}` : 'Сингл');
    
    if (t.cover_url) {
      dom.trackCoverImg.src = t.cover_url;
    }

    if (t.explicit) {
      dom.badgeExplicit.classList.remove('hidden');
    } else {
      dom.badgeExplicit.classList.add('hidden');
    }

    dom.btnDownloadYm.disabled = false;
    dom.btnFindUncensored.disabled = false;
    dom.resultSuccessCard.classList.add('hidden');

    showToast(`Найдено: ${t.artist} — ${t.title}`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    dom.btnFetchTrack.disabled = false;
    dom.btnFetchTrack.style.opacity = '1';
  }
}

async function startYmDownload() {
  if (!state.currentTrack || state.isDownloading) return;

  state.isDownloading = true;
  dom.btnDownloadYm.disabled = true;
  dom.btnFindUncensored.disabled = true;
  dom.progressContainer.classList.remove('hidden');
  dom.resultSuccessCard.classList.add('hidden');
  updateProgress(0, 0, 0, 'Запуск загрузки...', '');

  try {
    const res = await fetch('/api/download_ym', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ track_info: state.currentTrack })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Ошибка старта загрузки');

    startDownloadPolling();
  } catch (err) {
    state.isDownloading = false;
    dom.btnDownloadYm.disabled = false;
    dom.btnFindUncensored.disabled = false;
    dom.progressContainer.classList.add('hidden');
    showToast(err.message, 'error');
  }
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
        state.isDownloading = false;
        dom.btnDownloadYm.disabled = false;
        dom.btnFindUncensored.disabled = false;

        const filename = p.filepath ? p.filepath.split(/[\\/]/).pop() : 'Трек сохранён';
        dom.successFilename.textContent = filename;
        dom.resultSuccessCard.classList.remove('hidden');
        showToast('Скачивание успешно завершено!', 'success');
      } else if (p.error) {
        clearInterval(state.downloadPollInterval);
        state.isDownloading = false;
        dom.btnDownloadYm.disabled = false;
        dom.btnFindUncensored.disabled = false;
        showToast(`Ошибка: ${p.error}`, 'error');
      }
    } catch {
      // ignore transient network errors
    }
  }, 250);
}

function updateProgress(percent, dlMb, totMb, statusText, speedText) {
  dom.progressFill.style.width = `${percent}%`;
  dom.progressPercent.textContent = `${percent.toFixed(1)}%`;
  dom.progressStage.textContent = statusText || 'Загрузка...';

  if (totMb > 0) {
    dom.progressBytes.textContent = `${dlMb.toFixed(1)} / ${totMb.toFixed(1)} МБ`;
  } else {
    dom.progressBytes.textContent = '';
  }
  dom.progressSpeed.textContent = speedText || '';
}

/* ================= 6. UNCENSORED ALTERNATIVE SOURCES ================= */
function initUncensoredEvents() {
  dom.btnTriggerAltSearch.addEventListener('click', triggerAltSearch);
  dom.altSearchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') triggerAltSearch();
  });

  // Source Selector Pills (All, SoundCloud, Spotify, YouTube)
  dom.sourcePills.forEach(pill => {
    pill.addEventListener('click', () => {
      dom.sourcePills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      state.selectedSource = pill.dataset.source;
      if (dom.altSearchInput.value.trim()) {
        triggerAltSearch();
      }
    });
  });

  // Enable mouse-drag & wheel scroll on source pills
  enableDragScroll(dom.sourceFilterPills);
}

async function triggerAltSearch() {
  const query = dom.altSearchInput.value.trim();
  if (!query) {
    showToast('Введите запрос для поиска', 'error');
    return;
  }

  // Parse artist and title if query contains dash
  let artist = '';
  let title = query;
  if (query.includes(' - ')) {
    const parts = query.split(' - ');
    artist = parts[0].trim();
    title = parts[1].trim();
  }

  const sourceLabels = {
    all: 'SoundCloud, Spotify и YouTube',
    soundcloud: 'SoundCloud',
    spotify: 'Spotify Match',
    youtube: 'YouTube Music'
  };
  const sourceName = sourceLabels[state.selectedSource] || 'источниках';

  dom.altResultsList.innerHTML = `
    <div class="empty-placeholder">
      <div class="pulsing-spinner" style="width: 28px; height: 28px;"></div>
      <p>Ищем версии без цензуры в ${sourceName}...</p>
    </div>
  `;

  try {
    const res = await fetch('/api/search_uncensored', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        artist, 
        title, 
        source: state.selectedSource 
      })
    });
    const data = await res.json();

    if (!res.ok || data.error) throw new Error(data.error || 'Ничего не найдено');
    renderAltCandidates(data.candidates);
  } catch (err) {
    dom.altResultsList.innerHTML = `
      <div class="empty-placeholder">
        <p style="color: #ff453a;">${err.message}</p>
      </div>
    `;
  }
}

function renderAltCandidates(candidates) {
  if (!candidates || candidates.length === 0) {
    dom.altResultsList.innerHTML = `
      <div class="empty-placeholder">
        <p>Варианты не найдены. Попробуйте изменить фильтр источника или запрос.</p>
      </div>
    `;
    return;
  }

  dom.altResultsList.innerHTML = '';
  candidates.forEach(c => {
    const card = document.createElement('div');
    card.className = 'liquid-card candidate-card';

    let badgeClass = 'source-badge-yt';
    let badgeText = 'YouTube';
    if (c.source === 'SoundCloud') {
      badgeClass = 'source-badge-sc';
      badgeText = 'SoundCloud';
    } else if (c.source === 'Spotify') {
      badgeClass = 'source-badge-sp';
      badgeText = 'Spotify';
    }

    card.innerHTML = `
      <div class="candidate-top-row">
        <span class="candidate-title">${escapeHtml(c.title)}</span>
        <span class="candidate-dur">${c.duration_str}</span>
      </div>
      <div class="candidate-meta-row">
        <span class="badge ${badgeClass}">${badgeText}</span>
        <span class="badge badge-explicit">18+ UNENSORED</span>
        <span>•</span>
        <span>${escapeHtml(c.channel)}</span>
      </div>
      <div class="candidate-actions">
        <button class="liquid-button btn-glass-sm btn-play-preview" data-url="${escapeHtml(c.url)}" data-id="${c.id}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width: 14px; height: 14px;"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
          <span class="play-label">Предпрослушивание</span>
        </button>
        <button class="liquid-button btn-glow-primary btn-dl-candidate" data-id="${c.id}">
          ⚡ Скачать этот вариант
        </button>
      </div>
    `;

    // Preview play handler
    const btnPlay = card.querySelector('.btn-play-preview');
    btnPlay.addEventListener('click', () => toggleAudioPreview(c.url, c.id, btnPlay));

    // Download handler
    const btnDl = card.querySelector('.btn-dl-candidate');
    btnDl.addEventListener('click', () => downloadAlternativeCandidate(c));

    dom.altResultsList.appendChild(card);
  });
}

async function toggleAudioPreview(webUrl, id, btnEl) {
  const label = btnEl.querySelector('.play-label');

  if (state.activePreviewId === id && !dom.audioPlayer.paused) {
    dom.audioPlayer.pause();
    state.activePreviewId = null;
    label.textContent = 'Предпрослушивание';
    return;
  }

  label.textContent = 'Загрузка...';

  try {
    const res = await fetch('/api/get_preview_url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: webUrl })
    });
    const data = await res.json();
    if (!res.ok || !data.preview_url) throw new Error('Не удалось получить аудиопоток');

    dom.audioPlayer.src = data.preview_url;
    dom.audioPlayer.play();
    state.activePreviewId = id;
    label.textContent = '⏸ Стоп';

    dom.audioPlayer.onended = () => {
      state.activePreviewId = null;
      label.textContent = 'Предпрослушивание';
    };
  } catch (err) {
    label.textContent = 'Ошибка';
    showToast(err.message, 'error');
  }
}

async function downloadAlternativeCandidate(candidate) {
  if (!state.currentTrack) {
    showToast('Сначала выберите трек во вкладке «Скачать» для применения метаданных!', 'error');
    return;
  }

  // Stop audio preview
  dom.audioPlayer.pause();
  state.activePreviewId = null;

  // Switch to Downloader tab to show progress
  switchTab('tab-download', 0);

  state.isDownloading = true;
  dom.btnDownloadYm.disabled = true;
  dom.btnFindUncensored.disabled = true;
  dom.progressContainer.classList.remove('hidden');
  dom.resultSuccessCard.classList.add('hidden');
  updateProgress(0, 0, 0, 'Подготовка альтернативного трека...', '');

  try {
    const res = await fetch('/api/download_alternative', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        candidate,
        ym_track: state.currentTrack
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Ошибка загрузки');

    startDownloadPolling();
  } catch (err) {
    state.isDownloading = false;
    dom.btnDownloadYm.disabled = false;
    dom.btnFindUncensored.disabled = false;
    showToast(err.message, 'error');
  }
}

/* ================= 7. HISTORY / LIBRARY ================= */
async function loadHistory() {
  dom.historyList.innerHTML = `
    <div class="empty-placeholder">
      <div class="pulsing-spinner" style="width: 24px; height: 24px;"></div>
      <p>Загрузка библиотеки...</p>
    </div>
  `;

  try {
    const res = await fetch('/api/history');
    const data = await res.json();

    if (!data.history || data.history.length === 0) {
      dom.historyList.innerHTML = `
        <div class="empty-placeholder">
          <p>В папке пока нет скачанных треков</p>
        </div>
      `;
      return;
    }

    dom.historyList.innerHTML = '';
    data.history.forEach(item => {
      const card = document.createElement('div');
      card.className = 'liquid-card candidate-card';
      card.innerHTML = `
        <div class="candidate-top-row">
          <span class="candidate-title">${escapeHtml(item.title || item.filename)}</span>
          <span class="candidate-dur">${item.size_mb} МБ</span>
        </div>
        <div class="candidate-meta-row">
          <span>${escapeHtml(item.artist || 'Неизвестный автор')}</span>
          <span>•</span>
          <span>MP3</span>
        </div>
        <div class="candidate-actions">
          <button class="liquid-button btn-glass-sm btn-reveal-file" style="flex: 1;">
            📂 Показать в проводнике
          </button>
        </div>
      `;
      card.querySelector('.btn-reveal-file').addEventListener('click', openDownloadFolder);
      dom.historyList.appendChild(card);
    });
  } catch (err) {
    dom.historyList.innerHTML = `<div class="empty-placeholder"><p>Ошибка: ${err.message}</p></div>`;
  }
}

dom.btnRefreshHistory.addEventListener('click', loadHistory);

/* ================= 8. SYSTEM / FOLDER ACTIONS ================= */
async function openDownloadFolder() {
  try {
    await fetch('/api/open_folder', { method: 'POST' });
    showToast('Папка загрузок открыта', 'success');
  } catch (err) {
    showToast('Не удалось открыть папку', 'error');
  }
}

/* ================= 9. MODALS & AUTHENTICATION ================= */
function initModals() {
  // Quick Token Button
  dom.btnQuickToken.addEventListener('click', () => {
    openModal(dom.modalDevice);
    startDeviceAuthFlow();
  });

  // Settings Auth buttons
  dom.btnOpenDeviceAuth.addEventListener('click', () => {
    openModal(dom.modalDevice);
    startDeviceAuthFlow();
  });

  dom.btnOpenManualAuth.addEventListener('click', () => {
    openModal(dom.modalManual);
  });

  // Close modals
  document.querySelectorAll('[data-close-modal]').forEach(btn => {
    btn.addEventListener('click', () => {
      const modalId = btn.dataset.closeModal;
      closeModal(document.getElementById(modalId));
      stopDeviceAuthPolling();
    });
  });

  // Copy Device Code
  dom.btnCopyDeviceCode.addEventListener('click', () => {
    const code = dom.deviceCodeVal.textContent;
    if (code && code !== '------') {
      navigator.clipboard.writeText(code);
      showToast('Код скопирован в буфер обмена!', 'success');
    }
  });

  // Submit Manual Token
  dom.btnSubmitManualToken.addEventListener('click', async () => {
    const token = dom.manualTokenInput.value.trim();
    if (!token) {
      showToast('Введите токен!', 'error');
      return;
    }

    dom.btnSubmitManualToken.disabled = true;
    try {
      const res = await fetch('/api/auth/save_token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token })
      });
      const data = await res.json();
      if (!res.ok || !data.success) throw new Error(data.error || 'Неверный токен');

      showToast(`Успешно: ${data.account}`, 'success');
      closeModal(dom.modalManual);
      loadInitialStatus();
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      dom.btnSubmitManualToken.disabled = false;
    }
  });

  // Logout Button
  if (dom.btnAuthLogout) {
    dom.btnAuthLogout.addEventListener('click', async () => {
      try {
        await fetch('/api/auth/logout', { method: 'POST' });
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

function openModal(el) {
  el.classList.add('active');
}

function closeModal(el) {
  el.classList.remove('active');
}

async function startDeviceAuthFlow() {
  dom.deviceCodeVal.textContent = '...';
  dom.devicePollStatus.textContent = 'Генерация кода устройства...';

  try {
    const res = await fetch('/api/auth/device_code', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Не удалось получить код');

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
      const res = await fetch(`/api/auth/poll_token?code=${deviceCode}`);
      const data = await res.json();

      if (data.success && data.token) {
        stopDeviceAuthPolling();
        dom.devicePollStatus.textContent = 'Успешная авторизация!';
        dom.devicePollStatus.style.color = '#00e575';
        showToast('Авторизация успешна!', 'success');
        setTimeout(() => {
          closeModal(dom.modalDevice);
          loadInitialStatus();
        }, 1200);
      } else if (data.expired) {
        stopDeviceAuthPolling();
        dom.devicePollStatus.textContent = 'Время действия кода истекло.';
      }
    } catch {
      // transient network poll errors
    }
  }, 4000);
}

function stopDeviceAuthPolling() {
  if (state.devicePollingInterval) {
    clearInterval(state.devicePollingInterval);
    state.devicePollingInterval = null;
  }
}

/* ================= 10. TOAST NOTIFICATIONS ================= */
function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  dom.toastContainer.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}
