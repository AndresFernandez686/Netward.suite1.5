// Netward - interacciones globales
(function () {
  var PAGE_SCROLL_KEY_PREFIX = 'nw:pageScroll:';
  var SIDEBAR_SCROLL_KEY = 'nw:sidebarScroll';
  var PENDING_SCROLL_KEY = 'nw:pendingScroll';
  var uiLockOverlay = null;

  function getPageKey() {
    return window.location.pathname + window.location.search;
  }

  function safeSet(key, value) {
    try {
      sessionStorage.setItem(key, value);
    } catch (e) {}
  }

  function safeGet(key) {
    try {
      return sessionStorage.getItem(key);
    } catch (e) {
      return null;
    }
  }

  function safeRemove(key) {
    try {
      sessionStorage.removeItem(key);
    } catch (e) {}
  }

  function savePageScroll() {
    var payload = JSON.stringify({ x: window.scrollX || 0, y: window.scrollY || 0 });
    safeSet(PAGE_SCROLL_KEY_PREFIX + getPageKey(), payload);
  }

  function restorePageScroll() {
    var rawPending = safeGet(PENDING_SCROLL_KEY);
    var pending = null;
    if (rawPending) {
      try {
        pending = JSON.parse(rawPending);
      } catch (e) {
        pending = null;
      }
      if (pending && typeof pending.ts === 'number' && (Date.now() - pending.ts) > 15000) {
        pending = null;
      }
      if (!pending || pending.path !== window.location.pathname) {
        pending = null;
      }
      safeRemove(PENDING_SCROLL_KEY);
    }

    var rawPage = safeGet(PAGE_SCROLL_KEY_PREFIX + getPageKey());
    var page = null;
    if (rawPage) {
      try {
        page = JSON.parse(rawPage);
      } catch (e) {
        page = null;
      }
    }

    var target = pending || page;
    if (!target || typeof target.y !== 'number') {
      return;
    }

    requestAnimationFrame(function () {
      window.scrollTo(target.x || 0, target.y || 0);
      setTimeout(function () {
        window.scrollTo(target.x || 0, target.y || 0);
      }, 0);
    });
  }

  function saveSidebarScroll(sidebarEl) {
    if (!sidebarEl) return;
    safeSet(SIDEBAR_SCROLL_KEY, String(sidebarEl.scrollTop || 0));
  }

  function parseDelayMs(value) {
    var n = parseInt(String(value || ''), 10);
    if (isNaN(n) || n < 0) return 0;
    return n;
  }

  function setLoadingButtonState(button, loadingText) {
    if (!button) return;
    if (!button.dataset.originalLabel) {
      button.dataset.originalLabel = button.innerHTML;
    }
    button.disabled = true;
    button.classList.add('is-loading');
    button.textContent = loadingText || 'Cargando...';
  }

  function ensureUiLockOverlay() {
    if (uiLockOverlay) return uiLockOverlay;

    uiLockOverlay = document.createElement('div');
    uiLockOverlay.id = 'nw-ui-lock';
    uiLockOverlay.setAttribute('role', 'alert');
    uiLockOverlay.setAttribute('aria-live', 'assertive');
    uiLockOverlay.tabIndex = -1;
    uiLockOverlay.hidden = true;

    uiLockOverlay.innerHTML =
      '<div style="text-align:center;padding:18px 20px;border-radius:12px;background:#111827;color:#fff;box-shadow:0 12px 36px rgba(0,0,0,.35);min-width:220px;max-width:90vw;">' +
      '<div style="font-weight:700;font-size:1rem;margin-bottom:6px;">Procesando</div>' +
      '<div data-lock-text style="font-size:.9rem;opacity:.92;">Estamos guardando tus cambios</div>' +
      '</div>';

    Object.assign(uiLockOverlay.style, {
      position: 'fixed',
      inset: '0',
      zIndex: '10000',
      background: 'rgba(15, 23, 42, .45)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      pointerEvents: 'auto',
      backdropFilter: 'blur(1px)'
    });

    uiLockOverlay.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
    });

    document.body.appendChild(uiLockOverlay);
    return uiLockOverlay;
  }

  function isUiLocked() {
    return document.body.classList.contains('nw-ui-locked');
  }

  function lockUi(message) {
    var overlay = ensureUiLockOverlay();
    var textEl = overlay.querySelector('[data-lock-text]');
    if (textEl) {
      textEl.textContent = message || 'Estamos guardando tus cambios';
    }
    overlay.hidden = false;
    document.body.classList.add('nw-ui-locked');
    document.body.setAttribute('aria-busy', 'true');
    document.body.style.cursor = 'wait';
    overlay.focus();
  }

  function unlockUi() {
    if (uiLockOverlay) {
      uiLockOverlay.hidden = true;
    }
    document.body.classList.remove('nw-ui-locked');
    document.body.removeAttribute('aria-busy');
    document.body.style.cursor = '';
  }

  function blockWhileLocked(e) {
    if (!isUiLocked()) return;
    if (uiLockOverlay && uiLockOverlay.contains(e.target)) {
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    e.preventDefault();
    e.stopPropagation();
  }

  document.addEventListener('click', blockWhileLocked, true);
  document.addEventListener('pointerdown', blockWhileLocked, true);
  document.addEventListener('touchstart', blockWhileLocked, true);
  document.addEventListener('keydown', function (e) {
    if (!isUiLocked()) return;
    // Permitir recarga manual (F5 / Ctrl+R) si se necesita.
    if (e.key === 'F5' || ((e.ctrlKey || e.metaKey) && (e.key === 'r' || e.key === 'R'))) {
      return;
    }
    e.preventDefault();
    e.stopPropagation();
  }, true);

  window.addEventListener('pageshow', function () {
    unlockUi();
  });

  function initTimedSubmit() {
    document.querySelectorAll('form[data-submit-delay]').forEach(function (form) {
      form.addEventListener('submit', function (event) {
        if (event.defaultPrevented) return;
        if (form.dataset.delayBypassed === '1') return;

        var delayMs = parseDelayMs(form.dataset.submitDelay);
        if (delayMs <= 0) return;

        event.preventDefault();

        var submitter = event.submitter || null;
        if (!submitter) {
          submitter = form.querySelector('button[type="submit"], input[type="submit"]');
        }

        var loadingText =
          (submitter && submitter.dataset.loadingText) ||
          form.dataset.loadingText ||
          'Cargando...';

        setLoadingButtonState(submitter, loadingText);
        lockUi(loadingText);

        window.setTimeout(function () {
          try {
            form.dataset.delayBypassed = '1';
            if (typeof form.requestSubmit === 'function') {
              form.requestSubmit();
            } else {
              form.submit();
            }
            window.setTimeout(function () {
              form.dataset.delayBypassed = '0';
            }, 0);
          } catch (err) {
            unlockUi();
            throw err;
          }
        }, delayMs);
      });
    });
  }

  function restoreSidebarScroll(sidebarEl) {
    if (!sidebarEl) return;
    var raw = safeGet(SIDEBAR_SCROLL_KEY);
    if (raw == null) return;
    var y = parseInt(raw, 10);
    if (!isNaN(y)) {
      sidebarEl.scrollTop = y;
    }
  }

  // Menu lateral en moviles
  var toggle = document.getElementById('menuToggle');
  var sidebar = document.getElementById('sidebar');
  var backdrop = document.getElementById('backdrop');

  function closeMenu() {
    if (sidebar) sidebar.classList.remove('is-open');
    if (backdrop) backdrop.classList.remove('is-open');
  }

  if (toggle && sidebar && backdrop) {
    toggle.addEventListener('click', function () {
      sidebar.classList.toggle('is-open');
      backdrop.classList.toggle('is-open');
      restoreSidebarScroll(sidebar);
    });
    backdrop.addEventListener('click', closeMenu);
  }

  restorePageScroll();
  restoreSidebarScroll(sidebar);

  if (sidebar) {
    sidebar.addEventListener('scroll', function () {
      saveSidebarScroll(sidebar);
    }, { passive: true });
  }

  window.addEventListener('scroll', function () {
    savePageScroll();
  }, { passive: true });

  window.addEventListener('beforeunload', function () {
    savePageScroll();
    saveSidebarScroll(sidebar);
  });

  document.querySelectorAll('.nav__link').forEach(function (link) {
    link.addEventListener('click', function () {
      savePageScroll();
      saveSidebarScroll(sidebar);
    });
  });

  document.querySelectorAll('form[method="post"], form[method="POST"]').forEach(function (form) {
    form.addEventListener('submit', function () {
      var payload = {
        path: window.location.pathname,
        x: window.scrollX || 0,
        y: window.scrollY || 0,
        sidebarY: sidebar ? (sidebar.scrollTop || 0) : 0,
        ts: Date.now(),
      };
      safeSet(PENDING_SCROLL_KEY, JSON.stringify(payload));
      savePageScroll();
      saveSidebarScroll(sidebar);
    });
  });

  function initCollapsibleCards() {
    document.querySelectorAll('.card').forEach(function (card) {
      if (card.dataset.collapsibleInitialized === 'true' || card.classList.contains('card--skip-collapse')) {
        return;
      }

      card.dataset.collapsibleInitialized = 'true';
      var titleEl = card.querySelector('h1, h2, h3, h4, h5, .panel__title, .card__title');
      var titleText = titleEl ? titleEl.textContent.trim() : 'Detalles';

      var toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'card__toggle';
      toggle.innerHTML = '<span class="card__toggle-title">' + titleText + '</span><span class="card__toggle-icon">▾</span>';
      toggle.setAttribute('aria-expanded', card.classList.contains('is-collapsed') || card.hasAttribute('data-collapsed') ? 'false' : 'true');

      var body = document.createElement('div');
      body.className = 'card__body';

      Array.prototype.slice.call(card.childNodes).forEach(function (node) {
        if (node === titleEl) {
          return;
        }
        if (node.nodeType === 1 && node.classList && node.classList.contains('card__toggle')) {
          return;
        }
        body.appendChild(node);
      });

      card.classList.add('card--collapsible');
      card.insertBefore(toggle, card.firstChild);
      card.appendChild(body);

      if (card.classList.contains('is-collapsed') || card.hasAttribute('data-collapsed')) {
        card.classList.add('is-collapsed');
        body.hidden = true;
      } else {
        card.classList.remove('is-collapsed');
        body.hidden = false;
      }

      toggle.addEventListener('click', function () {
        var collapsed = card.classList.toggle('is-collapsed');
        body.hidden = collapsed;
        toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      });
    });
  }

  initCollapsibleCards();
  initTimedSubmit();

  // Auto-ocultar mensajes flash despues de 5s
  setTimeout(function () {
    document.querySelectorAll('.flash').forEach(function (f) {
      f.style.transition = 'opacity .4s';
      f.style.opacity = '0';
      setTimeout(function () { f.remove(); }, 400);
    });
  }, 5000);
})();

