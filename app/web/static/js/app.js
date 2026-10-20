(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  function refresh() {
    const form = $('#post-form');
    if (!form) return;
    const boxes = $$('input[name="finding_ids"]', form);
    const active = boxes.filter((b) => !b.disabled);
    $('#selected-count').textContent = active.filter((b) => b.checked).length;
    $('#post-btn').disabled = !active.some((b) => b.checked);
    $('#select-all').checked = active.length > 0 && active.every((b) => b.checked);
  }

  function refreshModules() {
    const btn = $('#review-submit');
    if (!btn) return;
    btn.disabled = !$$('input[name="categories"]:checked').length;
  }

  function applyFilters() {
    const off = new Set($$('[data-filter][aria-pressed="false"]').map((c) => c.dataset.filter));
    const offCat = new Set($$('[data-filter-cat][aria-pressed="false"]').map((c) => c.dataset.filterCat));
    $$('.finding').forEach((el) => {
      const hidden = off.has(el.dataset.sev) || offCat.has(el.dataset.cat);
      el.hidden = hidden;
      $('input[name="finding_ids"]', el).disabled = hidden;
    });
    $$('[data-group]').forEach((g) => {
      g.hidden = $$('.finding', g).every((el) => el.hidden);
    });
    refresh();
  }

  document.addEventListener('change', (e) => {
    if (e.target.id === 'select-all') {
      $$('input[name="finding_ids"]:not(:disabled)').forEach((b) => (b.checked = e.target.checked));
    }
    refresh();
    refreshModules();
  });

  document.addEventListener('click', (e) => {
    if (e.target.closest('#theme-toggle')) {
      const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem('theme', next); } catch (err) { /* storage unavailable */ }
      return;
    }
    const chip = e.target.closest('[data-filter], [data-filter-cat]');
    if (!chip) return;
    chip.setAttribute('aria-pressed', chip.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
    applyFilters();
  });

  document.addEventListener('htmx:afterSwap', refresh);
  document.addEventListener('DOMContentLoaded', () => { refresh(); refreshModules(); });
})();
