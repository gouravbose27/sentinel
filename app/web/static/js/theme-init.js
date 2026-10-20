(() => {
  let theme = 'light';
  try { theme = localStorage.getItem('theme') === 'light' ? 'light' : 'dark'; } catch (e) { /* storage unavailable */ }
  document.documentElement.dataset.theme = theme;
})();
