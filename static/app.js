// Live search + filters for the admin grid; copy buttons.
(function () {
  const form = document.getElementById('filters');
  if (form) {
    const body = document.getElementById('rows');
    const count = document.getElementById('count');
    let timer, ctl;
    const qs = () => new URLSearchParams(new FormData(form)).toString();
    const refreshLinks = () => document.querySelectorAll('[data-export]').forEach(a => a.href = a.dataset.export + '?' + qs());
    async function load() {
      if (ctl) ctl.abort(); ctl = new AbortController();
      body.classList.add('loading');
      try {
        const r = await fetch('/admin/members?partial=1&' + qs(), {signal: ctl.signal});
        if (!r.ok) throw new Error();
        body.innerHTML = await r.text();
        count.textContent = body.querySelector('tr[data-total]')?.dataset.total ?? '';
      } catch (e) { if (e.name !== 'AbortError') body.innerHTML = '<tr><td colspan="8" class="empty">Could not load members. Try again.</td></tr>'; }
      body.classList.remove('loading'); refreshLinks();
    }
    form.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(load, 200); });
    form.addEventListener('submit', e => { e.preventDefault(); load(); });
    refreshLinks();
  }
  document.querySelectorAll('[data-copy]').forEach(b => b.addEventListener('click', () => {
    navigator.clipboard.writeText(b.dataset.copy).then(() => { const t = b.innerHTML; b.textContent = 'Copied'; setTimeout(() => b.innerHTML = t, 1200); });
  }));
  document.querySelectorAll('form[data-busy]').forEach(f => f.addEventListener('submit', () => {
    const b = f.querySelector('button[type=submit],button:not([type])'); if (b) { b.disabled = true; b.textContent = 'Please wait...'; }
  }));
})();
