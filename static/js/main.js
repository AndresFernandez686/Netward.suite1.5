// Netward - interacciones globales
(function () {
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
    });
    backdrop.addEventListener('click', closeMenu);
  }

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
