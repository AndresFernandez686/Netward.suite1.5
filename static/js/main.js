// Netward - interacciones globales
(function () {
  var PAGE_SCROLL_KEY_PREFIX = 'nw:pageScroll:';
  var SIDEBAR_SCROLL_KEY = 'nw:sidebarScroll';
  var PENDING_SCROLL_KEY = 'nw:pendingScroll';
  var uiLockOverlay = null;
  var confirmOverlay = null;
  var confirmPendingForm = null;
  var confirmPendingSubmitter = null;

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

  function setLoadingButtonState(button, loadingText) {
    if (!button) return;
    if (!button.dataset.originalLabel) {
      button.dataset.originalLabel = button.innerHTML;
      button.dataset.originalDisabled = button.disabled ? '1' : '0';
    }
    button.disabled = true;
    button.classList.add('is-loading');
    button.textContent = loadingText || 'Cargando...';
  }

  function resetLoadingButtonStates() {
    document.querySelectorAll('[data-original-label]').forEach(function (button) {
      button.innerHTML = button.dataset.originalLabel;
      button.disabled = button.dataset.originalDisabled === '1';
      button.classList.remove('is-loading');
      delete button.dataset.originalLabel;
      delete button.dataset.originalDisabled;
    });
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
      '<div class="nw-processing-card">' +
      '<span class="nw-processing-spinner" aria-hidden="true"></span>' +
      '<strong data-lock-title>Procesando datos...</strong>' +
      '<span data-lock-subtitle>Procesando solicitud...</span>' +
      '</div>';

    Object.assign(uiLockOverlay.style, {
      position: 'fixed',
      inset: '0',
      zIndex: '10000',
      background: 'rgba(71, 85, 105, .38)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      pointerEvents: 'auto',
      backdropFilter: 'blur(2px)'
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

  function lockUi(title, subtitle) {
    var overlay = ensureUiLockOverlay();
    var titleEl = overlay.querySelector('[data-lock-title]');
    var subtitleEl = overlay.querySelector('[data-lock-subtitle]');
    if (titleEl) titleEl.textContent = title || 'Procesando datos...';
    if (subtitleEl) subtitleEl.textContent = subtitle || 'Procesando solicitud...';
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
    resetLoadingButtonStates();
  });

  function initSubmitLoading() {
    var forms = document.querySelectorAll(
      'form[data-loading-text], form[data-loading-title], form[method="post"]:not([data-no-loading])'
    );
    forms.forEach(function (form) {
      form.addEventListener('submit', function (event) {
        if (event.defaultPrevented) return;
        if (form.dataset.confirmMessage && form.dataset.confirmBypassed !== '1') return;

        var submitter = event.submitter || null;
        if (!submitter) {
          submitter = form.querySelector('button[type="submit"], input[type="submit"]');
        }

        var loadingTitle =
          (submitter && submitter.dataset.loadingTitle) ||
          form.dataset.loadingTitle ||
          (submitter && submitter.dataset.loadingText) ||
          form.dataset.loadingText;
        var action = String(form.getAttribute('action') || '').toLowerCase();
        var buttonText = String(submitter ? submitter.textContent : '').trim().toLowerCase();
        if (!loadingTitle) {
          if (action.indexOf('sincron') !== -1 || buttonText.indexOf('sincron') !== -1) {
            loadingTitle = 'Sincronizando datos...';
          } else if (action.indexOf('factura') !== -1) {
            loadingTitle = 'Procesando facturas...';
          } else if (action.indexOf('import') !== -1 || buttonText.indexOf('import') !== -1) {
            loadingTitle = 'Importando datos...';
          } else if (action.indexOf('eliminar') !== -1 || buttonText.indexOf('eliminar') !== -1) {
            loadingTitle = 'Eliminando registro...';
          } else if (buttonText.indexOf('aplicar') !== -1) {
            loadingTitle = 'Aplicando cambios...';
          } else {
            loadingTitle = 'Guardando datos...';
          }
        }
        var loadingSubtitle =
          (submitter && submitter.dataset.loadingSubtitle) ||
          form.dataset.loadingSubtitle ||
          'Procesando solicitud...';

        setLoadingButtonState(submitter, loadingTitle);
        if (form.dataset.buttonLoadingOnly !== '1') {
          lockUi(loadingTitle, loadingSubtitle);
        }
      });
    });
  }

  window.NetwardProcessing = {
    show: lockUi,
    hide: unlockUi
  };

  function ensureConfirmOverlay() {
    if (confirmOverlay) return confirmOverlay;

    confirmOverlay = document.createElement('div');
    confirmOverlay.id = 'nw-confirm-overlay';
    confirmOverlay.hidden = true;
    confirmOverlay.innerHTML =
      '<div data-confirm-dialog role="dialog" aria-modal="true" aria-labelledby="nw-confirm-title" style="width:min(480px,100%);background:#fff;border:1px solid #dbe4f0;border-radius:14px;box-shadow:0 20px 60px rgba(0,0,0,.24);padding:18px;">' +
      '<h4 id="nw-confirm-title" style="margin:0 0 10px;font-size:1.05rem;color:#0f172a;">Confirmar acción</h4>' +
      '<p data-confirm-text style="margin:0 0 14px;line-height:1.45;color:#334155;">¿Deseas continuar?</p>' +
      '<div style="display:flex;justify-content:flex-end;gap:10px;">' +
      '<button type="button" data-confirm-cancel class="btn btn--ghost">Cancelar</button>' +
      '<button type="button" data-confirm-accept class="btn btn--danger">Confirmar</button>' +
      '</div>' +
      '</div>';

    Object.assign(confirmOverlay.style, {
      position: 'fixed',
      inset: '0',
      zIndex: '10030',
      background: 'rgba(15, 23, 42, .45)',
      display: 'none',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '16px'
    });

    document.body.appendChild(confirmOverlay);

    confirmOverlay.addEventListener('click', function (event) {
      if (event.target === confirmOverlay) {
        closeConfirmOverlay();
      }
    });

    var cancelBtn = confirmOverlay.querySelector('[data-confirm-cancel]');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        var returnFocus = confirmPendingSubmitter;
        closeConfirmOverlay();
        if (returnFocus && typeof returnFocus.focus === 'function') returnFocus.focus();
      });
    }

    var acceptBtn = confirmOverlay.querySelector('[data-confirm-accept]');
    if (acceptBtn) {
      acceptBtn.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        if (acceptBtn.disabled) return;
        if (!confirmPendingForm) {
          closeConfirmOverlay();
          return;
        }

        var form = confirmPendingForm;
        var submitter = confirmPendingSubmitter;
        closeConfirmOverlay();

        form.dataset.confirmBypassed = '1';
        if (typeof form.requestSubmit === 'function') {
          form.requestSubmit(submitter || undefined);
        } else {
          form.submit();
        }
        window.setTimeout(function () {
          form.dataset.confirmBypassed = '0';
        }, 0);
      });
    }

    document.addEventListener('keydown', function (event) {
      if (!confirmOverlay || confirmOverlay.hidden) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        closeConfirmOverlay();
      }
    });

    return confirmOverlay;
  }

  function closeConfirmOverlay() {
    if (confirmOverlay) {
      confirmOverlay.hidden = true;
      confirmOverlay.style.display = 'none';
      var acceptBtn = confirmOverlay.querySelector('[data-confirm-accept]');
      if (acceptBtn) {
        acceptBtn.disabled = false;
        acceptBtn.textContent = 'Confirmar';
      }
    }
    confirmPendingForm = null;
    confirmPendingSubmitter = null;
  }

  function openConfirmOverlay(message, form, submitter) {
    var overlay = ensureConfirmOverlay();
    var textEl = overlay.querySelector('[data-confirm-text]');
    if (textEl) {
      textEl.textContent = message || '¿Deseas continuar?';
    }
    confirmPendingForm = form;
    confirmPendingSubmitter = submitter || null;
    overlay.hidden = false;
    overlay.style.display = 'flex';

    var cancelBtn = overlay.querySelector('[data-confirm-cancel]');
    var acceptBtn = overlay.querySelector('[data-confirm-accept]');
    if (acceptBtn) {
      acceptBtn.disabled = false;
      acceptBtn.textContent = 'Confirmar';
    }

    if (cancelBtn) cancelBtn.focus();
  }

  function initFormConfirm() {
    document.querySelectorAll('form[data-confirm-message]').forEach(function (form) {
      form.addEventListener('submit', function (event) {
        if (event.defaultPrevented) return;
        if (form.dataset.confirmBypassed === '1') {
          lockUi(
            form.dataset.confirmLoadingText || 'Procesando acción...',
            form.dataset.loadingSubtitle || 'Procesando solicitud...'
          );
          return;
        }

        event.preventDefault();
        openConfirmOverlay(form.dataset.confirmMessage, form, event.submitter || null);
      }, true);
    });
  }

  function showSystemNotification(message, category) {
    var main = document.querySelector('main.content');
    if (!main || !message) return;

    var stack = main.querySelector('.flash-stack[data-client-notifications]');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'flash-stack flash-stack--client';
      stack.dataset.clientNotifications = 'true';
      stack.setAttribute('aria-live', 'assertive');
      main.insertBefore(stack, main.firstChild);
    }

    stack.replaceChildren();
    var notice = document.createElement('div');
    notice.className = 'flash flash--' + (category || 'warning');
    notice.setAttribute('role', 'alert');
    notice.textContent = message;
    stack.appendChild(notice);

    window.setTimeout(function () {
      notice.style.transition = 'opacity .4s';
      notice.style.opacity = '0';
      window.setTimeout(function () {
        notice.remove();
        if (!stack.children.length) stack.remove();
      }, 400);
    }, 5000);
  }

  window.NetwardNotify = showSystemNotification;

  function initInlineValidation() {
    document.querySelectorAll('form[data-inline-validation]').forEach(function (form) {
      function fieldHost(field) {
        return field && field.closest(
          '.field, .desc-invoice-product, .desc-invoice-number, [data-validation-field]'
        );
      }

      function clearFieldError(host) {
        if (!host) return;
        host.classList.remove('has-error');
        var error = host.querySelector('.field-error-message');
        if (error) error.remove();
        var control = host.querySelector('select, input:not([type="hidden"]), textarea');
        if (control && control.validity && control.validity.valid) {
          control.setAttribute('aria-invalid', 'false');
        }
      }

      function validationMessage(field) {
        var value = String(field.value || '').trim();
        if (field.required && !value) {
          return field.dataset.requiredMessage || 'Completa este campo.';
        }
        if (field.validity && field.validity.badInput) {
          return 'Ingresa un número válido.';
        }
        if (field.validity && field.validity.stepMismatch) {
          return field.step === '1'
            ? 'Ingresa un número entero.'
            : 'Ingresa una cantidad decimal válida.';
        }
        if (field.validity && field.validity.rangeUnderflow) {
          return 'La cantidad no puede ser menor que ' + field.min + '.';
        }
        if (field.validity && field.validity.rangeOverflow) {
          return 'La cantidad no puede ser mayor que ' + field.max + '.';
        }
        return '';
      }

      function showFieldError(field, message) {
        var host = fieldHost(field) || field.parentElement;
        if (!host) return;
        clearFieldError(host);
        host.classList.add('has-error');
        field.setAttribute('aria-invalid', 'true');
        var error = document.createElement('span');
        error.className = 'field-error-message';
        error.setAttribute('role', 'alert');
        error.textContent = message;
        host.appendChild(error);
      }

      form.addEventListener('submit', function (event) {
        var firstInvalid = null;
        Array.prototype.filter.call(form.elements, function (field) {
          return field.required;
        }).forEach(function (field) {
          var message = validationMessage(field);
          if (!message && field.validity && !field.validity.valid) {
            message = 'Revisa el valor ingresado.';
          }
          if (message) {
            showFieldError(field, message);
            if (!firstInvalid) firstInvalid = field;
          } else {
            clearFieldError(fieldHost(field));
          }
        });

        if (!firstInvalid) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        showSystemNotification(
          validationMessage(firstInvalid) || 'Revisa los campos indicados.',
          'warning'
        );
        var host = fieldHost(firstInvalid);
        var focusTarget = host && host.querySelector('.combo__input, select, input:not([type="hidden"])');
        if (focusTarget) focusTarget.focus();
      }, true);

      Array.prototype.forEach.call(form.elements, function (field) {
        field.addEventListener('input', function () {
          clearFieldError(fieldHost(field));
        });
        field.addEventListener('change', function () {
          clearFieldError(fieldHost(field));
        });
      });
    });
  }

  function restoreSidebarScroll(sidebarEl) {
    if (!sidebarEl) return;
    var raw = safeGet(SIDEBAR_SCROLL_KEY);
    var y = raw == null ? null : parseInt(raw, 10);

    function ensureActiveVisible() {
      var active = sidebarEl.querySelector('.nav__link.is-active');
      if (!active) return;
      var containerRect = sidebarEl.getBoundingClientRect();
      var activeRect = active.getBoundingClientRect();
      if (activeRect.top < containerRect.top) {
        sidebarEl.scrollTop -= containerRect.top - activeRect.top + 8;
      } else if (activeRect.bottom > containerRect.bottom) {
        sidebarEl.scrollTop += activeRect.bottom - containerRect.bottom + 8;
      }
    }

    requestAnimationFrame(function () {
      if (y !== null && !isNaN(y)) sidebarEl.scrollTop = y;
      ensureActiveVisible();
      // Esperar fuentes y SVG para estabilizar la altura definitiva del menú.
      setTimeout(function () {
        if (y !== null && !isNaN(y)) sidebarEl.scrollTop = y;
        ensureActiveVisible();
      }, 80);
    });
  }

  // Menu lateral en moviles
  var toggle = document.getElementById('menuToggle');
  var sidebar = document.getElementById('sidebar');
  // En escritorio el elemento desplazable real es el nav, no el aside.
  var sidebarScroll = sidebar ? (sidebar.querySelector('.sidebar__nav') || sidebar) : null;
  var backdrop = document.getElementById('backdrop');

  function closeMenu() {
    if (sidebar) sidebar.classList.remove('is-open');
    if (backdrop) backdrop.classList.remove('is-open');
  }

  if (toggle && sidebar && backdrop) {
    toggle.addEventListener('click', function () {
      sidebar.classList.toggle('is-open');
      backdrop.classList.toggle('is-open');
      restoreSidebarScroll(sidebarScroll);
    });
    backdrop.addEventListener('click', closeMenu);
  }

  restorePageScroll();
  restoreSidebarScroll(sidebarScroll);

  if (sidebarScroll) {
    sidebarScroll.addEventListener('scroll', function () {
      saveSidebarScroll(sidebarScroll);
    }, { passive: true });
  }

  window.addEventListener('scroll', function () {
    savePageScroll();
  }, { passive: true });

  window.addEventListener('beforeunload', function () {
    savePageScroll();
    saveSidebarScroll(sidebarScroll);
  });

  document.querySelectorAll('.nav__link').forEach(function (link) {
    link.addEventListener('click', function () {
      savePageScroll();
      saveSidebarScroll(sidebarScroll);
    });
  });

  document.querySelectorAll('form[method="post"], form[method="POST"]').forEach(function (form) {
    form.addEventListener('submit', function () {
      var payload = {
        path: window.location.pathname,
        x: window.scrollX || 0,
        y: window.scrollY || 0,
        sidebarY: sidebarScroll ? (sidebarScroll.scrollTop || 0) : 0,
        ts: Date.now(),
      };
      safeSet(PENDING_SCROLL_KEY, JSON.stringify(payload));
      savePageScroll();
      saveSidebarScroll(sidebarScroll);
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
  // La validación debe registrarse primero para que un formulario incompleto
  // pueda cancelar el envío antes de mostrar el bloqueo de procesamiento.
  initInlineValidation();
  initSubmitLoading();
  initFormConfirm();

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
    return String(s || '')
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[^a-z0-9]+/g, ' ')
      .trim();
  }

  function searchScore(productName, query) {
    var product = norm(productName);
    var searched = norm(query);
    if (!searched) return 0;

    var productWords = product.split(/\s+/).filter(Boolean);
    var rawQueryWords = searched.split(/\s+/).filter(Boolean);
    var connectors = {
      a: true, al: true, de: true, del: true, el: true, la: true,
      las: true, los: true, un: true, una: true, y: true, e: true,
      con: true, x: true, and: true
    };
    var meaningfulWords = rawQueryWords.filter(function (word) {
      return word.length > 1 && !connectors[word];
    });
    var queryWords = meaningfulWords.length ? meaningfulWords : rawQueryWords;
    var wordScore = 0;
    var everyWordMatches = queryWords.every(function (queryWord) {
      var best = Infinity;
      productWords.forEach(function (productWord) {
        if (productWord === queryWord) best = Math.min(best, 0);
        else if (productWord.indexOf(queryWord) === 0 ||
                 (productWord.length >= 3 && queryWord.indexOf(productWord) === 0)) {
          best = Math.min(best, 1);
        }
        else if (productWord.indexOf(queryWord) !== -1) best = Math.min(best, 2);
      });
      if (!isFinite(best)) return false;
      wordScore += best;
      return true;
    });

    if (!everyWordMatches) return -1;
    if (product === searched) return wordScore;
    if (product.indexOf(searched) === 0) return 10 + wordScore;
    if (product.indexOf(searched) !== -1) return 20 + wordScore;
    return 30 + wordScore;
  }

  function initCombo(combo) {
    var input   = combo.querySelector('.combo__input');
    var hidden  = combo.querySelector('.combo__value');
    var hidCat  = combo.querySelector('.combo__cat');
    var list    = combo.querySelector('.combo__list');
    var empty   = combo.querySelector('.combo__empty');
    var clear   = combo.querySelector('.combo__clear');
    var options = Array.prototype.slice.call(combo.querySelectorAll('.combo__option'));
    options.forEach(function (option, index) { option._comboOrder = index; });
    var minChars = Math.max(0, parseInt(combo.dataset.minChars || '0', 10) || 0);
    var maxResults = Math.max(0, parseInt(combo.dataset.maxResults || '0', 10) || 0);
    var categorySelect = combo.dataset.categorySelect
      ? document.querySelector(combo.dataset.categorySelect)
      : null;
    var control = combo.querySelector('.combo__control');
    var positionFrame = null;

    if (!input || !list || !control) return;

    function positionList(el) {
      var rect = control.getBoundingClientRect();
      el.style.top   = (rect.bottom + 4) + 'px';
      el.style.left  = rect.left + 'px';
      el.style.width = rect.width + 'px';
    }

    function repositionOpenList() {
      positionFrame = null;
      if (list.hidden && (!empty || empty.hidden)) return;
      var rect = control.getBoundingClientRect();
      var outsideViewport = rect.bottom <= 0 || rect.top >= window.innerHeight ||
        rect.right <= 0 || rect.left >= window.innerWidth;
      if (outsideViewport) {
        close();
        return;
      }
      if (!list.hidden) positionList(list);
      if (empty && !empty.hidden) positionList(empty);
    }

    function scheduleReposition() {
      if (positionFrame !== null || (list.hidden && (!empty || empty.hidden))) return;
      positionFrame = window.requestAnimationFrame(repositionOpenList);
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
      var waitingForQuery = q.length < minChars;
      var matches = [];
      options.forEach(function (o) {
        var categoryMatch = !categorySelect || !categorySelect.value || o.dataset.cat === categorySelect.value;
        var searchable = o.dataset.search || o.dataset.display || o.dataset.value;
        var score = !waitingForQuery && categoryMatch ? searchScore(searchable, q) : -1;
        o.hidden = true;
        if (score >= 0) matches.push({ option: o, score: score });
      });
      matches.sort(function (a, b) {
        return a.score - b.score || a.option._comboOrder - b.option._comboOrder;
      });
      if (maxResults) matches = matches.slice(0, maxResults);
      matches.forEach(function (match) {
        match.option.hidden = false;
        list.appendChild(match.option);
      });
      anyVisible = matches.length > 0;
      if (empty) {
        if (!anyVisible) positionList(empty);
        empty.textContent = waitingForQuery
          ? (empty.dataset.prompt || 'Escribe para buscar.')
          : (empty.dataset.noResults || 'Sin resultados.');
        empty.hidden = anyVisible;
      }
      options.forEach(function (o) { o.classList.remove('is-active'); });
      open();
    }
    function select(opt) {
      hidden.value = opt.dataset.value;
      hidden.dispatchEvent(new Event('input', { bubbles: true }));
      hidden.dispatchEvent(new Event('change', { bubbles: true }));
      if (hidCat) hidCat.value = opt.dataset.cat || '';
      if (categorySelect && opt.dataset.cat) {
        categorySelect.value = opt.dataset.cat;
        categorySelect.dispatchEvent(new Event('change', { bubbles: true }));
      }
      input.value = opt.dataset.display || opt.dataset.value;
      if (clear) clear.hidden = false;
      combo.classList.add('has-value');
      close();
    }

    input.addEventListener('focus', filter);
    input.addEventListener('input', function () {
      hidden.value = '';
      hidden.dispatchEvent(new Event('input', { bubbles: true }));
      hidden.dispatchEvent(new Event('change', { bubbles: true }));
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
        hidden.dispatchEvent(new Event('input', { bubbles: true }));
        hidden.dispatchEvent(new Event('change', { bubbles: true }));
        combo.classList.remove('has-value');
        options.forEach(function (o) { o.hidden = false; });
        input.focus();
      });
    }
    if (categorySelect) {
      categorySelect.addEventListener('change', function () {
        var selected = options.find(function (o) { return o.dataset.value === hidden.value; });
        if (selected && categorySelect.value && selected.dataset.cat !== categorySelect.value) {
          hidden.value = '';
          input.value = '';
          if (hidCat) hidCat.value = '';
          if (clear) clear.hidden = true;
          combo.classList.remove('has-value');
        }
        if (!list.hidden || document.activeElement === input) filter();
      });
    }
    document.addEventListener('click', function (e) {
      if (!combo.contains(e.target)) close();
    });
    document.addEventListener('scroll', scheduleReposition, true);
    window.addEventListener('resize', scheduleReposition);
  }

  // Inicializar todos los combos presentes en la página
  document.querySelectorAll('[data-combo]').forEach(initCombo);
})();

