/**
 * 外观与动态背景：把设置页那些项真正作用到界面上。
 *
 * 桌面端是把它们写进 settings.json（backdrop 系列 / ui_opacity / theme / accent / glass_effect），
 * 无头端目前没有 per-user 设置存储，所以先存浏览器 localStorage —— 同一台机器打开控制台即生效。
 * 需要「换台机器也生效」时，把这里换成读写 /api/config 即可（键名与桌面端 settings 对齐）。
 *
 * 强调色直接用 tokens.css 里已有的 [data-accent] 块（6 色调色板与桌面端 THEMES 一致）。
 */

export const ACCENT_KEYS = {
  深邃蓝: 'default',
  暗夜紫: 'midnight',
  赛博青: 'cyber',
  暖阳橙: 'sunset',
  薄荷绿: 'forest',
  '深空绿（新色板）': 'slate',
};

export const UI_THEME_KEYS = { 极光玻璃: 'glass', 瑞士极简: 'swiss', 深空终端: 'terminal' };
export const GLASS_KEYS = { '默认（原样）': 'default', 液态玻璃: 'liquid', 颗粒磨砂: 'frosted' };

/** 默认值与桌面端 settings 默认一致（遮罩 0.68 / 不透明度 70 / 亮度 0） */
export const APPEARANCE_DEFAULTS = {
  enabled: false,
  path: '',
  autoplay: false,
  loop: false,
  mask: 68,
  opacity: 70,
  bright: 0,
  animations: true,
  theme: '极光玻璃',
  accent: '深邃蓝',
  glass: '默认（原样）',
};

const STORE_KEY = 'as_appearance';

export function loadAppearance() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return { ...APPEARANCE_DEFAULTS };
    return { ...APPEARANCE_DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return { ...APPEARANCE_DEFAULTS };
  }
}

export function saveAppearance(ap) {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(ap));
  } catch {
    /* 隐私模式/配额满时忽略：外观只是氛围层 */
  }
}

export function isVideoPath(p) {
  return /\.(mp4|webm|ogv|ogg|mov|m4v|mkv)$/i.test(String(p || '').trim());
}

/** 面板底色按「UI 不透明度」缩放：桌面端 70% 就是基准 1.0，范围 10~95 → 0.14~1.36 */
function panelAlphaScale(opacity) {
  const v = Number(opacity);
  const k = (Number.isFinite(v) ? v : 70) / 70;
  return Math.min(1.4, Math.max(0.15, k));
}

export function applyAppearance(ap) {
  const root = document.documentElement;
  root.dataset.accent = ACCENT_KEYS[ap.accent] || 'default';
  root.dataset.uiTheme = UI_THEME_KEYS[ap.theme] || 'glass';
  root.dataset.glass = GLASS_KEYS[ap.glass] || 'default';
  root.classList.toggle('reduce-motion', !ap.animations);

  const k = panelAlphaScale(ap.opacity);
  if ((UI_THEME_KEYS[ap.theme] || 'glass') === 'glass') {
    // 只有极光玻璃按「UI 不透明度」缩放面板 alpha。瑞士/终端的面板色由主题 CSS 决定，
    // 这里写内联变量会把主题色顶掉（内联样式优先级最高，之前就是这么被覆盖的）。
    root.style.setProperty('--as-panel', `rgba(17, 22, 34, ${(0.62 * k).toFixed(3)})`);
    root.style.setProperty('--as-panel-strong', `rgba(19, 26, 40, ${(0.78 * k).toFixed(3)})`);
  } else {
    root.style.removeProperty('--as-panel');
    root.style.removeProperty('--as-panel-strong');
  }
  root.style.setProperty('--as-bg-mask', String(Math.min(1, Math.max(0, Number(ap.mask) / 100))));
  root.style.setProperty('--as-bg-bright', String(1 + Number(ap.bright || 0) / 200));

  const hasBg = Boolean(ap.enabled && ap.path);
  document.body.classList.toggle('has-bg', hasBg);
}
