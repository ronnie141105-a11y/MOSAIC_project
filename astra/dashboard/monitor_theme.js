/* One preference shared by the airport and TMA browser monitors. */
(() => {
  const key = 'astra-monitor-theme';
  const button = document.getElementById('theme-toggle');
  const saved = () => {
    try { return localStorage.getItem(key); } catch (_) { return null; }
  };
  const apply = (value) => {
    const theme = value === 'light' || value === 'dark' ? value :
      'dark';
    document.documentElement.dataset.theme = theme;
    if (button) {
      button.textContent = theme === 'dark' ? '☾ Night' : '☀ Day';
      button.setAttribute('aria-label', `Display theme: ${theme}. Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`);
      button.setAttribute('aria-pressed', String(theme === 'dark'));
    }
    window.dispatchEvent(new Event('astra-theme-change'));
  };
  apply(saved());
  button?.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(key, next); } catch (_) { /* private browsing */ }
    apply(next);
  });
  window.addEventListener('storage', (event) => { if (event.key === key) apply(event.newValue); });
  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
    if (!saved()) apply(null);
  });
})();