/* ==========================================================================
   Combobox de búsqueda de productos — reutilizable en todas las páginas
   Uso: <div class="field combo" data-combo> ... </div>
   ========================================================================== */
(function () {
  function norm(s) {
    return s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  }

  function matchesSearch(productName, query) {
    if (!query) return true;
    var pn = norm(productName), q = norm(query);
    if (pn.indexOf(q) !== -1) return true;
    return pn.split(/[\s\-\/,()]+/).filter(Boolean).some(function (w) {
      return w.indexOf(q) === 0;
    });
  }

  function initCombo(combo) {
    var input   = combo.querySelector('.combo__input');
    var hidden  = combo.querySelector('.combo__value');
    var hidCat  = combo.querySelector('.combo__cat');
    var list    = combo.querySelector('.combo__list');
    var empty   = combo.querySelector('.combo__empty');
    var clear   = combo.querySelector('.combo__clear');
    var options = Array.prototype.slice.call(combo.querySelectorAll('.combo__option'));

    if (!input || !list) return;

    function positionList(el) {
      var rect = combo.querySelector('.combo__control').getBoundingClientRect();
      el.style.top   = (rect.bottom + 4) + 'px';
      el.style.left  = rect.left + 'px';
      el.style.width = rect.width + 'px';
    }

    function open() {
      positionList(list);
      list.hidden = false;
      input.setAttribute('aria-expanded', 'true');
    }
    function close() {
      list.hidden = true;
      if (empty) empty.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      options.forEach(function (o) { o.classList.remove('is-active'); });
    }
    function filter() {
      var q = input.value.trim(), anyVisible = false;
      options.forEach(function (o) {
        var match = matchesSearch(o.dataset.value, q);
        o.hidden = !match;
        if (match) anyVisible = true;
      });
      if (empty) {
        if (!anyVisible) positionList(empty);
        empty.hidden = anyVisible;
      }
      options.forEach(function (o) { o.classList.remove('is-active'); });
      open();
    }
    function select(opt) {
      hidden.value = opt.dataset.value;
      if (hidCat) hidCat.value = opt.dataset.cat || '';
      input.value = opt.dataset.display || opt.dataset.value;
      if (clear) clear.hidden = false;
      combo.classList.add('has-value');
      close();
    }

    input.addEventListener('focus', filter);
    input.addEventListener('input', function () {
      hidden.value = '';
      combo.classList.remove('has-value');
      if (clear) clear.hidden = input.value === '';
      filter();
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { close(); return; }
      if (e.key === 'Enter') {
        var a = combo.querySelector('.combo__option.is-active');
        if (a) { e.preventDefault(); select(a); }
        return;
      }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        var vis = options.filter(function (o) { return !o.hidden; });
        var cur = vis.indexOf(combo.querySelector('.combo__option.is-active'));
        var nxt = e.key === 'ArrowDown' ? (cur + 1) % vis.length : (cur - 1 + vis.length) % vis.length;
        options.forEach(function (o) { o.classList.remove('is-active'); });
        if (vis[nxt]) { vis[nxt].classList.add('is-active'); vis[nxt].scrollIntoView({ block: 'nearest' }); }
      }
    });
    options.forEach(function (o) {
      o.addEventListener('mousedown', function (e) { e.preventDefault(); select(o); });
    });
    if (clear) {
      clear.addEventListener('click', function () {
        hidden.value = ''; input.value = ''; clear.hidden = true;
        combo.classList.remove('has-value');
        options.forEach(function (o) { o.hidden = false; });
        input.focus();
      });
    }
    document.addEventListener('click', function (e) {
      if (!combo.contains(e.target)) close();
    });
  }

  // Inicializar todos los combos presentes en la página
  document.querySelectorAll('[data-combo]').forEach(initCombo);
})();
