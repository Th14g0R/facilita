'use strict';

// ============================================================================
// Alternador de Tema Claro e Escuro (Asaas & Conta Azul)
// ============================================================================
const THEME_STORAGE_KEY = 'facilita_theme';

function getSystemTheme() {
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function getActiveTheme() {
  return document.documentElement.getAttribute('data-theme') || getSystemTheme();
}

function updateThemeButtonState(btn, theme) {
  if (!btn) return;
  const isDark = theme === 'dark';
  btn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
  btn.setAttribute('title', isDark ? 'Alternar para Modo Claro' : 'Alternar para Modo Escuro');
  const label = btn.querySelector('.theme-label');
  if (label) {
    label.textContent = isDark ? 'Modo Escuro' : 'Modo Claro';
  }
}

function setTheme(theme) {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch (e) {}

  document.documentElement.setAttribute('data-theme', theme);
  const btn = document.getElementById('btnThemeToggle');
  updateThemeButtonState(btn, theme);
}

function initTheme() {
  const savedTheme = localStorage.getItem(THEME_STORAGE_KEY);
  const activeTheme = savedTheme || getSystemTheme();
  if (savedTheme) {
    document.documentElement.setAttribute('data-theme', savedTheme);
  }

  const btn = document.getElementById('btnThemeToggle');
  if (btn) {
    updateThemeButtonState(btn, activeTheme);
    btn.addEventListener('click', () => {
      const current = getActiveTheme();
      const next = current === 'dark' ? 'light' : 'dark';
      setTheme(next);
    });
  }

  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
      if (!localStorage.getItem(THEME_STORAGE_KEY)) {
        updateThemeButtonState(btn, e.matches ? 'dark' : 'light');
      }
    });
  }
}

// ============================================================================
// Modo Privacidade (Ocultar / Exibir Valores na Tela)
// ============================================================================
const PRIVACY_STORAGE_KEY = 'emprestimo_privacy_mode';

function isPrivacyEnabled() {
  try {
    return localStorage.getItem(PRIVACY_STORAGE_KEY) === 'true';
  } catch (e) {
    return false;
  }
}

function updatePrivacyButtonState(btn, isPrivate) {
  if (!btn) return;
  btn.setAttribute('aria-pressed', isPrivate ? 'true' : 'false');
  btn.setAttribute('aria-label', isPrivate ? 'Exibir valores da tela' : 'Ocultar valores da tela');
  btn.setAttribute('title', isPrivate ? 'Exibir valores (Modo Privacidade ativo)' : 'Ocultar valores na tela (Modo Privacidade)');
  
  const label = btn.querySelector('.privacy-label');
  if (label) {
    label.textContent = isPrivate ? 'Exibir valores' : 'Ocultar valores';
  }
}

function setPrivacyMode(enabled) {
  try {
    localStorage.setItem(PRIVACY_STORAGE_KEY, enabled ? 'true' : 'false');
  } catch (e) {}

  if (enabled) {
    document.documentElement.setAttribute('data-privacy-mode', 'true');
  } else {
    document.documentElement.removeAttribute('data-privacy-mode');
  }

  const btn = document.getElementById('btnPrivacyToggle');
  updatePrivacyButtonState(btn, enabled);
}

function initPrivacyMode() {
  const currentEnabled = isPrivacyEnabled();
  if (currentEnabled) {
    document.documentElement.setAttribute('data-privacy-mode', 'true');
  }

  const btn = document.getElementById('btnPrivacyToggle');
  if (btn) {
    updatePrivacyButtonState(btn, currentEnabled);
    btn.addEventListener('click', () => {
      const willEnable = !isPrivacyEnabled();
      setPrivacyMode(willEnable);
    });
  }

  // Atalho de teclado opcional (Alt + P ou Ctrl + Shift + P) para alternar privacidade rapidamente
  document.addEventListener('keydown', (event) => {
    if (event.altKey && (event.key === 'p' || event.key === 'P')) {
      const targetTag = event.target ? event.target.tagName : '';
      if (targetTag !== 'INPUT' && targetTag !== 'TEXTAREA') {
        event.preventDefault();
        setPrivacyMode(!isPrivacyEnabled());
      }
    }
  });

  // Proteção para valores monetários soltos no conteúdo textual (ex: parágrafos e resumos)
  protectMonetaryTextNodes();

  // Espiada temporária ao tocar em telas mobile
  document.addEventListener('click', (event) => {
    if (!isPrivacyEnabled()) return;
    const target = event.target.closest('.priv-val, td.money, .metric strong, .chart-value, .callout strong');
    if (target) {
      target.classList.add('peek-revealed');
      setTimeout(() => {
        target.classList.remove('peek-revealed');
      }, 2500);
    }
  });
}