/* Estados asíncronos compartidos. Nunca inserta HTML recibido del servidor. */
(function () {
  var toast;

  function stateElement(kind, title, detail, retry) {
    var region = document.createElement('div');
    region.className = 'nw-state-region nw-state-region--' + kind;
    region.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    region.setAttribute('aria-live', kind === 'error' ? 'assertive' : 'polite');

    var mark = document.createElement('span');
    mark.className = 'nw-state-region__mark';
    mark.setAttribute('aria-hidden', 'true');
    mark.textContent = kind === 'error' ? '!' : (kind === 'loading' ? '' : '—');
    if (kind === 'loading') {
      var spinner = document.createElement('span');
      spinner.className = 'nw-inline-spinner';
      mark.appendChild(spinner);
    }

    var body = document.createElement('div');
    body.className = 'nw-state-region__body';
    var heading = document.createElement('strong');
    heading.textContent = String(title || 'Estado del sistema');
    body.appendChild(heading);
    if (detail) {
      var copy = document.createElement('p');
      copy.textContent = String(detail);
      body.appendChild(copy);
    }
    if (typeof retry === 'function') {
      var actions = document.createElement('div');
      actions.className = 'nw-state-region__actions';
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn--secondary btn--sm';
      button.textContent = 'Reintentar';
      button.addEventListener('click', function () {
        region.remove();
        retry();
      });
      actions.appendChild(button);
      body.appendChild(actions);
    }
    region.append(mark, body);
    return region;
  }

  function showError(message, retry) {
    if (toast) toast.remove();
    toast = stateElement(
      'error',
      'No pudimos completar la operación',
      message || 'Revisa tu conexión e inténtalo nuevamente.',
      retry
    );
    toast.classList.add('nw-state-toast');
    document.body.appendChild(toast);
    return toast;
  }

  function setRegion(region, kind, title, detail, retry) {
    if (!region) return null;
    region.setAttribute('aria-busy', kind === 'loading' ? 'true' : 'false');
    var state = stateElement(kind, title, detail, retry);
    region.replaceChildren(state);
    return state;
  }

  function enhanceEmptyStates() {
    var emptyPattern = /^(no hay|sin (datos|registros|resultados|movimientos|productos|notificaciones)|todav[ií]a no hay)/i;
    document.querySelectorAll('tbody tr, p, .empty-state, [data-empty-state]').forEach(function (candidate) {
      if (candidate.dataset.nwStateReady === 'true') return;
      var text = (candidate.textContent || '').trim().replace(/\s+/g, ' ');
      if (!emptyPattern.test(text)) return;
      var target = candidate.matches('tr') ? candidate.querySelector('td') : candidate;
      if (!target) return;
      candidate.dataset.nwStateReady = 'true';
      if (candidate.matches('tr')) target.classList.add('nw-state-cell');
      var state = stateElement('empty', 'Nada para mostrar por ahora', text, null);
      state.classList.add('nw-state-region--compact');
      target.replaceChildren(state);
    });
  }

  window.NetwardUI = {
    showError: showError,
    setRegion: setRegion,
    stateElement: stateElement,
    clearError: function () { if (toast) toast.remove(); toast = null; }
  };

  document.querySelectorAll('[data-retry-page]').forEach(function (button) {
    button.addEventListener('click', function () { window.location.reload(); });
  });
  document.querySelectorAll('[data-go-back]').forEach(function (button) {
    button.addEventListener('click', function () {
      if (window.history.length > 1) window.history.back();
      else window.location.assign('/');
    });
  });
  enhanceEmptyStates();
  window.addEventListener('offline', function () {
    showError('Se perdió la conexión. Tus filtros y datos ingresados se conservarán.', function () {
      window.location.reload();
    });
  });
})();
