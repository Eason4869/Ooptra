/* 在样式加载前恢复主题，避免已选暗色时先闪出亮色页面。 */
'use strict';

(() => {
  const key = 'oopz.webui.theme';
  const root = document.documentElement;
  let dark = false;
  try { dark = localStorage.getItem(key) === 'dark'; } catch (_) { /* 存储不可用时仍可切换。 */ }

  function apply() {
    root.dataset.theme = dark ? 'dark' : 'light';
    document.querySelector('meta[name="color-scheme"]').content = dark ? 'dark' : 'light';
    document.querySelector('meta[name="theme-color"]').content = dark ? '#0F1824' : '#F5F8FC';
    document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
      button.setAttribute('aria-checked', String(dark));
      button.title = dark ? '切换到亮色模式' : '切换到暗色模式';
    });
  }

  apply();
  document.addEventListener('DOMContentLoaded', () => {
    apply();
    document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
      button.addEventListener('click', () => {
        dark = !dark;
        apply();
        try { localStorage.setItem(key, dark ? 'dark' : 'light'); } catch (_) { /* 保持当前页选择。 */ }
      });
    });
  });
})();