// Encontra ocorrências monetárias no texto (ex: R$ 1.500,00) fora de tags protegidas e envolve com span.priv-val
function protectMonetaryTextNodes() {
  const moneyRegex = /(R\$\s*[\d\.,]+)/g;
  const contentArea = document.querySelector('.content');
  if (!contentArea) return;

  const walker = document.createTreeWalker(
    contentArea,
    NodeFilter.SHOW_TEXT,
    {
      acceptNode(node) {
        if (!node.nodeValue || !moneyRegex.test(node.nodeValue)) {
          return NodeFilter.FILTER_REJECT;
        }
        const parent = node.parentElement;
        if (!parent) return NodeFilter.FILTER_REJECT;
        const tag = parent.tagName;
        if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'TEXTAREA' || tag === 'INPUT' || tag === 'SELECT') {
          return NodeFilter.FILTER_REJECT;
        }
        if (parent.closest('.priv-val, td.money, th.money, .metric strong, .chart-value')) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    }
  );

  const nodesToWrap = [];
  while (walker.nextNode()) {
    nodesToWrap.push(walker.currentNode);
  }

  nodesToWrap.forEach(node => {
    const parent = node.parentNode;
    if (!parent) return;
    const text = node.nodeValue;
    const parts = text.split(/(R\$\s*[\d\.,]+)/g);
    if (parts.length <= 1) return;

    const fragment = document.createDocumentFragment();
    parts.forEach(part => {
      if (/^R\$\s*[\d\.,]+$/.test(part)) {
        const span = document.createElement('span');
        span.className = 'priv-val';
        span.textContent = part;
        span.setAttribute('title', 'Passe o cursor para espiar o valor');
        fragment.appendChild(span);
      } else if (part) {
        fragment.appendChild(document.createTextNode(part));
      }
    });
    parent.replaceChild(fragment, node);
  });
}

// ============================================================================
// Controle de Exibição / Recolhimento da Barra Lateral (Sidebar)
// ============================================================================
const SIDEBAR_STORAGE_KEY = 'facilita_sidebar_collapsed';

function isSidebarCollapsed() {
  return document.documentElement.getAttribute('data-sidebar-collapsed') === 'true';
}

function setSidebarCollapsed(collapsed) {
  try {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, collapsed ? 'true' : 'false');
  } catch (e) {}

  if (collapsed) {
    document.documentElement.setAttribute('data-sidebar-collapsed', 'true');
  } else {
    document.documentElement.removeAttribute('data-sidebar-collapsed');
  }

  updateSidebarToggleButtons(collapsed);
}

function updateSidebarToggleButtons(collapsed) {
  const btnSidebar = document.getElementById('btnSidebarToggle');
  const btnTopbar = document.getElementById('btnTopbarSidebarToggle');

  if (btnSidebar) {
    btnSidebar.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    btnSidebar.setAttribute('title', collapsed ? 'Expandir menu lateral' : 'Recolher menu lateral');
  }
  if (btnTopbar) {
    btnTopbar.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    btnTopbar.setAttribute('title', collapsed ? 'Expandir menu lateral' : 'Recolher menu lateral');
  }
}

function initSidebarToggle() {
  const isCollapsed = isSidebarCollapsed();
  updateSidebarToggleButtons(isCollapsed);

  const toggleHandler = () => {
    const nextState = !isSidebarCollapsed();
    setSidebarCollapsed(nextState);
  };

  const btnSidebar = document.getElementById('btnSidebarToggle');
  if (btnSidebar) {
    btnSidebar.addEventListener('click', toggleHandler);
  }

  const btnTopbar = document.getElementById('btnTopbarSidebarToggle');
  if (btnTopbar) {
    btnTopbar.addEventListener('click', toggleHandler);
  }
}

// Inicializa o tema, o modo de privacidade e o menu lateral quando o DOM estiver pronto
function initApp() {
  initTheme();
  initPrivacyMode();
  initSidebarToggle();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}

// Atalho de teclado para alternar tema (Alt + T)
document.addEventListener('keydown', (event) => {
  if (event.altKey && (event.key === 't' || event.key === 'T')) {
    const targetTag = event.target ? event.target.tagName : '';
    if (targetTag !== 'INPUT' && targetTag !== 'TEXTAREA') {
      event.preventDefault();
      const current = getActiveTheme();
      const next = current === 'dark' ? 'light' : 'dark';
      setTheme(next);
    }
  }
});

// ============================================================================
// Validações e Interações de Formulários
// ============================================================================

// Confirmação para formulários com data-confirm
document.querySelectorAll('form[data-confirm]').forEach(form => {
  form.addEventListener('submit', event => {
    if (!window.confirm(form.dataset.confirm)) {
      event.preventDefault();
      return;
    }
  });
});

// Prevenção contra duplo clique e feedback de envio em formulários
document.querySelectorAll('form').forEach(form => {
  form.addEventListener('submit', event => {
    if (event.defaultPrevented) return;

    if (form.dataset.submitting === 'true') {
      event.preventDefault();
      return;
    }

    form.dataset.submitting = 'true';
    const submitBtn = form.querySelector('button[type="submit"], input[type="submit"], button:not([type])');
    if (submitBtn) {
      submitBtn.style.pointerEvents = 'none';
      submitBtn.style.opacity = '0.75';
      submitBtn.setAttribute('aria-busy', 'true');
    }

    // Timeout de segurança para reabilitar após 8s se a resposta demorar ou falhar
    setTimeout(() => {
      form.dataset.submitting = 'false';
      if (submitBtn) {
        submitBtn.style.pointerEvents = '';
        submitBtn.style.opacity = '';
        submitBtn.removeAttribute('aria-busy');
      }
    }, 8000);
  });
});

