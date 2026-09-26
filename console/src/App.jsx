import { useCallback, useEffect, useRef, useState } from 'react';
import { apiUrl, authUrl, get, post, put } from './api.js';
import MemoryTimeline from './MemoryTimeline.jsx';
import KnowledgeBase from './KnowledgeBase.jsx';
import { RecentMessages, StatsPanel } from './BrainStats.jsx';
import ZipInstall from './ZipInstall.jsx';
import {
  APPEARANCE_DEFAULTS,
  applyAppearance,
  isVideoPath,
  loadAppearance,
  saveAppearance,
} from './appearance.js';

/* 统一线性图标集：24×24 viewBox、stroke-width 1.5、round 端点/拐角、fill:none、stroke:currentColor。
   每个 name 对应「若干段 path」，一个图形拆成几笔，线条粗细与视觉比重才一致
   （之前每个图标一条长度不等的复杂路径，粗细/圆角/比重各不相同，看着就是「瞎做的」）。
   语义分配（任何两个导航项都不共用图标）：
   home 首页 · plug 接入（把通道插进来）· brain AI 大脑 · puzzle 插件管理 ·
   server 全局管理（服务/进程机架）· chat 消息中心 · file-text 日志（文档）·
   package 依赖（包裹箱）· gear 设置（齿轮）· user 星群账号（人像）；
   ⚠ 账号 ≠ 设置：「星群账号」入口（侧栏 .sidebar-account / 瑞士顶栏 .topnav__account /
   深空图标栏 .rail__account）一律用 user，gear 只留给「设置」那一条，任何两项都不共用图标。
   通道图标：qq QQ（企鹅）· wechat 微信（双气泡）· plane 飞书 · planeTilt 纸飞机 ·
   terminal 终端窗口 / check 完成勾（供其它页面调用，保持可用）。 */
const ICONS = {
  home: [
    'M3.5 10.6 12 3.6l8.5 7',
    'M5.8 9.4V19a1.4 1.4 0 0 0 1.4 1.4h9.6A1.4 1.4 0 0 0 18.2 19V9.4',
    'M9.8 20.4v-5.2h4.4v5.2',
  ],
  plug: [
    'M9 3v5',
    'M15 3v5',
    'M6 8h12v6.4a3.6 3.6 0 0 1-3.6 3.6h-4.8A3.6 3.6 0 0 1 6 14.4V8Z',
    'M12 18v3.4',
  ],
  brain: [
    'M12 4.6C10.6 2.6 7.6 3 7 5 4.6 4.8 3.2 6.6 3.6 8.6 2.2 9.8 2.4 12.2 4.2 13.2 4 15.6 5.8 17.4 8 17 8.4 19 10.6 19.8 12 19.2',
    'M12 4.6C13.4 2.6 16.4 3 17 5 19.4 4.8 20.8 6.6 20.4 8.6 21.8 9.8 21.6 12.2 19.8 13.2 20 15.6 18.2 17.4 16 17 15.6 19 13.4 19.8 12 19.2',
    'M12 4.6v14.6',
    'M9.6 8.9c-1.3 0-2 1.5-1.1 2.5',
    'M14.4 8.9c1.3 0 2 1.5 1.1 2.5',
  ],
  chat: [
    'M21 15.6a2 2 0 0 1-2 2H8.4L4 21.2V5.6a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2Z',
    'M8.6 9.4h7.4',
    'M8.6 13h4.4',
  ],
  wechat: [
    'M12 10.6a2 2 0 0 1-2 2H6.6L3.6 15.2V5.6a2 2 0 0 1 2-2h4.4a2 2 0 0 1 2 2Z',
    'M14.4 16.8a1.6 1.6 0 0 1 1.6 1.6h3.6L21.2 21V11.4a1.6 1.6 0 0 1-1.6-1.6H16a1.6 1.6 0 0 1-1.6 1.6Z',
  ],
  qq: [
    'M12 3.6C15.6 3.6 18.4 7 18.4 11.2c0 3-1 6.2-2.6 8.2-.5.6-1.2.9-2 .9H10.2c-.8 0-1.5-.3-2-.9-1.6-2-2.6-5.2-2.6-8.2C5.6 7 8.4 3.6 12 3.6Z',
    'M12 11.4c1.8 0 3.3 1.5 3.3 3.4 0 1.6-.7 3-1.6 4.2H10.3c-.9-1.2-1.6-2.6-1.6-4.2C8.7 12.9 10.2 11.4 12 11.4Z',
    'M11.3 9.6 12 10.4 12.7 9.6Z',
    'M9.9 7.45a0.75 0.75 0 0 1 0 1.5 0.75 0.75 0 0 1 0-1.5Z',
    'M14.1 7.45a0.75 0.75 0 0 1 0 1.5 0.75 0.75 0 0 1 0-1.5Z',
  ],
  puzzle: [
    'M9.6 4a2.4 2.4 0 0 1 4.8 0H19a1 1 0 0 1 1 1v4.6a2.4 2.4 0 0 0 0 4.8V19a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-4.6a2.4 2.4 0 0 0 0-4.8V5a1 1 0 0 1 1-1h4.6Z',
  ],
  server: [
    'M5 4.5h14A1.5 1.5 0 0 1 20.5 6v2.5a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 8.5V6A1.5 1.5 0 0 1 5 4.5Z',
    'M5 14.5h14a1.5 1.5 0 0 1 1.5 1.5v2.5a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 18.5V16A1.5 1.5 0 0 1 5 14.5Z',
    'M5.9 6.2a1 1 0 0 1 0 2 1 1 0 0 1 0-2Z',
    'M5.9 16.2a1 1 0 0 1 0 2 1 1 0 0 1 0-2Z',
  ],
  'file-text': [
    'M6.5 3.5h7L17 7v12a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 5 19V5a1.5 1.5 0 0 1 1.5-1.5Z',
    'M13.5 3.5V7H17',
    'M8 12h8',
    'M8 15.6h5',
  ],
  package: [
    'M20 8.4 12 4 4 8.4v7.2L12 20l8-4.4V8.4Z',
    'M4 8.4 12 12.8l8-4.4',
    'M12 12.8V20',
  ],
  terminal: [
    'M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z',
    'M3 8.6h18',
    'M7 12.4l2.4 2.2-2.4 2.2',
    'M12.6 16.8h4',
  ],
  /* 账号：一个头 + 一段肩弧（最外层落在 4.25–19.75，1–23 安全区内不溢出） */
  user: [
    'M12 4.6a3.5 3.5 0 0 1 0 7 3.5 3.5 0 0 1 0-7Z',
    'M5 19.4a7 7 0 0 1 14 0',
  ],
  gear: [
    'M8.4 12a3.6 3.6 0 0 1 7.2 0 3.6 3.6 0 0 1-7.2 0Z',
    'M17.6 12h2',
    'M14.8 16.85 15.8 18.58',
    'M9.2 16.85 8.2 18.58',
    'M6.4 12h-2',
    'M9.2 7.15 8.2 5.42',
    'M14.8 7.15 15.8 5.42',
  ],
  plane: [
    'M21 3 14.7 21 11.1 12.9 3 9.3 21 3Z',
    'M21 3 11.1 12.9',
  ],
  planeTilt: [
    'M21 21 14.7 3 11.1 11.1 3 14.7 21 21Z',
    'M21 21 11.1 11.1',
  ],
  check: ['M4.5 12.5 9.6 17.6 19.5 6.6'],
};

const APP_VERSION = '1.1.0';

/* ---------------------------------------------------------------- 依赖任务
   后台扫描 / 安装由无头端的 console_ext 跑在子线程里（一个请求挂几十秒会被 nginx 掐），
   所以控制台这边用 1.2s 轮询 /api/deps/status 拿进度；返回最终状态对象。 */
const DEPS_POLL_MS = 1200;
const DEPS_POLL_MAX = 300; // 最多 6 分钟

/** 写接口（扫描/安装/重启）要鉴权：未登录时后端回「请先登录」，这里补一句去哪儿登录 */
function withAuthHint(err) {
  const m = String((err && err.message) || err);
  return m.includes('登录') ? `${m}：请先在「设置 → 星群账号」登录，扫描/安装/重启都需要鉴权` : m;
}

/* 未登录 / 无权限的统一判据。
   为什么要把 403 也算进来：公开预览路径（/pv<token>/）下 nginx 对 /api/tools/status、
   /api/plugins/installed 直接 return 403（不落到后端），未登录时这两个请求拿到的是
   「HTTP 403」而不是后端的「请先登录」—— 只看 401 会把它们当成普通故障弹红字。 */
function isAuthError(err) {
  const m = String((err && err.message) || '');
  return m.includes('请先登录') || m.includes('未登录') || m.includes('401') || m.includes('403');
}

/** 「读不到真实数据」时的统一说法。
    ⚠ 不要把话说死成「你没登录」：公开预览路径 /pv<token>/ 下 nginx 会对
    /api/tools/status、/api/plugins/installed 直接 return 403（不落到后端），
    已经登录也会拿到 403 —— 所以这里说的是「读不到 + 先去登录」，
    并把「登录了还读不到」这个第二种可能一起写出来，不让用户白折腾。 */
const LOGIN_HINT =
  '读不到真实数据：请先登录（侧栏「星群账号」或 设置 → 账号）；登录后仍然读不到，就是这个访问地址没放开该接口';

async function runDeps(kind, onStatus) {
  try {
    await post(`/api/deps/${kind}`, {});
  } catch (e) {
    throw new Error(withAuthHint(e));
  }
  for (let i = 0; i < DEPS_POLL_MAX; i += 1) {
    const st = await get('/api/deps/status');
    if (onStatus) onStatus(st);
    if (!st.running) return st;
    await new Promise((r) => setTimeout(r, DEPS_POLL_MS));
  }
  throw new Error('依赖任务超时（超过 6 分钟）');
}
const ACTIVATE_URL = 'https://astroswarm.cn/account.html';

/* ── 权益判定的唯一口径────────
   后端 /api/auth/status 与 /api/plugins/entitlement 回三个字段：
     member      = 档位有效且未过期（微信通道看它）
     all_plugins = 历史字段（能力包已全部免费开源，运行时不再按它放行）
     full        = 旧字段 = all_plugins，保留兼容旧后端

   判定集中在下面两个小函数里，别在页面里直接读 auth.full，
   否则会出现「后端已经开通、界面显示未开通」的显示错。 */
const isMember = (a) => Boolean(a?.member) || Boolean(a?.all_plugins) || Boolean(a?.full);
const isFull = (a) => Boolean(a?.all_plugins) || Boolean(a?.full);

/** 写剪贴板：clipboard API 在非安全上下文（http 且非 localhost）不可用，兜底用 execCommand。 */
async function copyToClipboard(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  const ok = document.execCommand('copy');
  document.body.removeChild(ta);
  if (!ok) throw new Error('浏览器不给写剪贴板');
}

/**
 * 无头端的「打开 XX」一律改成「复制路径」：浏览器里没有服务器文件管理器，
 * 但把路径粘到 SSH / SFTP 里就是最顺手的做法。makePath 里现取现拼，保证是最新值。
 */
async function copyServerPath(setMsg, what, makePath) {
  try {
    const p = await makePath();
    await copyToClipboard(p);
    setMsg(`已复制${what}：${p}（服务器上的路径，粘到终端或 SFTP 里用）`);
  } catch (e) {
    setMsg(`复制${what}失败：${e.message}`);
  }
}

/** bot 的 .env 路径：/api/services/status 里带着 bot_dir。 */
async function botEnvPath() {
  const s = await get('/api/services/status');
  const dir = s && s.bot && s.bot.bot_dir;
  if (!dir) throw new Error('没拿到 bot 目录（机器人还没部署过）');
  return `${dir}/.env`;
}

/** 插件目录：/api/plugins/installed 里带着 dir。 */
async function pluginsDirPath() {
  const d = await get('/api/plugins/installed');
  if (!d || !d.dir) throw new Error('没拿到插件目录');
  return d.dir;
}

/* 导航按角色分组（不再按「平台 / 全局」分层）：
   运行 = 连通道看健康；能力 = 人格与工具；系统 = 服务、记录与设置。
   组标题小字次要色；条目沿用原来的图标与 .nav-item 样式。
   图标语义一一对应、互不重复：首页 home / 接入 plug（多通道合并页，不再用微信图标）
   / AI 大脑 brain / 插件管理 puzzle / 全局管理 server（服务与进程）/ 消息中心 chat
   / 日志 file-text（文档，不再和全局管理共用 terminal）/ 依赖 package / 设置 gear。 */
const NAV_GROUPS = [
  {
    id: 'run',
    title: '运行',
    items: [
      ['home', '首页', 'home'],
      ['access', '接入', 'plug'],
    ],
  },
  {
    id: 'skill',
    title: '能力',
    items: [
      ['brain', 'AI 大脑', 'brain'],
      ['plugins', '插件管理', 'puzzle'],
    ],
  },
  {
    id: 'sys',
    title: '系统',
    items: [
      ['services', '全局管理', 'server'],
      ['messages', '消息中心', 'chat'],
      ['logs', '日志', 'file-text'],
      ['deps', '依赖', 'package'],
      ['settings', '设置', 'gear'],
    ],
  },
];
// 桌面端 ADVANCED_PAGES：小白模式（默认开启）下隐藏这些入口，可在「设置」里关掉
const ADVANCED_PAGES = ['messages', 'plugins', 'logs', 'deps'];
const BEGINNER_KEY = 'as_beginner_mode';

/* UI v2 重排后，styles.css 自动区那批「按页钉死」的定位规则（.page > section:nth-child(n) …）
   是按旧 DOM 的层级数出来的，新 DOM 一旦命中就会把高度/位移钉错地方。
   换一个页名，让旧选择器整体不命中 —— 自动区一个字节都不用改，旧页面的版式也不受影响。 */
const PAGE_KEY = {
  home: 'home-v2',
  access: 'access-v2',
  services: 'services-v2',
  plugins: 'plugins-v2',
  settings: 'settings-v2',
};

/* 图标渲染：尺寸只有两档 —— 侧栏/内容区 18、顶栏/标题栏 16（调用点显式传 size）。
   规格钉死：24×24 viewBox、stroke 1.5、round、fill:none、currentColor。
   className="icon" 让 svg 变块级并在 flex 里 align-self 居中（inline svg 默认带基线偏移，
   看起来会偏下 1–2px），保证同一排按钮里的图标光学对齐。 */
function Icon({ name, size = 18 }) {
  const paths = ICONS[name] || ICONS.package;
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {paths.map((d, i) => (
        <path key={i} d={d} />
      ))}
    </svg>
  );
}

function StatusChip({ ok, warn, children }) {
  const cls = warn ? 'chip chip--warn' : ok ? 'chip chip--ok' : 'chip chip--err';
  return <span className={cls}>{children}</span>;
}

/** 桌面端 StatusBadge：9px 色点（带同色辉光）+ 13px 文案 */
function StatusBadge({ tone = 'unknown', children }) {
  return (
    <span className={`badge badge--${tone}`}>
      <i className="badge__dot" />
      <span className="badge__label">{children}</span>
    </span>
  );
}

function Group({ title, desc, children }) {
  return (
    <section className="group">
      <header className="group__head">
        <h2>{title}</h2>
        {desc && <p>{desc}</p>}
      </header>
      <div className="group__body">{children}</div>
    </section>
  );
}

function Field({ label, children }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export default function App() {
  const [view, setView] = useState('home');
  const [detailPid, setDetailPid] = useState('');
  const [detailEntry, setDetailEntry] = useState(null);
  const [beginner, setBeginner] = useState(() => localStorage.getItem(BEGINNER_KEY) !== '0');
  // 真正的「已登录」判据是本地有没有 token：/api/auth/status 无论登录与否都会返回本机账号邮箱，
  // 拿 auth.email 当登录标志会让设置页的端口一直空着（/api/config 需要 token）。
  const [token, setToken] = useState(() => localStorage.getItem('astroswarm_token') || '');
  const [health, setHealth] = useState(null);
  const [auth, setAuth] = useState(null);
  const [services, setServices] = useState(null);
  const [config, setConfig] = useState(null);
  // 外观（背景/遮罩/不透明度/主题/强调色/质感）：存在浏览器本地，改动即时生效
  const [appearance, setAppearance] = useState(loadAppearance);

  useEffect(() => {
    applyAppearance(appearance);
    saveAppearance(appearance);
  }, [appearance]);

  // 当前页 id 写进 <html data-page="xxx">：styles.css 里「自动钉死 / 自动求解」那两段规则
  // 是按页作用域的（html[data-page='xxx'][data-ui-theme='yyy'] .page > …）。
  // UI v2 重排过的页面走 PAGE_KEY 里的新页名：旧规则整体不命中，自动区一个字节都不用改；
  // 没重排的页面（brain / logs / deps / messages / plugin-detail）仍用原名，版式不变。
  useEffect(() => {
    document.documentElement.dataset.page = PAGE_KEY[view] || view;
  }, [view]);

  const refresh = async () => {
    try {
      const [h, a, s] = await Promise.all([
        get('/health'),
        get('/api/auth/status'),
        get('/api/services/status'),
      ]);
      setHealth(h);
      setAuth(a);
      setServices(s);
    } catch {
      /* 服务未就绪时保持旧状态 */
    }
  };

  const loadConfig = async () => {
    try {
      setConfig(await get('/api/config'));
    } catch {
      /* 保持旧配置 */
    }
  };

  useEffect(() => {
    loadConfig();
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, []);

  const setBeginnerMode = (on) => {
    localStorage.setItem(BEGINNER_KEY, on ? '1' : '0');
    setBeginner(Boolean(on));
  };

  // 登录/认领/退出之后配置才有权限拉：一起刷新，否则设置页端口一直是空的
  const reloadAll = async () => {
    await Promise.all([refresh(), loadConfig()]);
  };

  const onToken = (value) => {
    if (value) localStorage.setItem('astroswarm_token', value);
    else localStorage.removeItem('astroswarm_token');
    setToken(value || '');
  };

  const accountTip = auth?.email
    ? `星群账号 · 已登录：${auth.email}`
    : '星群账号 · 未登录，点击登录';

  /* 小白模式隐藏 messages / plugins / logs / deps 四个入口。但首页「打开消息中心」、
     接入页「打开消息中心」、设置页「实时日志 / 依赖管理」都会把用户直接送到这些页 ——
     那时侧栏里没有对应条目，用户会以为「进到了导航上不存在的地方」，也找不到回去的路。
     所以：当前页永远保留自己的入口。只多不少，不新增任何功能。 */
  const visibleNav = (items) =>
    items.filter(([id]) => !(beginner && ADVANCED_PAGES.includes(id)) || id === view);

  /* 侧边栏（极光玻璃）：三组「运行 / 能力 / 系统」，组标题小字次要色，条目仍是原来的 .nav-item。
     组内是一个面板，组与组之间留空；列表自带 overflow，窄屏只在组内滚动、不横向溢出。 */
  const renderNav = () => (
    <nav className="navgroups" aria-label="主导航">
      {NAV_GROUPS.map((g) => {
        const items = visibleNav(g.items);
        if (!items.length) return null;
        return (
          <div className="navgrp" key={g.id}>
            <div className="navgrp__title">{g.title}</div>
            <div className="navgrp__list">
              {items.map(([id, label, icon]) => (
                <button
                  key={id}
                  type="button"
                  className={view === id ? 'nav-item nav-item--on' : 'nav-item'}
                  onClick={() => setView(id)}
                  aria-current={view === id ? 'page' : undefined}
                >
                  <Icon name={icon} size={18} />
                  <span>{label}</span>
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </nav>
  );

  /* 瑞士极简：顶栏导航（带图标，选中 = 深色文字 + 2px 强调色下划线）。
     账号按钮 → 三组（组间竖分隔线）；窄屏由 .navflow 允许换行，不横向溢出。 */
  const renderTopnav = () => (
    <nav className="topnav navflow" aria-label="顶部导航">
      <button type="button" className="topnav__account" title={accountTip} onClick={() => setView('settings')}>
        <Icon name="user" size={16} />
        <span>星群账号</span>
      </button>
      {NAV_GROUPS.flatMap((g, gi) => {
        const items = visibleNav(g.items);
        if (!items.length) return [];
        return [
          ...(gi > 0 ? [<span className="topnav__sep" key={`sep-${g.id}`} />] : []),
          ...items.map(([id, label, icon]) => (
            <button
              key={id}
              type="button"
              className={view === id ? 'topnav__item topnav__item--on' : 'topnav__item'}
              onClick={() => setView(id)}
              aria-current={view === id ? 'page' : undefined}
            >
              <Icon name={icon} size={16} />
              <span>{label}</span>
            </button>
          )),
        ];
      })}
    </nav>
  );

  /* 深空终端：54 宽的图标栏（图标 20），选中 = 强调色底 + 左侧 2px 强调色边；
     组与组之间用一条极细分隔线（图标模式下没有文字，只能靠线分层）。 */
  const renderRail = () => (
    <nav className="rail" aria-label="图标导航">
      <button type="button" className="rail__account" title={accountTip} onClick={() => setView('settings')}>
        <Icon name="user" size={18} />
      </button>
      {NAV_GROUPS.flatMap((g, gi) => {
        const items = visibleNav(g.items);
        if (!items.length) return [];
        return [
          ...(gi > 0 ? [<span className="railsep" key={`sep-${g.id}`} />] : []),
          ...items.map(([id, label, icon]) => (
            <button
              key={id}
              type="button"
              className={view === id ? 'rail__item rail__item--on' : 'rail__item'}
              title={label}
              aria-label={label}
              onClick={() => setView(id)}
              aria-current={view === id ? 'page' : undefined}
            >
              <Icon name={icon} size={18} />
            </button>
          )),
        ];
      })}
    </nav>
  );

  return (
    <>
      {/* 动态背景层（图片/视频 + 遮罩强度），永远在最底层且不挡点击 */}
      <div className="bg-media" aria-hidden="true">
        {appearance.enabled && appearance.path ? (
          isVideoPath(appearance.path) ? (
            <video src={appearance.path} autoPlay={appearance.autoplay} loop={appearance.loop} muted playsInline />
          ) : (
            <img src={appearance.path} alt="" />
          )
        ) : null}
        <div className="bg-media__mask" />
      </div>
      <div className="shell">
      <header className="titlebar">
        <span className="titlebar__title">AstroSwarm 星群</span>
        <span className="titlebar__ver">v{APP_VERSION}</span>
        <div className="titlebar__right">
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => setView('logs')}>
            实时日志
          </button>
          {/* 通道开通判据是 member；没有权益的账号只写「未开通」 */}
          <StatusChip ok={isMember(auth)} warn={!auth?.email}>
            {isMember(auth) ? `已开通 · ${auth.plan}` : auth?.email ? '未开通' : '未登录'}
          </StatusChip>
        </div>
      </header>
      {renderTopnav()}
      <div className="app">
        <aside className="sidebar-wrap">
          <button
            type="button"
            className="sidebar-account"
            title={accountTip}
            onClick={() => setView('settings')}
          >
            <Icon name="user" size={18} />
            <span>星群账号</span>
          </button>
          {renderNav()}
        </aside>
        {renderRail()}
        <main className="main" key={view}>
          <div className={PAGE_KEY[view] ? 'page page--v2' : 'page'}>
            {view === 'home' && (
              <Overview
                health={health}
                auth={auth}
                services={services}
                config={config}
                loggedIn={Boolean(token)}
                onAccess={() => setView('access')}
                onMessages={() => setView('messages')}
                onServices={() => setView('services')}
              />
            )}
            {view === 'access' && (
              <AccessPage
                auth={auth}
                config={config}
                health={health}
                services={services}
                onSaved={loadConfig}
                onMessages={() => setView('messages')}
              />
            )}
            {view === 'services' && (
              <ServicesPage
                config={config}
                health={health}
                services={services}
                onAccess={() => setView('access')}
                onLogs={() => setView('logs')}
                onDeps={() => setView('deps')}
              />
            )}
            {view === 'brain' && (
              <AiBrain
                config={config}
                onSaved={loadConfig}
                beginner={beginner}
                loggedIn={Boolean(token)}
              />
            )}
            {view === 'messages' && <MessageCenter loggedIn={Boolean(token)} />}
            {view === 'plugins' && (
              <Plugins
                auth={auth}
                onDetail={(pid, entry) => {
                  setDetailPid(pid);
                  setDetailEntry(entry || null);
                  setView('plugin-detail');
                }}
              />
            )}
            {view === 'plugin-detail' && (
              <PluginDetail
                pid={detailPid}
                entry={detailEntry}
                auth={auth}
                onBack={() => setView('plugins')}
              />
            )}
            {view === 'logs' && <Logs loggedIn={Boolean(token)} />}
            {view === 'settings' && (
              <Settings
                config={config}
                services={services}
                onSaved={loadConfig}
                beginner={beginner}
                onBeginner={setBeginnerMode}
                loggedIn={Boolean(token)}
                health={health}
                auth={auth}
                onChanged={reloadAll}
                onToken={onToken}
                appearance={appearance}
                onAppearance={setAppearance}
                onGo={(v) => setView(v)}
              />
            )}
            {view === 'deps' && <Deps />}
          </div>
        </main>
      </div>
      </div>
    </>
  );
}

function QWeatherCard() {
  const [cfg, setCfg] = useState(null);
  const [pub, setPub] = useState('');
  const [apiHost, setApiHost] = useState('');
  const [projectId, setProjectId] = useState('');
  const [credId, setCredId] = useState('');
  const [msg, setMsg] = useState('');

  const refresh = () => {
    get('/api/qweather/config')
      .then((d) => {
        setCfg(d);
        setApiHost(d.api_host || '');
        setProjectId(d.project_id || '');
        setCredId(d.credential_id || '');
      })
      .catch((e) => setMsg(String(e.message)));
  };

  useEffect(refresh, []);

  const generate = async () => {
    try {
      const d = await post('/api/qweather/generate-key');
      setPub(d.public_key || '');
      setMsg('密钥已生成并保存在服务器，把公钥贴到和风控制台');
      refresh();
    } catch (e) {
      setMsg(String(e.message));
    }
  };

  const save = async () => {
    try {
      await post('/api/qweather/save', {
        api_host: apiHost,
        project_id: projectId,
        credential_id: credId,
      });
      setMsg('已保存，重启机器人生效');
      refresh();
    } catch (e) {
      setMsg(String(e.message));
    }
  };

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h3 className="subhead">和风天气配置</h3>
      {cfg && (
        <p className="row-item__desc">
          状态：
          {cfg.configured ? '已配置 ✓' : '未完成（需要公钥 + 凭据ID）'}
          {cfg.private_key_path ? (
            <span className="mono"> · 私钥 {cfg.private_key_path}</span>
          ) : null}
        </p>
      )}
      <div className="field">
        <label>API Host</label>
        <input
          value={apiHost}
          onChange={(e) => setApiHost(e.target.value)}
          placeholder="控制台-设置里的专属 API Host，如 xxx.qweatherapi.com"
        />
      </div>
      <div className="field">
        <label>项目ID</label>
        <input
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          placeholder="控制台-项目管理里的项目ID"
        />
      </div>
      <div className="field">
        <label>凭据ID</label>
        <input
          value={credId}
          onChange={(e) => setCredId(e.target.value)}
          placeholder="创建 JWT 凭据后显示的 ID"
        />
      </div>
      <div className="wake-row" style={{ gap: 8, marginTop: 8 }}>
        <button type="button" className="btn" onClick={generate}>
          生成密钥对
        </button>
        <button type="button" className="btn btn--primary" onClick={save}>
          保存配置
        </button>
      </div>
      {pub && (
        <pre
          className="mono"
          style={{
            whiteSpace: 'pre-wrap',
            background: 'rgba(255,255,255,0.05)',
            padding: 10,
            borderRadius: 8,
            marginTop: 10,
          }}
        >
          {pub}
        </pre>
      )}
      <p className="msg msg--in" style={{ marginTop: 10 }}>
        控制台：dev.qweather.com → 项目管理 → 你的项目 → 添加凭据 →
        身份认证方式选「JSON Web Token」→ 粘贴上方公钥 → 保存 →
        把「设置」里的 API Host 和「凭据ID」填到上面 → 保存配置 → 重启机器人。
      </p>
      {msg && <p className="msg msg--in">{msg}</p>}
    </div>
  );
}

/* 插件管理：与桌面端 plugins_page.py 1:1（高级页，小白模式下入口被隐藏）。
   实测：左右两张面板各 679×598（行内间距 14）→ 全宽「本地插件」169 → 底部「安装任务」48
   （只露标题，任务面板自身隐藏）。面板内所有子行间距 = 面板自身间距 6
   （Qt 的子布局会继承父布局 spacing，所以这里不能用页面的 14）。
   开发者模式关闭时：PyPI / zip 的输入与按钮禁用、「NoneBot 插件市场」整块隐藏。
   列表项格式取自 _refresh_market_list：`[免费|需开通] 名字  v版本  [分类]`。 */
const PLUGIN_TIER_LABEL = { free: '免费', member: '需开通', buy: '需开通' };
const PLUGIN_ITEM_COLOR = { free: '#34D399', member: '#22D3EE', buy: '#22D3EE' };

/** 插件详情页：介绍 / 功能 / 可调参数（写 <data_home>/tool_packs/<id>/config.json）。 */
function PluginDetail({ pid, entry, auth, onBack }) {
  const [d, setD] = useState(null);
  const [ent, setEnt] = useState(null);      // /api/plugins/entitlement
  const [code, setCode] = useState('');
  const [form, setForm] = useState({});
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  const load = () => {
    if (!pid) return;
    get(`/api/tools/${pid}/detail`)
      .then((res) => {
        setD(res);
        setForm({ ...(res.values || {}) });
      })
      .catch((e) => setMsg(`读取插件详情失败：${e.message}`));
  };
  useEffect(load, [pid]);

  const loadEnt = () =>
    get('/api/plugins/entitlement')
      .then(setEnt)
      .catch(() => {});
  useEffect(loadEnt, [pid]);

  const price = entry?.price;
  const buyUrl = ACTIVATE_URL;   // 开通用账号中心；市场清单里的旧购买链接不再使用
  const owned = Boolean(ent && (ent.owned_plugins || []).includes(pid));
  // 能力包已全部免费开源：这里只做「装了就能用」的兜底判断，
  // 旧清单里带 tier 的条目按后端口径（all_plugins / 已登记）放行。
  const locked = Boolean(entry && entry.tier && entry.tier !== 'free') && !owned && !isFull(ent);

  const redeem = async () => {
    const v = code.trim();
    if (!v) {
      setMsg('先填兑换码');
      return;
    }
    setBusy(true);
    try {
      const res = await post('/api/plugins/redeem', { code: v });
      setCode('');
      setEnt(res);
      setMsg(
        (res.owned_plugins || []).includes(pid)
          ? `兑换成功：已永久拥有「${d?.name || pid}」`
          : `兑换成功（当前已购：${(res.owned_plugins || []).join('、') || '无'}）`,
      );
    } catch (e) {
      setMsg(withAuthHint(e));
    } finally {
      setBusy(false);
    }
  };

  const refreshEnt = async () => {
    setBusy(true);
    try {
      const res = await post('/api/plugins/refresh-entitlement', {});
      setEnt(res);
      setMsg(
        (res.owned_plugins || []).includes(pid)
          ? '权益已刷新：这个插件已经是你的了 ✓'
          : '权益已刷新，但还没查到这笔购买（如果你刚付款，等 1~5 分钟再点一次）',
      );
    } catch (e) {
      setMsg(withAuthHint(e));
    } finally {
      setBusy(false);
    }
  };

  const fields = d?.fields || [];
  const installed = Boolean(d?.installed);
  const changed = fields.filter((f) => form[f.key] !== (d?.values || {})[f.key]);
  const set = (k, v) => setForm((s) => ({ ...s, [k]: v }));

  const save = async () => {
    if (!changed.length) {
      setMsg('没有改动');
      return;
    }
    setBusy(true);
    try {
      const patch = {};
      changed.forEach((f) => {
        patch[f.key] = f.type === 'number' ? Number(form[f.key]) : form[f.key];
      });
      const res = await put(`/api/tools/${pid}/config`, patch);
      setMsg(`已保存：${Object.keys(res.changed || {}).join('、') || '无变化'}（参数立刻生效，下次主动消息就按新值判断）`);
      load();
    } catch (e) {
      setMsg(withAuthHint(e));
    } finally {
      setBusy(false);
    }
  };

  const installPack = async () => {
    try {
      await post('/api/tools/install', { id: pid });
      setMsg('已安装');
      load();
    } catch (e) {
      setMsg(withAuthHint(e));
    }
  };

  const field = (f) => {
    const v = form[f.key];
    if (f.type === 'bool') {
      return (
        <label className="check">
          <input type="checkbox" checked={Boolean(v)} onChange={(e) => set(f.key, e.target.checked)} />
          <span>{f.label || f.key}</span>
        </label>
      );
    }
    if (f.type === 'number') {
      return (
        <div className="param-row">
          <span>{f.label || f.key}</span>
          <input
            className="p-input"
            type="number"
            value={v ?? ''}
            min={f.min}
            max={f.max}
            step={f.step || 1}
            onChange={(e) => set(f.key, e.target.value)}
          />
          <b>
            {f.min != null && f.max != null ? `${f.min} ~ ${f.max}` : ''}
            {f.unit || ''}
          </b>
        </div>
      );
    }
    return (
      <div className="param-row">
        <span>{f.label || f.key}</span>
        <input className="p-input" value={v ?? ''} spellCheck={false} onChange={(e) => set(f.key, e.target.value)} />
        <b>{(f.help || '') + (f.unit || '')}</b>
      </div>
    );
  };

  return (
    <>
      <header className="page-head">
        <div>
          <h1>{d?.name || '插件详情'}</h1>
          <p>
            {d?.installed ? `已安装 v${d.version || '—'}` : '尚未安装'}
            {d?.kind ? ` · ${d.kind}` : ''}
            {d?.adapters?.length ? ` · 支持 ${d.adapters.join(' / ')}` : ''}
          </p>
        </div>
        <div className="page-head__right">
          <button type="button" className="btn btn--ghost" onClick={onBack}>
            返回插件列表
          </button>
        </div>
      </header>

      <section className="card card--wide">
        <h2 className="card__title">介绍</h2>
        <div className="stat-row">
          <span>价格</span>
          <b>{price == null ? '免费' : `¥${price}`}</b>
        </div>
        <div className="stat-row">
          <span>拥有状态</span>
          <b>{price == null || owned || isFull(ent) ? '可以直接安装' : '需要先开通'}</b>
        </div>
        <p className="card__note">{d?.description || '（这个插件没有写介绍）'}</p>
        {price == null ? (
          <p className="card__note">
            这是<b>免费插件</b>：点下面「安装这个插件」直接装，装完重启一次机器人即可用。
            也可以在官网「插件市场」（astroswarm.cn/plugins.html）下载 zip。
          </p>
        ) : owned ? (
          <p className="card__note">
            这个插件已经登记在你账号下：点「安装这个插件」即可，重启机器人后生效；
            官网「插件市场」里它也会显示「已拥有」，随时能重新下载。
          </p>
        ) : (
          <>
            <div className="p-row">
              {buyUrl && (
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={() => window.open(buyUrl, '_blank')}
                >
                  {'去账号中心开通'}
                </button>
              )}
              <button type="button" className="btn" disabled={busy} onClick={refreshEnt}>
                已开通，刷新权益
              </button>
            </div>
            <p className="card__note">
              开通入口在账号中心（astroswarm.cn）：填<b>你的星群账号邮箱</b>，
              开通后点「已开通，刷新权益」，一般几秒内生效。
            </p>
            <div className="p-row">
              <input
                className="p-input"
                value={code}
                placeholder="兑换码（XXXX-XXXX-XXXX-XXXX）"
                spellCheck={false}
                onChange={(e) => setCode(e.target.value)}
              />
              <button type="button" className="btn" disabled={busy} onClick={redeem}>
                兑换
              </button>
            </div>
            <p className="card__note">
              兑换码是<b>人工兜底</b>用的：开通后权益没自动同步过来（比如账号邮箱填错了），
              找我要一个码填在这里兑换即可。
            </p>
          </>
        )}
        {!d?.installed && (
          <div className="p-row">
            <button type="button" className="btn btn--primary" onClick={installPack}>
              安装这个插件
            </button>
          </div>
        )}
      </section>

      {Boolean(d?.features?.length) && (
        <section className="card card--wide">
          <h2 className="card__title">功能</h2>
          <div className="p-list">
            {d.features.map((f) => (
              <div className="p-item param-feature" key={f.title}>
                {`${f.title}：${f.desc}`}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="card card--wide">
        <h2 className="card__title">参数设置</h2>
        <p className="card__note">
          {d?.installed
            ? '改完点保存，立刻写进服务器；主动消息按这些数值判断（概率 / 间隔 / 互动窗口 / 未回上限 / 免打扰 / 限速）。'
            : '这个插件还没安装，安装后才能改参数。'}
        </p>
        {fields.length === 0 && <p className="card__note">这个插件没有可调参数。</p>}
        {fields.map((f) => (
          <div key={f.key}>{field(f)}</div>
        ))}
        {fields.length > 0 && (
          <div className="p-row">
            <button
              type="button"
              className="btn btn--primary"
              disabled={!installed || busy || !changed.length}
              onClick={save}
            >
              {busy ? '保存中…' : changed.length ? `保存参数（${changed.length} 项改动）` : '保存参数'}
            </button>
            <button type="button" className="btn btn--ghost" onClick={load}>
              重新读取
            </button>
          </div>
        )}
      </section>

      {msg && <div className="toast">{msg}</div>}
    </>
  );
}

function Plugins({ auth, onDetail = () => {} }) {
  const [entries, setEntries] = useState([]);
  const [packs, setPacks] = useState([]);
  const [status, setStatus] = useState('正在加载插件商店...');
  const [category, setCategory] = useState('');
  const [picked, setPicked] = useState('');
  const [packId, setPackId] = useState('');
  const [pyPackage, setPyPackage] = useState('');
  const [zipPath, setZipPath] = useState('');
  // 已登记的插件 id（列表里标「✓已拥有」，并让它们可安装）
  const [ownedPlugins, setOwnedPlugins] = useState([]);
  const [qweather, setQweather] = useState(false);
  const [msg, setMsg] = useState('');
  // 开发者模式（后端 /api/console/dev-mode，存服务器 config_home/console.json）：
  // 关着时 PyPI 那行输入与按钮禁用，跟桌面端 plugin 页的规则一致。
  const [devMode, setDevMode] = useState(false);
  const [pkgBusy, setPkgBusy] = useState(false);
  const [pkgStage, setPkgStage] = useState('');
  // /api/plugins/installed：已装插件、本地插件目录、pyproject 记录的商店插件
  const [localInfo, setLocalInfo] = useState({ installed: [], local: [], store: [], dir: '' });
  const [deps, setDeps] = useState(null);

  const loadLocal = () => {
    get('/api/plugins/installed')
      .then((d) => setLocalInfo(d))
      .catch((e) => fail(e, '本地插件清单'));
  };

  /* 未登录时这一页的四块数据全都读不到（/api/tools/status、/api/plugins/entitlement、
     /api/plugins/installed 都鉴权）。以前每处都是 .catch(() => {})，静默吞掉：
     表现是「已装能力包空列表」「插件全显示未开通」，用户以为功能没了。
     现在统一记一句实话，并在对应卡片上显示，不再把「没登录」装成「没有数据」。 */
  const [needLogin, setNeedLogin] = useState(false);
  const fail = (e, what) => {
    if (isAuthError(e)) {
      setNeedLogin(true);
      return;
    }
    setMsg(`${what}读取失败：${e.message}`);
  };

  const loadPacks = () => {
    get('/api/tools/status')
      .then((d) => setPacks((d.installed || []).filter((p) => p.kind !== 'persona-pack')))
      .catch((e) => fail(e, '已装能力包'));
  };

  const load = () => {
    setStatus('正在加载插件商店...');
    Promise.all([
      get('/api/plugins').then((d) => d.plugins || []).catch(() => []),
      get('/api/tools/market').then((d) => d.packs || []).catch(() => []),
    ])
      .then(([plugins, toolPacks]) => {
        const list = [...plugins, ...toolPacks];
        setEntries(list);
        if (!list.length) {
          setStatus('插件商店暂不可用或暂无内容，可稍后点「刷新」重试');
          return;
        }
        // 「当前账号」按 member 判；没有权益的账号写「未开通」
        const plan = auth?.email ? (isMember(auth) ? '已开通' : '未开通') : '未登录星群账号（插件不受影响）';
        const locked = list.filter((e) => tier(e) !== 'free').length;
        setStatus(
          `插件商店已加载：${list.length} 个 · 当前账号：${plan}` + (locked ? ` · ${locked} 个需开通` : ''),
        );
      })
      .catch((e) => setStatus(`插件商店加载失败：${e.message}（可点「刷新」重试）`));
  };

  useEffect(() => {
    load();
    loadPacks();
    loadLocal();
    get('/api/console/dev-mode')
      .then((d) => setDevMode(Boolean(d.developer_mode)))
      .catch((e) => fail(e, '开发者模式'));
    // 已登记的插件：以前只认开通标记，会被判成「没权限」装不上
    get('/api/plugins/entitlement')
      .then((d) => setOwnedPlugins((d.owned_plugins || []).map(String)))
      .catch((e) => fail(e, '已购插件权益'));
  }, []);

  const tier = (e) => String(e.tier || 'free').toLowerCase();
  const isOwned = (e) => ownedPlugins.includes(String(e.id));
  const allowed = (e) => tier(e) === 'free' || isFull(auth) || isOwned(e);
  const categories = [...new Set(entries.map((e) => e.category || '未分类'))].sort();
  const shown = category ? entries.filter((e) => (e.category || '未分类') === category) : entries;

  const install = async () => {
    const entry = entries.find((e) => String(e.id) === picked);
    if (!entry) {
      setMsg('请先在插件商店选择一个插件');
      return;
    }
    if (!allowed(entry)) {
      setMsg(`「${entry.name}」需要先在账号中心开通，开通后再点安装`);
      return;
    }
    try {
      // 能力包走 /api/tools/install，普通插件走 /api/plugins/install（桌面端是同一份列表）
      await post(entry.kind && entry.kind !== 'plugin' ? '/api/tools/install' : '/api/plugins/install', {
        id: entry.id,
      });
      setMsg('已安装，重启机器人生效');
      loadPacks();
    } catch (e) {
      setMsg(withAuthHint(e));
    }
  };

  // 开发者模式：从 PyPI 装插件。后端是后台线程 + 轮询（pip 可能跑几分钟），
  // 所以这里提交完就轮询 /api/deps/status，把最后一行输出当进度显示。
  const installPyPI = async () => {
    const name = pyPackage.trim();
    if (!name) {
      setMsg('先填 PyPI 包名，例如 nonebot-plugin-status');
      return;
    }
    if (!devMode) {
      setMsg('开发者模式没开：先去「设置 → 启动行为」打开（后果自负）');
      return;
    }
    setPkgBusy(true);
    setPkgStage('正在提交安装…');
    setMsg(`正在安装 ${name}…`);
    try {
      await post('/api/plugins/install-pypi', { package: name });
      for (let i = 0; i < 400; i += 1) {
        const st = await get('/api/deps/status');
        const last = (st.log || []).slice(-1)[0];
        if (last) setPkgStage(last);
        if (!st.running) {
          if (st.error) {
            setMsg(`${name} 安装失败。下面是安装命令的输出，出问题时把这段发给开发者：${st.error}`);
          } else {
            setMsg(`${name} 装好了（已写进机器人 pyproject），重启机器人后生效`);
            setPyPackage('');
            loadLocal();
          }
          break;
        }
        await new Promise((r) => setTimeout(r, 1500));
      }
    } catch (e) {
      setMsg(withAuthHint(e));
    } finally {
      setPkgBusy(false);
      setPkgStage('');
    }
  };

  const uninstallPack = async () => {
    if (!packId) {
      setMsg('请先在「已装能力包」里选一个');
      return;
    }
    // 卸载不可撤销：删掉的是 <数据目录>/tool_packs/<id>，连同用户调过的参数一起没了
    if (!window.confirm(`确定卸载「${packId}」？\n该能力包的配置与参数会一起删除，不能撤销。`)) return;
    try {
      await post('/api/tools/uninstall', { id: packId });
      setMsg('已卸载');
      loadPacks();
    } catch (e) {
      setMsg(withAuthHint(e));
    }
  };

  const restartBot = async () => {
    if (!window.confirm('确定重启机器人？\n大约 10 秒内 QQ / 微信 会短暂离线，正在进行的对话会中断。')) return;
    try {
      await post('/api/services/restart', { service: 'bot' });
      setMsg('已发送重启指令，NoneBot 起来后新插件才生效');
    } catch (e) {
      setMsg(withAuthHint(e));
    }
  };

  // 桌面端「重装缺失依赖」：先扫一遍，真有缺失再装
  const reinstallDeps = async () => {
    setMsg('正在扫描插件依赖…');
    try {
      const scanned = await runDeps('scan', (st) => setDeps(st));
      if (!scanned.missing || !scanned.missing.length) {
        setMsg(`依赖齐全（共检查 ${scanned.checked} 项）`);
        return;
      }
      setMsg(`缺 ${scanned.missing.length} 项，开始安装…`);
      const done = await runDeps('install', (st) => setDeps(st));
      setMsg(`依赖安装完成（成功 ${(done.installed || []).length} 项），建议重新扫描验证`);
    } catch (e) {
      setMsg(withAuthHint(e));
    }
  };

  const disabled = '无头端暂不支持，请先在桌面端操作';
  const todo = (what) => setMsg(`${what}：${disabled}`);

  return (
    <>
      <header className="page-head">
        <div>
          <h1>插件管理</h1>
          <p>插件商店（直连星群服务器）与本地插件管理；第三方插件安装默认关闭，可在「设置 → 开发者模式」开启（后果自负）。</p>
        </div>
      </header>

      <div className="pl-row">
        <section className="card pl-panel">
          <h2 className="card__title">插件商店</h2>
          <p className="card__note">
            直连星群服务器拉取插件清单；安装前自动校验适配器兼容性与 SHA256。插件全部免费、源码开源，直接装即可。
          </p>

          <div className="p-row">
            <span>分类</span>
            <select className="p-select" value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">全部分类</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <button type="button" className="btn btn--ghost" onClick={load}>
              刷新
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              title="去官网插件市场看介绍与下载（astroswarm.cn/plugins.html）"
              onClick={() => {
                window.open('https://astroswarm.cn/plugins.html', '_blank', 'noopener');
                setMsg('已打开插件市场：装插件直接用左边的列表，这里只是去看介绍和下载 zip');
              }}
            >
              插件市场
            </button>
            <button type="button" className="btn btn--primary" onClick={install}>
              安装
            </button>
          </div>

          <div className="p-list p-list--134">
            {shown.map((e) => (
              <div className="p-item-row" key={String(e.id)}>
                <button
                  type="button"
                  className={picked === String(e.id) ? 'p-item p-item--on' : 'p-item'}
                  style={{ color: allowed(e) ? PLUGIN_ITEM_COLOR[tier(e)] || '#22D3EE' : '#94A3B8' }}
                  onClick={() => setPicked(String(e.id))}
                  title={e.description || ''}
                >
                  {`[${PLUGIN_TIER_LABEL[tier(e)] || '免费'}] ${e.name}  v${e.version}  [${e.category || '未分类'}]  免费${isOwned(e) ? '  ✓已拥有' : ''}`}
                </button>
                <button
                  type="button"
                  className="btn btn--ghost p-item__more"
                  title="看这个插件的介绍、功能和可调参数"
                  onClick={() => onDetail(String(e.id), e)}
                >
                  详情
                </button>
              </div>
            ))}
          </div>

          <p className="card__note">{status}</p>
          {needLogin && (
            <p className="card__note">
              {LOGIN_HINT}：下面「已装能力包 / 已安装 / 本地插件」三块都会是空的，
              需要开通的插件也读不到开通状态 —— 不是这些插件不存在。
            </p>
          )}
          <p className="card__note">已装能力包</p>

          <div className="p-row">
            <div className="p-list p-list--72">
              {packs.map((p) => (
                <div className="p-item-row" key={String(p.id)}>
                  <button
                    type="button"
                    className={packId === String(p.id) ? 'p-item p-item--on' : 'p-item'}
                    onClick={() => setPackId(String(p.id))}
                  >
                    {`${p.name}  v${p.version}`}
                  </button>
                  <button
                    type="button"
                    className="btn btn--ghost p-item__more"
                    title="看介绍、功能与可调参数"
                    onClick={() => onDetail(String(p.id))}
                  >
                    详情
                  </button>
                </div>
              ))}
            </div>
            {/* 这个「配置」原来在没选中任何能力包时会 onDetail('')：详情页 pid 为空 →
                 load() 里 if (!pid) return → 进到一个只有标题、价格「免费」和
                「这个插件没有写介绍」的空白页，没有任何错误提示。
                现在先拦住，并说清楚要先选一个。 */}
            <button
              type="button"
              className="btn btn--ghost"
              title="先在左边「已装能力包」里选一个，再点这里看它的可调参数"
              onClick={() => {
                if (!packId) {
                  setMsg('先在左边「已装能力包」里选一个，再点「配置」');
                  return;
                }
                if (packId === 'qweather') {
                  setQweather((v) => !v);
                  return;
                }
                onDetail(packId);
              }}
            >
              配置
            </button>
            <button type="button" className="btn btn--ghost" onClick={uninstallPack}>
              卸载
            </button>
          </div>

          <p className="card__note">开发者模式：从 PyPI 安装任意 NoneBot 插件（不推荐，兼容与合规由用户自负）</p>

          <div className="p-row">
            <input
              className="p-input"
              value={pkgBusy && pkgStage ? pkgStage : pyPackage}
              placeholder={devMode ? 'PyPI 包名，如 nonebot-plugin-status' : 'PyPI 包名（需先开开发者模式）'}
              spellCheck={false}
              disabled={!devMode || pkgBusy}
              onChange={(e) => setPyPackage(e.target.value)}
            />
            <button
              type="button"
              className="btn btn--primary"
              disabled={!devMode || pkgBusy}
              onClick={installPyPI}
            >
              安装
            </button>
          </div>

          <p className="card__note">已安装（pyproject 记录）</p>
          <div className="p-list p-list--115">
            {localInfo.store.map((name) => (
              <div className="p-item" key={name}>
                {name}
              </div>
            ))}
          </div>
        </section>

        <section className="card pl-panel">
          <h2 className="card__title">第三方插件（已限制）</h2>
          <p className="card__note">开发者模式开启后可安装第三方 zip；插件兼容性、安全性、平台协议合规由用户自行承担。</p>

          <ZipInstall />
        </section>
      </div>

      {qweather && <QWeatherCard />}

      <section className="card card--strong pl-local">
        <h2 className="card__title">本地插件（src/plugins）</h2>
        <div className="p-list p-list--72">
          {localInfo.local.map((name) => (
            <div className="p-item" key={name}>
              {`${name}${localInfo.installed.some((p) => p.id === name) ? '' : '（无 plugin.json）'}`}
            </div>
          ))}
        </div>
        {needLogin && <p className="card__note">{LOGIN_HINT}：本地插件清单读不到。</p>}
        <div className="p-row">
          <button type="button" className="btn" onClick={reinstallDeps}>
            重装缺失依赖
          </button>
          <button type="button" className="btn" onClick={loadLocal}>
            刷新列表
          </button>
          <button
            type="button"
            className="btn"
            title={localInfo.dir || '插件目录'}
            onClick={() => copyServerPath(setMsg, '插件目录', pluginsDirPath)}
          >
            复制插件目录
          </button>
          <span className="p-gap" />
          <button type="button" className="btn btn--primary" onClick={restartBot}>
            重启 NoneBot 生效
          </button>
        </div>
      </section>

      {/* 「安装任务」原来是一张只有标题的空卡片。改成本地/后台任务的真状态：
          这一页发起的「重装缺失依赖」与「PyPI 安装」都会写 /api/deps/status，
          进度与最后一行输出就在这里显示，不用再去「依赖」页看。 */}
      <section className="card pl-tasks">
        <h2 className="card__title">安装任务</h2>
        <p className="card__note">
          {pkgBusy
            ? `正在从 PyPI 安装：${pkgStage || '准备中…'}`
            : deps && deps.running
              ? `后台任务进行中：${deps.stage || '执行中…'}`
              : deps && deps.error
                ? `上次任务失败：${deps.error}`
                : deps && Array.isArray(deps.missing) && deps.checked
                  ? `上次检查 ${deps.checked} 项依赖，缺失 ${deps.missing.length} 项`
                  : '当前没有正在执行的安装任务。点上面「重装缺失依赖」或在插件商店安装后，进度会显示在这里。'}
        </p>
      </section>

      {msg && <div className="toast">{msg}</div>}
    </>
  );
}

/* 日志：与桌面端 logs_page.py 1:1。
   实测：玻璃面板内边距 12/16/14、间距 6；过滤行 = 来源标签/下拉(100) + addSpacing(12) +
   级别标签/下拉(88) + 撑开 + 打开日志目录(108) + 清空视图(82)（按钮间 6）。
   日志视图：等宽 12px、底 rgba(8,11,18,.72)、1px rgba(255,255,255,.08)、圆角 10、内边距 10、色 #C6D0E0。
   行格式与桌面端一致：`[HH:MM:SS] [来源][级别] 正文`；级别按桌面端 _infer_level 的同一套关键词推断。
   数据源：桌面端是「任务/管理器信号 + NoneBot 日志文件尾部」，无头端一条 SSE 对一个文件
   （/api/logs/stream?name=headless 跟无头端自己的进程访问日志，?name=nonebot 跟机器人日志）。
   来源下拉原来有「任务 / 管理器 / NoneBot」三项，但流里每一行都被硬编码成
   「管理器」，选「任务」「NoneBot」永远是空面板 —— 属于点了没用的假筛选项。
   后端已补上 ?name=nonebot（logs.LOG_FILES 白名单，只收名字不收路径），
   于是「NoneBot」这一项现在有真实数据了，重新加回来。 */
const LOG_SOURCES = ['全部', '管理器', 'NoneBot'];
/* 来源 → 后端日志名（logs.LOG_FILES 的键）。名字写死在这里，页面上永远给不出路径。 */
const LOG_STREAM_NAMES = { 管理器: 'headless', NoneBot: 'nonebot' };
const LOG_LEVELS = ['全部', 'INFO', 'OK', 'WARN', 'ERROR'];

function inferLevel(line) {
  const low = line.toLowerCase();
  if (low.includes('error') || low.includes('traceback') || low.includes('exception') || low.includes('failed')) {
    return 'ERROR';
  }
  if (low.includes('warn')) return 'WARN';
  if (low.includes('success') || low.includes('ok') || line.includes('完成')) return 'OK';
  return 'INFO';
}

function Logs({ loggedIn = true }) {
  const [entries, setEntries] = useState([]);
  const [source, setSource] = useState('全部');
  const [level, setLevel] = useState('全部');
  const [msg, setMsg] = useState('');
  // 流的状态：'' 正常；否则是一句给用户看的实话（未登录 / 断开）
  const [streamNote, setStreamNote] = useState('');
  const boxRef = useRef(null);

  useEffect(() => {
    const stamp = () => new Date().toTimeString().slice(0, 8);
    const push = (msgs, src) => {
      const rows = msgs
        .map((m) => String(m).replace(/\x1b\[[0-9;]*m/g, '').trimEnd())
        .filter((m) => m.trim())
        .map((m) => ({ t: stamp(), source: src, level: inferLevel(m), msg: m }));
      if (!rows.length) return;
      setEntries((prev) => [...prev, ...rows].slice(-8000));
    };

    // 未登录时后端 _require_auth 直接 401：EventSource 会静默失败，
    // 页面上只剩一个永远空的黑框。这里先判登录态，别白试一次。
    if (!loggedIn) {
      setStreamNote(`${LOGIN_HINT}。实时日志带 AI key / 微信 token / 对话内容，必须登录才能看。`);
      return undefined;
    }

    /* 每个来源一条 SSE：「全部」= 两条流都在跑，每行按自己那条流打来源标记，
       于是「来源」筛选变成纯前端过滤，选哪一项都有真数据。
       后端用 ?name= 选文件（白名单，只收名字不收路径），这里传的就是上面那张表里的常量。 */
    const streams = Object.entries(LOG_STREAM_NAMES).map(([src, name]) => {
      const es = new EventSource(authUrl(`/api/logs/stream?name=${encodeURIComponent(name)}`));
      es.onopen = () => setStreamNote('');
      es.onmessage = (ev) => push(String(ev.data || '').split('\n'), src);
      /* 没有 onerror 时用户看到的就是「卡住的黑框」：token 过期（401）、服务重启、
         或后端 10 分钟主动结束连接（logs.afollow 的 max_seconds）都会走到这里。
         浏览器会自己按 EventSource 的规则重连，所以文案说「正在自动重连」。 */
      es.onerror = () => {
        setStreamNote(
          `${src} 日志流已断开，浏览器正在自动重连；如果一直连不上，多半是登录态过期了 —— 重新登录后再回本页。`,
        );
      };
      return es;
    });
    return () => streams.forEach((es) => es.close());
  }, [loggedIn]);

  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [entries]);

  const shown = entries.filter(
    (e) => (source === '全部' || e.source === source) && (level === '全部' || e.level === level),
  );

  return (
    <>
      <header className="page-head">
        <div>
          <h1>日志</h1>
          <p>管理器（无头端）与 NoneBot（机器人）两路日志实时推送；可按来源与级别筛选。</p>
        </div>
      </header>

      <section className="card card--strong log-panel">
        <div className="log-bar">
          <span>来源</span>
          <select className="log-select log-select--src" value={source} onChange={(e) => setSource(e.target.value)}>
            {LOG_SOURCES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <span className="log-bar__gap">级别</span>
          <select className="log-select log-select--lv" value={level} onChange={(e) => setLevel(e.target.value)}>
            {LOG_LEVELS.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
          <span className="log-bar__spacer" />
          <button
            type="button"
            className="btn"
            title="无头端没有本地文件管理器：点这里把日志文件下载下来（按当前「来源」选文件；来源为「全部」时下载管理器的日志）"
            onClick={() => {
              // 下载接口同样 _require_auth：未登录时开新标签页只会得到一个 401 空白页
              if (!loggedIn) {
                setMsg(`${LOGIN_HINT}（下载日志文件也需要鉴权）`);
                return;
              }
              const name = LOG_STREAM_NAMES[source] || LOG_STREAM_NAMES['管理器'];
              window.open(authUrl(`/api/logs/download?name=${encodeURIComponent(name)}`), '_blank');
            }}
          >
            下载日志文件
          </button>
          <button type="button" className="btn" onClick={() => setEntries([])}>
            清空视图
          </button>
        </div>

        {streamNote && <p className="card__note log-note">{streamNote}</p>}

        <textarea
          className="log-view"
          ref={boxRef}
          readOnly
          spellCheck={false}
          value={shown.map((e) => `[${e.t}] [${e.source}][${e.level}] ${e.msg}`).join('\n')}
        />

        {/* 有日志但筛没了，要说清楚是筛选的问题，不是「日志没了」 */}
        {!streamNote && entries.length > 0 && shown.length === 0 && (
          <p className="card__note log-note">当前筛选（来源「{source}」· 级别「{level}」）没有匹配的日志，把筛选放宽试试。</p>
        )}
      </section>

      {msg && <div className="toast">{msg}</div>}
    </>
  );
}

const PERSONA_PRESETS = {
  星群助手:
    '你是星群（AstroSwarm）的 AI 助手，负责跨平台对话与记忆管理。回答保持简洁直接，情绪随心情波动，回答长短看情况，只给关键信息，不啰嗦。',
};

/* ------------------------------------------------------------------ AI 大脑
   与桌面端 brain_page.py 1:1：
   - 小白模式（默认）只显示「接口配置 + 人设与主动聊天 + 底部空态」；
     桌面端 BrainPage.set_beginner() 同样把 智能体档案 / 人设工坊 / 记忆与 MCP
     三块 setVisible(False)，并隐藏「飞书 / 纸飞机」两个平台开关。
   - 卡片内间距实测 10（不是 6），行内「标签→控件」间距 10，标签宽度按文字自适应。
   - 保存：桌面端一个「保存 AI 配置」按钮统一写接口 + 人设 + 主动聊天；
     无头端 /api/config 目前只认 ai_provider / ai_base_url / ai_model / ai_api_key，
     人设走 /api/ai/personality，其余项等后端补齐（先按 UI 对齐）。 */
const AI_PROVIDERS = [
  ['custom', '自定义接口', '', ''],
  ['deepseek', 'DeepSeek', 'https://api.deepseek.com', 'deepseek-v4-flash'],
  ['dashscope', '通义千问（百炼）', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen3.7-flash'],
  ['zhipu', '智谱 GLM', 'https://open.bigmodel.cn/api/paas/v4', 'glm-5.2'],
  ['moonshot', 'Kimi（Moonshot）', 'https://api.moonshot.cn/v1', 'kimi-k3'],
  ['openai', 'OpenAI', 'https://api.openai.com/v1', 'gpt-5.6'],
];
const AGENT_PROFILES = [
  ['star_helper', '星群助手'],
  ['liqinghan', '李清菡'],
];
// 桌面端 _spin()：label 在上、QSpinBox 在下的定宽（118）小格，3 列 × 2 行
const SPIN_LABELS = {
  ai_interval_min: '间隔最小(分)',
  ai_interval_max: '间隔最大(分)',
  ai_cooldown: '冷却(分)',
  ai_quiet_start: '免打扰开始(时)',
  ai_quiet_end: '免打扰结束(时)',
};
// 桌面端 Settings 里已有、但无头端 /api/config 还没接的项：先给同款默认值，UI 与桌面端一致
const BRAIN_DEFAULTS = {
  ai_provider: 'custom',
  ai_base_url: '',
  ai_model: '',
  ai_api_key: '',
  ai_platforms: { qq: true, wechat: true, feishu: true, telegram: true },
  agent_profile_enabled: false,
  agent_profile_id: 'star_helper',
  agent_wake_words: '',
  agent_wake_auto: true,
  agent_owner_openid: '',
  vision_api_url: '',
  vision_model: '',
  vision_api_key: '',
  ai_proactive: false,
  ai_proactive_targets: '',
  ai_proactive_groups: '',
  ai_interval_min: 30,
  ai_interval_max: 90,
  ai_cooldown: 30,
  ai_quiet_start: 0,
  ai_quiet_end: 8,
  memory_enabled: true,
  mcp_enabled: false,
  mcp_servers: {},
};

function AiBrain({ config, onSaved, beginner, loggedIn = true }) {
  const [form, setForm] = useState(null);
  const [personality, setPersonality] = useState('');
  const [msg, setMsg] = useState('');
  const [installed, setInstalled] = useState(false);
  /* 记忆 / 身份绑定的真实数量。以前这一块三行写死 0 条 / 0 个用户 / 0 组绑定，
     无论机器人里有多少记忆都显示 0 —— 数据其实一直有：GET /api/stats/summary 返回
     memory_global / memory_users / identity_binds（首页「运行数据」用的就是它）。
     未登录时该接口 401，退回「—」并给一句实话，不编数字。 */
  const [stats, setStats] = useState(null);
  const [personas, setPersonas] = useState([]);
  const [personaSel, setPersonaSel] = useState('');
  const [personaBusy, setPersonaBusy] = useState(false);
  const [guide, setGuide] = useState('');            // 非空 = 就地展开模板说明
  const [importPanel, setImportPanel] = useState(false);
  const [importText, setImportText] = useState('');
  const [importName, setImportName] = useState('');
  const [mcpText, setMcpText] = useState('{}');
  /* MCP 状态必须走专用接口 /api/mcp/config（返回 {ok, mcp:{enabled,servers}}）。
     以前从 /api/config 读 mcp_enabled / mcp_servers，而后端 headless_config 的
     DEFAULTS / SAFE_KEYS 根本没有这两个键 → 永远 undefined → 保存时 !!undefined 恒 false，
     用户只是改了模型名，已开启的 MCP 就被静默关掉（界面上的服务器框也永远是 {}）。
     mcpBase：null = 还没读到；false = 读不到（未登录/接口不可用）—— 读不到就绝不写 MCP。 */
  const [mcpBase, setMcpBase] = useState(null);
  // 用户是否真的动过 MCP 控件（勾选框 / JSON 框）；没动过就不提交，避免无谓写入
  const [mcpTouched, setMcpTouched] = useState(false);
  const [wakeBusy, setWakeBusy] = useState(false);
  const personaFileRef = useRef(null);

  useEffect(() => {
    get('/api/ai/personality')
      .then((d) => setPersonality(d.personality || ''))
      .catch((e) => setMsg(String(e.message)));
  }, []);

  useEffect(() => {
    get('/api/mcp/config')
      .then((d) => {
        const m = (d && d.mcp) || {};
        setMcpBase({
          enabled: Boolean(m.enabled),
          servers: (m.servers && typeof m.servers === 'object') ? m.servers : {},
        });
      })
      .catch(() => setMcpBase(false));
  }, []);

  useEffect(() => {
    if (form === null && config) {
      const merged = { ...BRAIN_DEFAULTS, ...config };
      setForm(merged);
      setMcpText(JSON.stringify(merged.mcp_servers || {}, null, 2));
    }
  }, [config, form]);

  // MCP 基线读到后回填表单（用户已经动过 MCP 控件就不覆盖他改的值）
  const formReady = form !== null;
  useEffect(() => {
    if (!formReady || !mcpBase || mcpTouched) return;
    setForm((cur) => ({ ...cur, mcp_enabled: mcpBase.enabled, mcp_servers: mcpBase.servers }));
    setMcpText(JSON.stringify(mcpBase.servers || {}, null, 2));
  }, [formReady, mcpBase, mcpTouched]);

  useEffect(() => {
    get('/api/tools/status')
      .then((d) => {
        const list = d.installed || [];
        // 桌面端判据是 (plugins_dir / "ai").is_dir()；无头端取工具包列表里的 ai
        setInstalled(list.some((p) => String(p.id || '').toLowerCase() === 'ai'));
      })
      .catch(() => {});
  }, []);

  // 记忆 / 身份绑定数量：跟首页「运行数据」同一份真数据（未登录就别发这个必 401 的请求）
  useEffect(() => {
    if (!loggedIn) {
      setStats(null);
      return undefined;
    }
    let alive = true;
    get('/api/stats/summary')
      .then((d) => { if (alive) setStats(d); })
      .catch(() => { if (alive) setStats(null); });
    return () => { alive = false; };
  }, [loggedIn]);

  /* -------------------------------------------------------- 人设工坊（本地）
     后端 /api/persona/* 直接包桌面端的 qbotmanager.core.persona_workshop：
     同一个 <数据目录>/personas，同一套人格卡格式，启用后写机器人人格 + 关智能体档案。
     列表的增删改都走真接口，不再弹「桌面端功能」。 */
  const refreshPersonas = async (keepSel) => {
    try {
      const d = await get('/api/persona/list');
      const list = d.items || [];
      setPersonas(list);
      setPersonaSel((cur) => {
        const want = keepSel || cur;
        if (want && list.some((p) => p.id === want)) return want;
        const active = list.find((p) => p.active);
        return (active || list[0] || {}).id || '';
      });
      return list;
    } catch (e) {
      setMsg(`人设列表读取失败：${e.message}`);
      return [];
    }
  };

  useEffect(() => { refreshPersonas(); }, []);

  const personaName = (p) => (p && (p.name || p.id)) || '';

  const importPersonaPayload = async (payload) => {
    setPersonaBusy(true);
    try {
      const d = await post('/api/persona/import', payload);
      setImportPanel(false);
      setImportText('');
      setImportName('');
      await refreshPersonas(d.id);
      setMsg(`人设已导入：${d.name || d.id}（${d.id}），选中后点「启用」；启用后重启机器人生效。`);
    } catch (e) {
      setMsg(`导入失败：${e.message}`);
    } finally {
      setPersonaBusy(false);
    }
  };

  const onPickPersonaFile = (file) => {
    if (!file) return;
    // 浏览器读文件：文本类（json/md）直接读文本，zip 读成 base64 ——
    // 后端不用 multipart（无头端依赖里没有 python-multipart），统一收 JSON 正文。
    const isZip = /\.zip$/i.test(file.name);
    const reader = new FileReader();
    const done = new Promise((resolve, reject) => {
      reader.onerror = () => reject(new Error('文件读取失败'));
      reader.onload = () => resolve(String(reader.result || ''));
    });
    if (isZip) reader.readAsDataURL(file);
    else reader.readAsText(file, 'utf-8');
    done.then((raw) => importPersonaPayload(isZip
      ? { filename: file.name, content_b64: raw.split(',')[1] || '' }
      : { filename: file.name, content: raw, name: importName }))
      .catch((e) => setMsg(`导入失败：${e.message}`));
  };

  const activatePersona = async () => {
    if (!personaSel) {
      setMsg('请先在人设列表里选中一个本地人设');
      return;
    }
    setPersonaBusy(true);
    try {
      const d = await post('/api/persona/activate', { id: personaSel });
      if (d.personality !== undefined) setPersonality(d.personality);
      set({ agent_profile_enabled: false });   // 与桌面端一致：启用本地人设会关掉硬编码档案
      await refreshPersonas(personaSel);
      onSaved();
      setMsg(`已启用人设：${personaName(d) || personaSel}，重启机器人后生效。`);
    } catch (e) {
      setMsg(`启用失败：${e.message}`);
    } finally {
      setPersonaBusy(false);
    }
  };

  const deactivatePersona = async () => {
    setPersonaBusy(true);
    try {
      const d = await post('/api/persona/deactivate', {});
      if (d.personality !== undefined) setPersonality(d.personality);
      await refreshPersonas();
      setMsg('已停用本地人设，人格恢复内置默认，重启机器人后生效。');
    } catch (e) {
      setMsg(`停用失败：${e.message}`);
    } finally {
      setPersonaBusy(false);
    }
  };

  const uninstallPersona = async () => {
    const item = personas.find((p) => p.id === personaSel);
    if (!item) {
      setMsg('请先在人设列表里选中要卸载的人设');
      return;
    }
    // 卸载不可撤销：删的是 <数据目录>/personas/<id>，连同自带工具一起没
    if (!window.confirm(
      `确定卸载人设「${personaName(item)}」吗？\n该人设的文件与自带工具会被删除，不能撤销。`
    )) return;
    setPersonaBusy(true);
    try {
      await post('/api/persona/uninstall', { id: item.id, confirm: true });
      await refreshPersonas();
      setMsg(`人设已卸载：${personaName(item)}`);
    } catch (e) {
      setMsg(`卸载失败：${e.message}`);
    } finally {
      setPersonaBusy(false);
    }
  };

  const togglePersonaGuide = async () => {
    if (guide) {                 // 再点一次收起
      setGuide('');
      return;
    }
    try {
      const d = await get('/api/persona/guide');
      setGuide(d.text || '');
    } catch (e) {
      setMsg(`读取模板说明失败：${e.message}`);
    }
  };

  const f = form || BRAIN_DEFAULTS;
  const set = (patch) => setForm({ ...f, ...patch });
  const onProvider = (key) => {
    const p = AI_PROVIDERS.find((x) => x[0] === key) || AI_PROVIDERS[0];
    const patch = { ai_provider: key };
    if (p[2]) patch.ai_base_url = p[2];
    if (p[3]) patch.ai_model = p[3];
    set(patch);
  };

  const genWake = async () => {
    setWakeBusy(true);
    try {
      // 后端按人格文本判定并提取称呼（不调用外部模型，不产生费用，也不会再 404）。
      // 把界面上正在编辑的人格一起带过去，改完人格不用先保存也能生成。
      const d = await post('/api/ai/wake-words', {
        persona_mode: f.agent_persona_mode || '',
        personality,
      });
      if (d.words && d.words.length) set({ agent_wake_words: d.words.join(',') });
      setMsg(d.source === 'default'
        ? '人格文本里没提到称呼，已用默认唤醒词，可手动修改（保存后重启机器人生效）'
        : '唤醒词已生成，可手动修改（保存后重启机器人生效）');
    } catch (e) {
      setMsg(`唤醒词生成失败：${e.message}`);
    } finally {
      setWakeBusy(false);
    }
  };

  const save = async () => {
    try {
      let servers = f.mcp_servers || {};
      try {
        servers = JSON.parse(mcpText || '{}');
      } catch {
        setMsg('MCP 配置格式错误: MCP 配置必须是 JSON 对象，例如 {"名称": {...}}');
        return;
      }
      // 无头端 /api/config 只接这些键（与后端 SAFE_KEYS 对齐）。
      // 以前只 PUT 4 项，界面上改了的平台开关/智能体档案等 15+ 项被静默丢弃却提示「已保存」。
      const HEADLESS_CFG_KEYS = [
        'ai_provider', 'ai_base_url', 'ai_model', 'ai_api_key',
        'ai_platforms',
        'agent_profile_enabled', 'agent_profile_id', 'agent_owner_qq',
        'agent_groups', 'agent_address_words', 'agent_wake_words', 'agent_wake_auto',
        'vision_api_url', 'vision_api_key', 'vision_model',
      ];
      const payload = {};
      HEADLESS_CFG_KEYS.forEach((k) => {
        if (f[k] !== undefined) payload[k] = f[k];
      });
      const savedCfg = await put('/api/config', payload);
      setForm({ ...f, ...savedCfg, mcp_servers: servers });
      await put('/api/ai/personality', { personality });
      /* MCP 走专用接口（存进机器人侧读的那份 manager 文件）。
         写之前必须确认「读到了基线」：读不到（未登录 / 接口不可用）时一个字节都不写，
         否则就会重现「不写 MCP 却把写成 enabled:false」这种把配置改坏的问题。
         读到基线时也要真变了（或用户确实动过控件）才提交，保证保存不动服务器上的 MCP。 */
      const base = mcpBase || null;
      const serversChanged = !base || JSON.stringify(servers) !== JSON.stringify(base.servers || {});
      const enabledChanged = !base || Boolean(f.mcp_enabled) !== base.enabled;
      let mcpMsg = '';
      if (base) {
        if (mcpTouched || serversChanged || enabledChanged) {
          try {
            const r = await post('/api/mcp/save', { enabled: Boolean(f.mcp_enabled), servers });
            mcpMsg = `；MCP 已保存 ${r.servers} 个服务器`;
            setMcpBase({ enabled: Boolean(f.mcp_enabled), servers });
            setMcpTouched(false);
          } catch (e) {
            mcpMsg = `；MCP 保存失败：${e.message}`;
          }
        }
      } else if (mcpTouched) {
        mcpMsg = '；MCP 状态没读到，本次未改动服务器上的 MCP 配置（登录后重试）';
      }
      setMsg(
        `AI 配置已保存 ${Object.keys(payload).length} 项（模型 / 智能体档案 / 视觉）${mcpMsg}，重启机器人生效；` +
        '主动聊天与记忆等数值在「插件详情页」里改。'
      );
      setMcpText(JSON.stringify(servers, null, 2));
      onSaved();
    } catch (e) {
      setMsg(String(e.message));
    }
  };

  const headlessTodo = (what) => setMsg(
    `${what}：这是桌面端（Windows 版）的功能，无头端暂未接入 —— 记忆时间线、本地知识库请在桌面版里操作。`
  );
  const num = (key, lo, hi) => (
    <label className="num-item" key={key}>
      <span>{SPIN_LABELS[key]}</span>
      <input
        type="number"
        min={lo}
        max={hi}
        value={f[key]}
        onChange={(e) => set({ [key]: e.target.value === '' ? lo : Number(e.target.value) })}
      />
    </label>
  );

  return (
    <>
      <header className="page-head">
        <div>
          <h1>AI 大脑</h1>
          <p>内置 AI 大脑：QQ / 微信 / 飞书 / 纸飞机共享模型、记忆与工具；接口配置与平台开关在本页完成</p>
        </div>
      </header>

      {/* 顶部状态摘要：先回答"现在什么状态、下一步做什么"，细节都在下面的分区里 */}
      <section
        className="card"
        style={{
          marginBottom: 18,
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: '10px 16px',
          padding: '12px 16px',
        }}
      >
        <StatusBadge tone={f.ai_api_key ? 'running' : 'warn'}>
          {f.ai_api_key ? '模型已配置' : '还没填 API 密钥'}
        </StatusBadge>
        <span className="card__note" style={{ margin: 0 }}>
          模型 <b>{f.ai_model || '未配置'}</b>
          {' · 平台 '}
          {[
            ['qq', 'QQ'],
            ['wechat', '微信'],
            ['feishu', '飞书'],
            ['telegram', '纸飞机'],
          ]
            .map(([k, label]) => `${label}${f.ai_platforms?.[k] === false ? '✗' : '✓'}`)
            .join(' / ')}
          {' · 人格 '}
          <b>
            {f.agent_profile_enabled
              ? `智能体档案（${f.agent_profile_id || '默认'}）`
              : '内置人格'}
          </b>
        </span>
        {!f.ai_api_key && (
          <span className="card__note" style={{ margin: 0, color: '#f0b429' }}>
            → 先在下面「连接模型」里填 API 密钥，保存后重启机器人
          </span>
        )}
      </section>

      <section className="card card--strong card--brain">
        <h2 className="card__title">接口配置</h2>
        <p className="card__note">
          选择服务商自动填接口地址与默认模型（预设已按官方文档核对）；平台开关决定 AI
          在哪些平台生效，保存后重启机器人生效。
        </p>

        <div className="kv-row kv-row--platform">
          <span>平台启用</span>
          {[
            ['qq', 'QQ'],
            ['wechat', '微信'],
          ].map(([key, label]) => (
            <label className="check" key={key} title="关闭后 AI 大脑不再处理该平台的消息，但平台通道本身仍正常运行">
              <input
                type="checkbox"
                checked={Boolean((f.ai_platforms || {})[key])}
                onChange={(e) => set({ ai_platforms: { ...(f.ai_platforms || {}), [key]: e.target.checked } })}
              />
              <span>{label}</span>
            </label>
          ))}
          {!beginner &&
            [
              ['feishu', '飞书'],
              ['telegram', '纸飞机'],
            ].map(([key, label]) => (
              <label className="check" key={key}>
                <input
                  type="checkbox"
                  checked={Boolean((f.ai_platforms || {})[key])}
                  onChange={(e) => set({ ai_platforms: { ...(f.ai_platforms || {}), [key]: e.target.checked } })}
                />
                <span>{label}</span>
              </label>
            ))}
        </div>

        <div className="kv-row kv-row--wide">
          <span>服务商</span>
          <select
            value={f.ai_provider || 'custom'}
            onChange={(e) => onProvider(e.target.value)}
            title="DeepSeek / 通义 / 智谱 / Kimi / OpenAI 等大厂接口自动填地址与默认模型，也可选「自定义接口」手动填写"
          >
            {AI_PROVIDERS.map(([key, name]) => (
              <option key={key} value={key}>
                {name}
              </option>
            ))}
          </select>
        </div>

        <div className="kv-row kv-row--wide">
          <span>接口地址</span>
          <input
            value={f.ai_base_url ?? ''}
            placeholder="https://api.deepseek.com"
            spellCheck={false}
            onChange={(e) => set({ ai_base_url: e.target.value })}
          />
        </div>

        <div className="kv-row kv-row--wide">
          <span>模型</span>
          <input
            value={f.ai_model ?? ''}
            placeholder="deepseek-v4-flash"
            spellCheck={false}
            onChange={(e) => set({ ai_model: e.target.value })}
          />
        </div>

        <div className="kv-row kv-row--wide">
          <span>API 密钥</span>
          <input
            type="password"
            value={f.ai_api_key ?? ''}
            placeholder="sk-..."
            spellCheck={false}
            onChange={(e) => set({ ai_api_key: e.target.value })}
          />
        </div>

        <div className="btn-row">
          <button type="button" className="btn btn--primary" onClick={save}>
            保存 AI 配置
          </button>
        </div>
      </section>

      {!beginner && (
        <section className="card card--strong card--brain">
          <h2 className="card__title">智能体档案</h2>
          <p className="card__note">
            想让它按「李清菡 / EVA」这类预设运行就打开下面的开关；人格仍以上方人格设定为准。
          </p>

          <label className="check" title="开启后机器人按所选档案的功能层运行（李清菡：群管/语音/图片/游戏/记忆等）">
            <input
              type="checkbox"
              checked={Boolean(f.agent_profile_enabled)}
              onChange={(e) => set({ agent_profile_enabled: e.target.checked })}
            />
            <span>启用智能体档案（默认关闭）</span>
          </label>

          <div className="kv-row kv-row--wide">
            <span>档案选择</span>
            <select
              value={f.agent_profile_id || 'star_helper'}
              onChange={(e) => set({ agent_profile_id: e.target.value })}
              title="星群助手 = 默认行为；李清菡 = 完整功能层预设"
            >
              {AGENT_PROFILES.map(([key, name]) => (
                <option key={key} value={key}>
                  {name}
                </option>
              ))}
            </select>
          </div>

          <details style={{ marginTop: 12 }}>
            <summary
              style={{
                cursor: 'pointer',
                fontSize: 13,
                opacity: 0.7,
                padding: '6px 0',
              }}
            >
              高级设置：唤醒词 · 绑定账号 · 视觉模型（默认收起）
            </summary>
            <p className="card__note" style={{ marginTop: 8 }}>
              唤醒词用于群聊无 @ 唤醒（私聊不需要）；QQ 群不 @ 也回复，需要群主开启「获取群内全部消息」后才会推送。
            </p>

          <div className="kv-row kv-row--wide">
            <span>唤醒词</span>
            <input
              value={f.agent_wake_words ?? ''}
              placeholder="逗号分隔，如：李清菡,学姐,菡姐,菡菡（留空 = 档案默认）"
              spellCheck={false}
              onChange={(e) => set({ agent_wake_words: e.target.value })}
            />
            <button
              type="button"
              className="btn btn--ghost"
              onClick={genWake}
              disabled={wakeBusy}
              title="用上方语言模型按人格文本生成唤醒词；未配置模型时自动按名字句式提取"
            >
              {wakeBusy ? '生成中…' : '按人格生成'}
            </button>
          </div>

          <label className="check">
            <input
              type="checkbox"
              checked={Boolean(f.agent_wake_auto)}
              onChange={(e) => set({ agent_wake_auto: e.target.checked })}
            />
            <span>人格变化时自动重新生成唤醒词（手动修改唤醒词后自动取消）</span>
          </label>

          <div className="kv-row kv-row--wide">
            <span>你同学 openid</span>
            <input
              value={f.agent_owner_openid ?? ''}
              placeholder="你的官方 openid（先用你的账号与机器人对话，从消息中心会话标识复制；留空 = 群管专属命令降级）"
              spellCheck={false}
              onChange={(e) => set({ agent_owner_openid: e.target.value })}
            />
          </div>

          <p className="card__note">视觉模型（图片描述/生成；密钥留空 = 不启用）</p>
          <div className="kv-row kv-row--wide">
            <span>视觉接口地址</span>
            <input
              value={f.vision_api_url ?? ''}
              placeholder="https://api.siliconflow.cn/v1"
              spellCheck={false}
              onChange={(e) => set({ vision_api_url: e.target.value })}
            />
          </div>
          <div className="kv-row kv-row--wide">
            <span>视觉模型</span>
            <input
              value={f.vision_model ?? ''}
              placeholder="Qwen/Qwen3-Omni-30B-A3B-Instruct"
              spellCheck={false}
              onChange={(e) => set({ vision_model: e.target.value })}
            />
          </div>
          <div className="kv-row kv-row--wide">
            <span>视觉 API 密钥</span>
            <input
              type="password"
              value={f.vision_api_key ?? ''}
              placeholder="sk-..."
              spellCheck={false}
              onChange={(e) => set({ vision_api_key: e.target.value })}
            />
          </div>
          </details>
        </section>
      )}

      {!beginner && (
        <section className="card card--strong card--brain">
          <h2 className="card__title">人设工坊（本地）</h2>
          <p className="card__note">
            上传自己的「人格卡 + 工具」人设包（和内置李清菡 / EVA 同一种模式）：先下载模板填写，再导入
            JSON 或 zip（也可以直接粘一段人设文字）；启用后写入人格并加载自带工具，保存重启机器人生效。启用本地人设会自动关闭上方智能体档案，避免双人格。
          </p>
          <div className="btn-row btn-row--6">
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => window.open(authUrl('/api/persona/template'), '_blank')}
            >
              下载模板
            </button>
            <button type="button" className="btn btn--ghost" onClick={togglePersonaGuide}>
              {guide ? '收起说明' : '模板说明'}
            </button>
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => setImportPanel((v) => !v)}
            >
              导入人设
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => refreshPersonas()}>
              刷新
            </button>
          </div>

          {importPanel && (
            <div className="kv-row kv-row--wide kv-row--top">
              <span>导入</span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
                <div className="btn-row btn-row--6">
                  <button
                    type="button"
                    className="btn btn--ghost"
                    disabled={personaBusy}
                    onClick={() => personaFileRef.current && personaFileRef.current.click()}
                  >
                    选择文件（.json / .zip）
                  </button>
                  <input
                    ref={personaFileRef}
                    type="file"
                    accept=".json,.zip,.md,.markdown,.txt"
                    style={{ display: 'none' }}
                    onChange={(e) => {
                      const file = e.target.files && e.target.files[0];
                      e.target.value = '';           // 同一个文件能连续选两次
                      onPickPersonaFile(file);
                    }}
                  />
                  <input
                    value={importName}
                    placeholder="人设名称（粘贴文本时用，可留空）"
                    spellCheck={false}
                    onChange={(e) => setImportName(e.target.value)}
                  />
                </div>
                <textarea
                  className="brain-area"
                  value={importText}
                  placeholder="也可以直接把人格卡 JSON 或一整段人设文字粘在这里，再点右边「导入」"
                  spellCheck={false}
                  onChange={(e) => setImportText(e.target.value)}
                />
                <div className="btn-row btn-row--6">
                  <button
                    type="button"
                    className="btn btn--primary"
                    disabled={personaBusy || !importText.trim()}
                    onClick={() => importPersonaPayload({ filename: 'pasted.md', content: importText, name: importName })}
                  >
                    导入粘贴内容
                  </button>
                  <button type="button" className="btn btn--ghost" onClick={() => setImportPanel(false)}>
                    取消
                  </button>
                </div>
              </div>
            </div>
          )}

          {guide && (
            <div className="kv-row kv-row--wide kv-row--top">
              <span>模板说明</span>
              <pre
                className="brain-area brain-area--mcp"
                style={{ flex: 1, height: 220, overflow: 'auto', whiteSpace: 'pre-wrap' }}
              >
                {guide}
              </pre>
            </div>
          )}

          <div className="brain-list brain-list--110">
            {personas.length ? (
              personas.map((p) => (
                <div
                  className="brain-list__row"
                  key={p.id}
                  title={`${p.summary || ''}${p.tools && p.tools.length ? `　工具：${p.tools.join('、')}` : ''}`}
                  style={{
                    cursor: 'pointer',
                    background: p.id === personaSel ? 'rgba(88, 152, 255, 0.18)' : 'transparent',
                  }}
                  onClick={() => setPersonaSel(p.id)}
                >
                  {p.name} v{p.version}{p.active ? '（启用中）' : ''}　[工具：{(p.tools || []).join('、') || '无'}]
                  　{p.source}{p.updated_at ? ` · ${p.updated_at}` : ''}
                </div>
              ))
            ) : (
              <p className="brain-list__empty">本机未安装本地人设包</p>
            )}
          </div>
          <div className="btn-row btn-row--6">
            <button
              type="button"
              className="btn btn--ghost"
              disabled={personaBusy}
              onClick={activatePersona}
            >
              启用
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              disabled={personaBusy}
              onClick={deactivatePersona}
            >
              停用本地人设
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              disabled={personaBusy}
              onClick={uninstallPersona}
            >
              卸载
            </button>
          </div>
        </section>
      )}

      <section className="card card--strong card--brain">
        <h2 className="card__title">人设与主动聊天</h2>
        <p className="card__note">原 ac 指令已移除，改在这里配置；保存后重启机器人生效。</p>

        <div className="kv-row kv-row--wide kv-row--top">
          <span>人格设定</span>
          <textarea
            className="brain-area"
            value={personality}
            placeholder="机器人的人设/性格，例如：你是 AstroSwarm 星群内置 AI 助手，回答简洁直接…"
            spellCheck={false}
            onChange={(e) => setPersonality(e.target.value)}
          />
        </div>

        <label className="check">
          <input
            type="checkbox"
            checked={Boolean(f.ai_proactive)}
            onChange={(e) => set({ ai_proactive: e.target.checked })}
          />
          <span>启用主动聊天（机器人会不定时主动找用户聊天）</span>
        </label>

        <div className="kv-row kv-row--wide">
          <span>目标用户</span>
          <input
            value={f.ai_proactive_targets ?? ''}
            placeholder="QQ 官方 openid，多个用逗号分隔（留空 = 无目标；先用目标账号与机器人对话获取 openid）"
            spellCheck={false}
            onChange={(e) => set({ ai_proactive_targets: e.target.value })}
          />
        </div>

        <div className="kv-row kv-row--wide">
          <span>搭话群聊</span>
          <input
            value={f.ai_proactive_groups ?? ''}
            placeholder="QQ 群 openid，多个用逗号分隔（留空 = 不搭话；机器人需已在群内接收过消息）"
            spellCheck={false}
            onChange={(e) => set({ ai_proactive_groups: e.target.value })}
          />
        </div>

        <div className="num-grid">
          {num('ai_interval_min', 1, 1440)}
          {num('ai_interval_max', 1, 1440)}
          {num('ai_cooldown', 1, 1440)}
          {num('ai_quiet_start', 0, 23)}
          {num('ai_quiet_end', 0, 23)}
        </div>
      </section>

      {!beginner && (
        <section className="card card--strong card--brain">
          <h2 className="card__title">记忆与 MCP</h2>
          <label className="check">
            <input
              type="checkbox"
              checked={Boolean(f.memory_enabled)}
              onChange={(e) => set({ memory_enabled: e.target.checked })}
            />
            <span>启用全局记忆（默认开启，AI 会记住长期事项）</span>
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={Boolean(f.mcp_enabled)}
              onChange={(e) => {
                setMcpTouched(true);
                set({ mcp_enabled: e.target.checked });
              }}
            />
            <span>启用 MCP 工具（供 AI 调用外部服务器）</span>
          </label>
          <div className="kv-row kv-row--wide kv-row--top">
            <span>MCP 服务器</span>
            <textarea
              className="brain-area brain-area--mcp"
              value={mcpText}
              placeholder={'{\n  "服务器名": {"type": "sse", "enabled": true, "url": "http://127.0.0.1:8000/sse", "headers": {}}\n}'}
              spellCheck={false}
              onChange={(e) => {
                setMcpTouched(true);
                setMcpText(e.target.value);
              }}
            />
          </div>
          <p className="card__note">JSON 格式：sse 用 url/headers；stdio 用 command/args/env；保存后重启机器人生效。</p>
          {mcpBase === false && (
            <p className="card__note">
              MCP 状态没读到（通常是没登录）：这里显示的是默认值，保存时不会改动服务器上的 MCP 配置。
            </p>
          )}
          <MemoryTimeline />
          <KnowledgeBase />
        </section>
      )}

      {!installed ? (
        <div className="empty-state empty-state--brain">
          <div className="empty-state__title">未检测到内置 AI 插件</div>
          <div className="empty-state__hint">
            重启一次机器人后，AstroSwarm 会自动把内置 ai 插件安装到插件目录，并在这里展示模型、MCP、记忆与身份绑定状态。
          </div>
        </div>
      ) : (
        <section className="card card--brain">
          {[
            ['当前模型', f.ai_model || '未配置'],
            ['MCP', `${f.mcp_enabled ? '已开启' : '未开启'} · ${Object.keys(f.mcp_servers || {}).length} 个服务器`],
            ['全局记忆', stats ? `${stats.memory_global ?? 0} 条` : '—'],
            ['用户记忆', stats ? `${stats.memory_users ?? 0} 个用户` : '—'],
            ['身份绑定', stats ? `${stats.identity_binds ?? 0} 组绑定` : '—'],
          ].map(([label, value]) => (
            <div className="kv-row kv-row--wide" key={label}>
              <span>{label}</span>
              <b>{value}</b>
            </div>
          ))}
          {!stats && <p className="card__note">{LOGIN_HINT}（记忆与身份绑定的数量需要登录后才能读）</p>}
          <div className="btn-row btn-row--6">
            <button
              type="button"
              className="btn"
              title="无头端没有本地编辑器：点这里复制 bot 的 .env 路径"
              onClick={() => copyServerPath(setMsg, ' .env 路径', botEnvPath)}
            >
              复制 .env
            </button>
            <button
              type="button"
              className="btn"
              title="无头端没有本地文件管理器：点这里复制插件目录"
              onClick={() => copyServerPath(setMsg, '插件目录', pluginsDirPath)}
            >
              复制插件目录
            </button>
          </div>
        </section>
      )}

      {msg && <div className="toast">{msg}</div>}
    </>
  );
}


function Overview({ health, auth, services, config, loggedIn, onAccess, onMessages, onServices }) {
  const [msg, setMsg] = useState('');
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!msg) return undefined;
    const timer = setTimeout(() => setMsg(''), 3200);
    return () => clearTimeout(timer);
  }, [msg]);

  const act = async (action) => {
    const label = { start: '启动', stop: '停止', restart: '重启' }[action] || action;
    try {
      await post(`/api/services/${action}`, { service: 'bot' });
      setMsg(`${label}指令已发送`);
    } catch (e) {
      setMsg(String(e.message));
    }
  };

  const stopAll = () => {
    if (!window.confirm('确定停止全部？\nQQ / 微信 会离线，机器人不再回复任何消息。')) return;
    act('stop');
  };

  /* 重启不是无害动作：进程重启期间 QQ / 微信 会离线约 10 秒，协议端要重新连回来，
     正在进行的对话会被打断。首页三个分支里的「重启机器人」都走这里，统一加二次确认。 */
  const restartBot = () => {
    if (!window.confirm('确定重启机器人？\n大约 10 秒内 QQ / 微信 会短暂离线，正在进行的对话会中断。')) return;
    act('restart');
  };

  const botState = services?.bot?.state;
  const botOn = botState === 'running';
  const deployed = botState === 'running' || botState === 'installed';
  // 通道连接状态：进程在跑 ≠ QQ 已连上。以前只看进程，协议端没连也显示绿色「运行中」，
  // 用户会以为能收消息，实际一条都收不到 —— 这里拆成三态。
  const qqRaw = String(services?.bot?.qq || '').toLowerCase();
  const qqLinked = qqRaw === 'connected';
  const qqMap = {
    connected: '已连接',
    connecting: '连接中',
    unauthorized: '白名单未通过',
    stopped: '等待协议端连接',
    unknown: '状态未知',
  };
  const qqReason = qqMap[qqRaw] || '等待协议端连接';
  const qqTone = !botOn ? 'stopped' : qqLinked ? 'running' : 'warn';
  const qqLabel = !botOn ? 'QQ · 未连接' : qqLinked ? 'QQ · 已连接' : 'QQ · 未连接';
  // 微信通道的闸门后端读 member（deploy.apply_wechat_gate / console_ext.wechat_state），
  // 前端必须同一个口径，否则月费用户会被显示成「未解锁」，而后端其实是开的。
  const wxOn = isMember(auth);
  const botTone = services == null ? 'unknown' : botOn ? 'running' : deployed ? 'stopped' : 'unknown';
  const botLabel = services == null ? '机器人 · 状态未知' : botOn ? '机器人 · 运行中' : deployed ? '机器人 · 已停止' : '机器人 · 未部署';
  // 「机器人现在好不好」= 三件事都成立才算正常；任何一项不成立都给出人话原因 + 该做什么
  const healthy = botOn && qqLinked && wxOn;
  const problems = [];
  if (!botOn) problems.push(deployed ? '机器人进程没在跑：点下面的按钮启动。' : '机器人还没部署过：先启动一次，部署脚本会装好运行环境。');
  else if (!qqLinked) problems.push(`QQ 通道未连接（当前：${qqReason}）：协议端没连上，QQ 现在收不到消息，去「接入 → QQ」核对反向 WS 地址。`);
  if (!wxOn) problems.push('微信通道未开通：当前只有 QQ 通道，去账号中心开通后就能用微信。');
  const botPort = config?.bot_port || health?.bot_port || 12113;
  const clock = now.toTimeString().slice(0, 8);
  const wsUrl = `ws://${window.location.hostname || '127.0.0.1'}:${botPort}/onebot/v11/ws`;

  // 主操作：一屏只有一个「该做的事」。正常时不给实心主按钮（没事情要做），
  // 只留一个次级的「重启机器人」；出问题就把对应动作顶上来。
  const mainAction = !botOn
    ? {
        title: deployed ? '机器人没在跑' : '机器人还没部署',
        hint: deployed
          ? '启动后 QQ / 微信 通道才会开始收消息。'
          : '第一次启动会自动装运行环境（几分钟），装完就能用。',
        primary: { label: '启动全部', onClick: () => act('start') },
        secondary: [],
      }
    : !qqLinked
      ? {
          title: 'QQ 通道没连上',
          hint: `进程在跑，但协议端还没连过来（当前：${qqReason}），QQ 现在收不到消息。`,
          primary: { label: '去接入', onClick: onAccess },
          secondary: [{ label: '重启机器人', onClick: restartBot }],
        }
      : !wxOn
        ? {
            title: '微信通道未开通',
            hint: '当前只有 QQ 通道；微信通道去账号中心开通后即可用。',
            primary: { label: '去接入', onClick: onAccess },
            secondary: [{ label: '重启机器人', onClick: restartBot }],
          }
        : {
            title: '一切正常',
            hint: 'QQ 已连接，机器人正在收消息。要改配置或加平台去「接入」。',
            primary: null,
            secondary: [
              { label: '重启机器人', onClick: restartBot },
              { label: '去接入', onClick: onAccess },
            ],
          };

  return (
    <>
      <header className="page-head">
        <div>
          <h1>首页</h1>
          <p>机器人现在好不好，一眼看出问题在哪</p>
        </div>
        <div className="page-head__right">
          <span className="home-time">更新于 {clock}</span>
        </div>
      </header>

      {/* 1) 顶部一行健康摘要：正常/需要注意 + 三个通道状态（都带文字，不靠颜色单独表意） */}
      <section className="card hp-health">
        <div className="hp-health__head">
          <StatusBadge tone={healthy ? 'success' : 'warn'}>{healthy ? '正常' : '需要注意'}</StatusBadge>
          <span className="hp-health__note">
            {healthy ? '三个通道都正常' : '下面有不正常的地方，按提示处理即可'}
          </span>
        </div>
        <div className="hp-health__row">
          <StatusBadge tone={qqTone}>{qqLabel}</StatusBadge>
          <StatusBadge tone={wxOn ? 'success' : 'warn'}>{wxOn ? '微信 · 已解锁' : '微信 · 未解锁'}</StatusBadge>
          <StatusBadge tone={botTone}>{botLabel}</StatusBadge>
        </div>
        {problems.length > 0 && (
          <ul className="hp-health__list">
            {problems.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        )}
      </section>

      {/* 2) 一屏一个实心主操作：异常时是「去接入」，正常时不给实心按钮（没事情要做）。
          次级最多两个（描边，现在三个分支最多只给 1 个，slice 不会丢掉任何动作），
          危险/边缘动作一律第三级（ghost）——「停止机器人」不再是红色实心大按钮；
          「看服务详情」这类运维入口收进底部「详情与运维」折叠，避免四个按钮挤成一行。 */}
      <section className="card hp-act">
        <h2 className="card__title">{mainAction.title}</h2>
        <p className="card__note">{mainAction.hint}</p>
        <div className="hp-act__btns">
          {mainAction.primary ? (
            <button type="button" className="btn btn--primary" onClick={mainAction.primary.onClick}>
              {mainAction.primary.label}
            </button>
          ) : null}
          {mainAction.secondary.slice(0, 2).map((b) => (
            <button key={b.label} type="button" className="btn" onClick={b.onClick}>
              {b.label}
            </button>
          ))}
          {/* 停止是危险动作：主界面用第三级样式 + 二次确认，确认框里才说清后果 */}
          {botOn && (
            <button type="button" className="btn btn--ghost" onClick={stopAll}>
              停止机器人
            </button>
          )}
        </div>
      </section>

      {/* 3) 两列网格（别拉成通栏大块）：左列本机信息（压成 3 行）+ 当前任务，右列最近消息（真实会话） */}
      <div className="hp-grid">
        <div className="hp-col">
          <section className="card">
            <h2 className="card__title">本机信息</h2>
            <div className="stat-rows">
              {[
                // 同类信息合并成行：版本/机器码一行、目录一行、服务与端口一行，不再一项一行撑满屏
                ['版本 / 机器码',
                  `${health?.version || APP_VERSION} · ${health?.machine_id ? String(health.machine_id).slice(0, 8) + '…' : '登录后可见'}`],
                ['机器人目录', services?.bot?.bot_dir || '—'],
                ['服务 / 端口', `${health?.ok ? '后端正常' : '后端未连通'} · ${botPort}`],
              ].map(([label, value]) => (
                <div className="stat-row" key={label}>
                  <span>{label}</span>
                  <b className="hp-nowrap">{value ?? '—'}</b>
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <h2 className="card__title">当前任务</h2>
            {/* 空闲时就是一行说明，不留空态大块；有任务时这里换成任务列表 */}
            <p className="card__note">当前没有正在执行的任务 · 点上面的按钮启动，或在「依赖」页发起安装</p>
          </section>
        </div>

        <section className="card hp-recent">
          <h2 className="card__title">最近消息</h2>
          <RecentMessages onOpen={onMessages} loggedIn={loggedIn} />
          <div className="hp-linkrow">
            <button type="button" className="hp-link" onClick={onMessages}>
              打开消息中心 ›
            </button>
          </div>
        </section>
      </div>

      {/* 4) 折叠区只留运维入口、路径细节与原始数据 */}
      <details className="fold">
        <summary className="fold__summary">详情与运维：运行数据 · 路径与日志入口</summary>
        <div className="fold__body">
          <section className="card">
            <h2 className="card__title">运行数据</h2>
            <StatsPanel loggedIn={loggedIn} />
          </section>

          <section className="card">
            <h2 className="card__title">运维入口</h2>
            <div className="stat-rows">
              <div className="stat-row">
                <span>QQ 反向地址</span>
                <b className="hp-nowrap">{wsUrl}</b>
              </div>
              <div className="stat-row">
                <span>日志文件</span>
                <b className="hp-nowrap">{services?.bot?.log || '—'}</b>
              </div>
            </div>
            <div className="btn-row">
              <button type="button" className="btn" onClick={onServices}>
                看服务详情
              </button>
              <button type="button" className="btn btn--ghost" onClick={onMessages}>
                打开消息中心
              </button>
            </div>
          </section>
        </div>
      </details>

      {msg && <div className="toast">{msg}</div>}
    </>
  );
}

function WeChatBody({ auth, onMessages }) {
  // 微信闸门 = member（后端 deploy.apply_wechat_gate 读的就是 feature_gate()["member"]）。
  // 以前读 full，后端收窄 full 之后已开通的账号会被判成「未开通」——后端其实是开的。
  const member = isMember(auth);
  const reason = auth?.reason || 'QQ 通道可用；微信通道未开通（本机权益未通过签名校验）';
  // 微信通道（iLink）：状态和二维码都由后端从适配器落的文件里读，前端只做展示与触发
  const [wx, setWx] = useState(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [wxErr, setWxErr] = useState('');
  const codeRef = useRef(null);

  // /api/wechat/status 也要鉴权：未登录时以前是 .catch(() => {})，卡片会显示成
  // 「未登录 / 还没有二维码」—— 把「读不到」说成了「没有」。这里记下来如实展示。
  const loadWx = () =>
    get('/api/wechat/status')
      .then((d) => { setWx(d); setWxErr(''); })
      .catch((e) => {
        setWx(null);
        setWxErr(isAuthError(e) ? 'login' : String(e.message));
      });
  useEffect(() => {
    loadWx();
    const t = setInterval(loadWx, 3000);
    return () => clearInterval(t);
  }, []);

  const qrUrl = wx?.qrcode_url || '';
  const qrFresh = qrUrl && (wx?.qrcode_age ?? 999) < 110;   // 二维码 2 分钟一换
  const loggedIn = Boolean(wx?.logged_in);
  const tone = loggedIn ? 'success' : member && qrUrl ? 'warn' : 'stopped';
  const stateText = loggedIn ? '已连接' : !member ? '未开通' : qrUrl ? '等待扫码' : '未登录';

  /* 「重新扫码登录」的按钮名看起来只是刷新一张图，后端实现却是 /api/wechat/relogin
     = 清登录态 + 重启机器人（console_ext 的 relogin），会打断正在进行的对话、
     微信在几秒内离线。所以加二次确认，并在确认框与提示里把真实后果说清楚。 */
  const doRelogin = async () => {
    if (!window.confirm(
      '确定重新扫码登录？\n这会清除微信登录态并重启机器人：\n'
      + '· 大约 10 秒内微信/QQ 会离线，正在进行的对话会中断；\n'
      + '· 之后要用微信重新扫一次码才能恢复。',
    )) return;
    setBusy(true);
    setMsg('正在重新扫码：清登录态并重启机器人…');
    try {
      await post('/api/wechat/relogin', {});
      setMsg('已重启机器人，几秒后这里会出现新的二维码');
      setTimeout(loadWx, 4000);
    } catch (e) {
      setMsg(withAuthHint(e));
    } finally {
      setBusy(false);
    }
  };

  const submitCode = async () => {
    const v = code.trim();
    if (!v) {
      setMsg('先填配对码');
      return;
    }
    try {
      await post('/api/wechat/verify-code', { code: v });
      setCode('');
      setMsg('配对码已提交，微信那边确认后这里会自动变成「已连接」');
      loadWx();
    } catch (e) {
      setMsg(withAuthHint(e));
    }
  };

  const restartBot = async () => {
    if (!window.confirm('确定重启机器人？\n大约 10 秒内 QQ / 微信 会短暂离线，正在进行扫码会中断。')) return;
    try {
      await post('/api/services/restart', { service: 'bot' });
      setMsg('已发送重启指令，机器人起来后会继续扫码流程');
    } catch (e) {
      setMsg(withAuthHint(e));
    }
  };

  const openQrLink = () => {
    if (!qrUrl) {
      setMsg('还没有二维码，先点「重新扫码登录」');
      return;
    }
    window.open(qrUrl, '_blank');
    setMsg('已打开二维码链接：用微信打开它即可授权');
  };

  return (
    <>
      {!member && (
        <>
          <p className="gate-lock">{reason}。开通后即可扫码登录。</p>
          <a className="btn btn--ghost btn--block" href={ACTIVATE_URL} target="_blank" rel="noreferrer">
            去账号中心开通微信通道
          </a>
        </>
      )}

      <section className="card card--wx">
        <StatusBadge tone={wxErr ? 'unknown' : tone}>
          微信 ClawBot · {wxErr ? '状态读不到' : stateText}
        </StatusBadge>
        {wxErr === 'login' && (
          <p className="card__note">{LOGIN_HINT}：微信状态读不到，下面显示的不是真实状态。</p>
        )}
        {wxErr && wxErr !== 'login' && (
          <p className="card__note">微信状态读取失败：{wxErr}（可点「刷新二维码」重试）</p>
        )}
        <div className="stat-row">
          <span>Bot ID</span>
          <b>{wx?.bot_id || '—'}</b>
        </div>
        <div className="stat-row">
          <span>登录时间</span>
          <b>{loggedIn ? '已登录' : wx?.login_status ? `扫码状态：${wx.login_status}` : '—'}</b>
        </div>
        <div className="qr-box">
          {!member ? (
            reason
          ) : loggedIn ? (
            '微信通道已连接，收到私聊会由 Agent 直接回复'
          ) : qrFresh ? (
            <img
              src={authUrl('/api/wechat/qrcode.png?t=' + Math.floor(qrUrl.length + (wx?.qrcode_ts || 0)))}
              alt="微信二维码"
              style={{ width: '100%', height: '100%', objectFit: 'contain' }}
            />
          ) : (
            '暂无有效二维码\n点「重新扫码登录」后这里会自动显示'
          )}
        </div>
        {(wx?.login_extra || qrUrl) && !loggedIn && (
          <p className="card__note">
            {wx?.login_extra ? `微信：${wx.login_extra}　` : ''}
            {qrUrl ? `二维码链接：${qrUrl}` : ''}
          </p>
        )}
        <p className="card__note">
          说明：ClawBot 是私密个人助手通道，不支持群聊；其他用户无法添加你的 ClawBot。
        </p>
        <div className="p-row">
          <input
            className="p-input"
            ref={codeRef}
            value={code}
            placeholder="配对码（微信里提示时填这里）"
            spellCheck={false}
            onChange={(e) => setCode(e.target.value)}
          />
          <button type="button" className="btn btn--primary" onClick={submitCode}>
            提交配对码
          </button>
        </div>
        <div className="btn-row">
          <button type="button" className="btn" disabled={!member || busy} onClick={doRelogin}>
            重新扫码登录
          </button>
          <button type="button" className="btn" onClick={loadWx}>
            刷新二维码
          </button>
          <button type="button" className="btn" onClick={openQrLink}>
            打开扫码链接
          </button>
          <button type="button" className="btn" onClick={() => codeRef.current && codeRef.current.focus()}>
            输入配对码
          </button>
          <button type="button" className="btn" onClick={restartBot}>
            重启 NoneBot
          </button>
        </div>
      </section>

      <section className="card card--wide card--fill">
        <h2 className="card__title">最近微信会话</h2>
        {/* 这里以前是一个写死的「—」占位。会话本身在消息中心（真接口），
            这里如实说明去哪儿看，不再摆一个没有意义的横杠。 */}
        <p className="card__note">
          {wxErr === 'login'
            ? `${LOGIN_HINT}：登录后才能判断微信有没有会话。`
            : !member
              ? '微信通道未解锁：解锁并登录后，微信私聊会话会出现在消息中心（把「平台」选成「微信」）。'
              : loggedIn
                ? '已连接：点下面的按钮进消息中心，「平台」选「微信」即可只看微信会话。'
                : '微信还没登录：扫码并提交配对码后，会话才会出现在消息中心。'}
        </p>
        <button type="button" className="btn btn--block" onClick={onMessages}>
          打开消息中心
        </button>
      </section>

      {msg && <div className="toast">{msg}</div>}
    </>
  );
}

function QQBody({ config, health, services, onSaved }) {
  const [form, setForm] = useState(null);
  const [msg, setMsg] = useState('');
  const [tutorial, setTutorial] = useState(false);
  /* QQ 官方凭证（AppID / AppSecret / AppToken）在重排版时从前端丢了，后端 SAFE_KEYS 一直支持。
     这里补回来：secret / token 是后端脱敏字段（/api/config 回 ****1234），
     只有用户确实改过（edited 里标记过）才提交，未修改时整条键都不送 ——
     否则就是把打码值当成真值写回去（后端虽然也会拦 **** 开头的值，前端不该依赖那一层）。 */
  const [edited, setEdited] = useState({});
  useEffect(() => {
    if (form === null && config) setForm(config);
  }, [config, form]);
  const f = form || {};
  const botPort = f.bot_port || health?.bot_port || 12113;
  const host = window.location.hostname || '127.0.0.1';
  const wsUrl = `ws://${host}:${botPort}/onebot/v11/ws`;
  const botOn = services?.bot?.state === 'running';
  const qq = services?.bot?.qq;
  const qqText =
    {
      connected: '已连接（协议端在线）',
      connecting: '连接中',
      unauthorized: '白名单未通过',
    }[qq] || '等待协议端反向连接';

  const act = async (action) => {
    const label = { start: '启动', stop: '停止', restart: '重启' }[action] || action;
    try {
      await post(`/api/services/${action}`, { service: 'bot' });
      setMsg(`${label}指令已发送`);
    } catch (e) {
      setMsg(String(e.message));
    }
  };

  const editField = (key, value) => {
    setForm({ ...f, [key]: value });
    setEdited((prev) => ({ ...prev, [key]: true }));
  };

  const save = async () => {
    try {
      const payload = { bot_port: Number(botPort) || 12113 };
      // AppID 不是脱敏字段（后端原样返回），可以一直提交；
      // AppSecret / AppToken / 访问令牌只在用户改过时提交。
      if (f.qq_app_id !== undefined) payload.qq_app_id = String(f.qq_app_id || '');
      ['qq_app_secret', 'qq_app_token', 'qq_onebot_token'].forEach((k) => {
        if (edited[k]) payload[k] = String(f[k] || '');
      });
      const saved = await put('/api/config', payload);
      setForm({ ...f, ...saved });
      setEdited({});
      setMsg('已保存，重启 NoneBot 后生效');
      onSaved();
    } catch (e) {
      setMsg(String(e.message));
    }
  };

  const copyUrl = async () => {
    try {
      await navigator.clipboard.writeText(wsUrl);
      setMsg(`已复制：${wsUrl}`);
    } catch (e) {
      setMsg('浏览器不给写剪贴板，请手动选中复制');
    }
  };

  return (
    <>
      <div className="btn-row">
        <button type="button" className="btn btn--primary" onClick={() => act('start')}>
          启动全部
        </button>
        <button
          type="button"
          className="btn btn--danger"
          onClick={() => {
            if (!window.confirm('确定停止全部？\nQQ / 微信 会离线，机器人不再回复任何消息。')) return;
            act('stop');
          }}
        >
          停止全部
        </button>
        <button type="button" className="btn btn--ghost" onClick={() => act('restart')}>
          重启 NoneBot
        </button>
      </div>

      <div className="btn-row">
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => copyServerPath(setMsg, ' .env 路径', botEnvPath)}
          title="无头端没有本地编辑器：点这里复制 bot 的 .env 路径；要改配置去「设置」页"
        >
          复制 .env
        </button>
        <button type="button" className="btn btn--ghost" onClick={() => setTutorial((v) => !v)}>
          接入教程（LLOneBot）
        </button>
      </div>

      {tutorial && (
        <section className="card card--wide">
          <h2 className="card__title">接入教程：把协议端连过来</h2>
          <p className="card__note">
            {`1. 在任意一台设备安装协议端（LLOneBot / NapCat / Lagrange.OneBot）并扫码登录 QQ 小号；
2. 打开协议端的「网络配置」→ 新建「WebSocket 服务端 / 反向 WebSocket」；
3. 地址填 ${wsUrl}，启用并保存；
4. 回到本页，上面「状态」变成「已连接」即接入成功。`}
          </p>
        </section>
      )}

      <div className="home-row home-row--cards">
        <section className="card card--kv card--wide">
          <StatusBadge tone={botOn ? 'running' : 'stopped'}>
            NoneBot · {botOn ? '运行中' : '已停止'}
          </StatusBadge>
          <div className="stat-row">
            <span>端口</span>
            <b>{botPort}</b>
          </div>
          <div className="stat-row">
            <span>Python</span>
            <b className="mono">—</b>
          </div>
          <div className="stat-row">
            <span>运行记录</span>
            <b>—</b>
          </div>
        </section>

        <section className="card card--kv card--wide">
          <StatusBadge tone={qq === 'connected' ? 'success' : (botOn ? 'warn' : 'stopped')}>
            QQ OneBot · {qq === 'connected' ? '已连接' : '已停止'}
          </StatusBadge>
          <div className="stat-row">
            <span>反向地址</span>
            <b className="mono">{wsUrl}</b>
          </div>
          <div className="stat-row">
            <span>通道</span>
            <b>第三方 OneBot（反向 WS）</b>
          </div>
          <div className="stat-row">
            <span>状态</span>
            <b>{qqText}</b>
          </div>
          <p className="card__note">
            协议端由你自行安装并扫码登录（例如 LLOneBot / Lagrange），AstroSwarm
            只负责连接，不内置、不分发任何协议端；使用第三方协议有账号风险，请自备小号。
          </p>
        </section>
      </div>

      <section className="card card--kv card--wide">
        <h2 className="card__title">QQ 通道配置</h2>

        {/* 这两个「下拉」各自只有一个选项、也没有 onChange —— 点了不会变，是假控件。
            无头端固定只走第三方 OneBot + 反向 WS（后端的 qq_channel / qq_onebot_mode 虽然
            在白名单里，但界面上没有第二种可选值），所以改成只读文字，不再做成下拉。 */}
        <div className="stat-row">
          <span>接入方式</span>
          <b>第三方 OneBot 协议（协议端自行安装）</b>
        </div>
        <p className="card__note">
          协议端需你自己安装（例如 LLOneBot、Lagrange.OneBot、NapCat）并扫码登录，AstroSwarm
          不提供、不下载任何协议端；使用第三方协议存在账号风险，请自备小号。
        </p>

        <div className="kv-group">
          <div className="stat-row">
            <span>连接方式</span>
            <b>反向 WS（推荐）：协议端来连星群</b>
          </div>

          <div className="kv-group">
            <p className="card__note">
              {`把下面的地址复制到协议端的「反向 WebSocket / WebSocket 服务端」配置里，保存后协议端会主动连回星群（本机/局域网直连，无需端口转发）。
NapCat：网络配置 → 新建 WebSocket 服务端；LLOneBot：网络配置 → 反向 WebSocket 客户端。
协议端在另一台设备时：监听地址填 0.0.0.0，并把下面地址里的 ${host} 换成这台电脑的局域网 IP。`}
            </p>

            <div className="kv-row">
              <span>监听地址</span>
              <input className="mono" value="0.0.0.0" readOnly title="无头端固定监听全部网卡" />
            </div>
            <div className="kv-row">
              <span>监听端口</span>
              <input
                className="mono"
                value={botPort}
                spellCheck={false}
                onChange={(e) => setForm({ ...f, bot_port: e.target.value })}
              />
            </div>
            <div className="kv-row kv-row--url">
              <input className="mono" value={wsUrl} readOnly />
              <button type="button" className="btn btn--primary" onClick={copyUrl}>
                复制地址
              </button>
            </div>
          </div>

          {/* 「访问令牌」原来是一个永远空白、永远不可填的 disabled 输入框：
              它既没有值也没有入口，看着就像坏了。而后端 headless_config.SAFE_KEYS 里
              qq_onebot_token 一直是可读可写的（且不在 SECRET_FIELDS，/api/config 会回真值），
              所以这里做成真正能填的输入：填了就跟机器人端口一起保存（见 save()）。
              留空 = 机器人不校验令牌，此时协议端也留空即可。 */}
          <div className="kv-row">
            <span>访问令牌</span>
            <input
              className="mono"
              value={f.qq_onebot_token ?? ''}
              spellCheck={false}
              placeholder="留空 = 不校验；两边要填成同一个值"
              onChange={(e) => editField('qq_onebot_token', e.target.value)}
            />
          </div>
          <p className="card__note">
            访问令牌是协议端连回来时的校验口令：机器人这边填什么，协议端那边就要填一样的，
            否则 QQ 会连不上。改完要重启 NoneBot 生效。
          </p>
        </div>

        {/* QQ 官方机器人（QQ 开放平台）凭证：重排版时前端丢了这三个字段，而后端
            headless_config 的 SAFE_KEYS 一直支持 qq_app_id / qq_app_secret / qq_app_token。
            密钥用 password 输入；框里显示的 ****xxxx 是后端脱敏值，直接保存不会覆盖服务器上的真值。 */}
        <div className="kv-group">
          <p className="card__note">
            QQ 官方机器人（QQ 开放平台）：走官方通道时填下面三项；密钥框里的 ****xxxx
            是脱敏显示，不重新输入就保持服务器上的原值。
          </p>
          <div className="kv-row">
            <span>AppID</span>
            <input
              className="mono"
              value={f.qq_app_id ?? ''}
              spellCheck={false}
              placeholder="QQ 开放平台的 AppID"
              onChange={(e) => editField('qq_app_id', e.target.value)}
            />
          </div>
          <div className="kv-row">
            <span>AppSecret</span>
            <input
              className="mono"
              type="password"
              value={f.qq_app_secret ?? ''}
              spellCheck={false}
              placeholder="QQ 开放平台的 AppSecret"
              onChange={(e) => editField('qq_app_secret', e.target.value)}
            />
          </div>
          <div className="kv-row">
            <span>AppToken</span>
            <input
              className="mono"
              type="password"
              value={f.qq_app_token ?? ''}
              spellCheck={false}
              placeholder="QQ 开放平台事件推送的 Token"
              onChange={(e) => editField('qq_app_token', e.target.value)}
            />
          </div>
        </div>

        <button type="button" className="btn btn--primary btn--self" onClick={save}>
          保存通道配置
        </button>
      </section>

      {msg && <div className="toast">{msg}</div>}
    </>
  );
}

/* 接入页：通道列表，两组（已上线通道 / 规划中通道）。
   每行结构固定：左边图标 + 信息列（名称 + 状态徽标 / 一句说明 / 2–3 行关键事实），
   右边一个固定宽度的操作槽（只有「配置 ›」一个主操作，margin-left:auto 右对齐）——
   状态文字挪进信息列后，按钮横向位置就不再随状态文字长短漂移。
   复制地址 / 重新扫码这类就地快捷动作放在信息列自己的行里，不影响右侧操作槽对齐。
   展开后才出现该通道原来的全部设置（QQBody / WeChatBody 原样保留，功能一个没删）。 */
function AccessPage({ auth, config, health, services, onSaved, onMessages }) {
  const [open, setOpen] = useState('');
  const [wx, setWx] = useState(null);
  const [msg, setMsg] = useState('');

  const botOn = services?.bot?.state === 'running';
  const qqRaw = String(services?.bot?.qq || '').toLowerCase();
  const qqLinked = qqRaw === 'connected';
  const qqTone = !botOn ? 'stopped' : qqLinked ? 'running' : 'warn';
  const qqLabel = !botOn ? '未连接（机器人未运行）' : qqLinked ? '已连接（协议端在线）' : '未连接（等待协议端）';
  const wxOn = isMember(auth);
  const toggle = (id) => setOpen((v) => (v === id ? '' : id));

  // 折叠状态下也要有信息：微信通道摘要自己拉一次 /api/wechat/status（和展开后的 WeChatBody 同源）
  // 未登录时这个接口 401：以前 .catch(() => {}) 会让摘要显示成「还没有二维码，点重新扫码生成」，
  // 把「读不到」说成「没有」。这里记下来，摘要里如实写。
  const [wxErr, setWxErr] = useState('');
  const loadWx = () =>
    get('/api/wechat/status')
      .then((d) => { setWx(d); setWxErr(''); })
      .catch((e) => {
        setWx(null);
        setWxErr(isAuthError(e) ? 'login' : String(e.message));
      });
  useEffect(() => {
    loadWx();
    const t = setInterval(loadWx, 5000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    if (!msg) return undefined;
    const t = setTimeout(() => setMsg(''), 3200);
    return () => clearTimeout(t);
  }, [msg]);

  const botPort = config?.bot_port || health?.bot_port || 12113;
  const wsUrl = `ws://${window.location.hostname || '127.0.0.1'}:${botPort}/onebot/v11/ws`;

  const copyWs = async () => {
    try {
      await navigator.clipboard.writeText(wsUrl);
      setMsg(`已复制：${wsUrl}`);
    } catch {
      setMsg('浏览器不给写剪贴板，请手动选中复制');
    }
  };

  /* 「重新扫码」不只是刷新二维码：后端 /api/wechat/relogin = 清登录态 + 重启机器人，
     会让微信在几秒内离线并打断正在进行的对话。这个按钮还是折叠行里的小 ghost 按钮，
     很容易误点 —— 加二次确认，并在提示里写清真实后果。 */
  const relogin = async () => {
    if (!window.confirm(
      '确定重新扫码？\n这会清除微信登录态并重启机器人：\n'
      + '· 大约 10 秒内微信/QQ 会离线，正在进行的对话会中断；\n'
      + '· 之后要用微信重新扫一次码才能恢复。',
    )) return;
    try {
      await post('/api/wechat/relogin', {});
      setMsg('已重启机器人，几秒后会出现新二维码；展开这张卡可以扫码并填配对码');
      setTimeout(loadWx, 4000);
    } catch (e) {
      setMsg(withAuthHint(e));
    }
  };

  const wxSummary = !wxOn
    ? '微信通道未开通：当前只有 QQ 通道，去账号中心即可开通'
    : wxErr === 'login'
      ? `${LOGIN_HINT}：微信状态读不到`
      : wxErr
        ? `微信状态读取失败：${wxErr}`
        : wx?.logged_in
          ? `已登录 ClawBot${wx?.bot_id ? ` · Bot ${wx.bot_id}` : ''}，私聊会由 Agent 直接回复`
          : wx?.qrcode_url
            ? `二维码待扫（${wx?.qrcode_age ?? 0}s 前生成，2 分钟一换）`
            : wx?.login_status
              ? `扫码状态：${wx.login_status}`
              : '还没有二维码，点「重新扫码」生成';

  const channels = [
    {
      id: 'qq',
      icon: 'qq',
      name: 'QQ',
      meta: '第三方 OneBot 协议（协议端自行安装）· 反向 WS',
      tone: qqTone,
      label: qqLabel,
      body: <QQBody config={config} health={health} services={services} onSaved={onSaved} />,
      facts: (
        <>
          <div className="chan__fact">
            <span className="chan__k">连接地址</span>
            <code className="chan__v mono">{wsUrl}</code>
            <button type="button" className="btn btn--ghost btn--sm" onClick={copyWs}>
              复制地址
            </button>
          </div>
          <div className="chan__fact">
            <span className="chan__k">协议端(OneBot)</span>
            <span className="chan__v">LLOneBot / NapCat / Lagrange 等，自行安装并扫码登录小号</span>
          </div>
          <p className="chan__hint">
            {qqLinked
              ? '已连上：QQ 消息现在会经这条通道进 Agent。'
              : '未连上：在协议端新建「反向 WebSocket / WebSocket 服务端」，地址填上面的连接地址并启用，状态会自己变成「已连接」。'}
          </p>
        </>
      ),
    },
    {
      id: 'wx',
      icon: 'wechat',
      name: '微信',
      meta: 'ClawBot 通道：个人私聊助手，不支持群聊',
      tone: wxOn ? (wx?.logged_in ? 'success' : 'warn') : 'warn',
      label: wxErr && wxOn
        ? '已解锁 · 状态读不到'
        : wxOn ? (wx?.logged_in ? '已解锁 · 已连接' : '已解锁 · 未登录') : '未解锁（免费版仅 QQ）',
      body: <WeChatBody auth={auth} onMessages={onMessages} />,
      facts: (
        <>
          <div className="chan__fact">
            <span className="chan__k">通道状态</span>
            <span className="chan__v">{wxSummary}</span>
            {/* 按钮名保持「重新扫码」是因为这是桌面端/用户习惯的叫法，但它的真实行为
                （清登录态 + 重启机器人）写在 title 里，点击还会有二次确认。 */}
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              disabled={!wxOn}
              title="会清除微信登录态并重启机器人（约 10 秒离线），之后需要重新扫码授权"
              onClick={relogin}
            >
              重新扫码
            </button>
          </div>
          <p className="chan__hint">
            {!wxOn
              ? '未解锁：微信通道暂不可用，解锁后这里的二维码才会出现。'
              : wxErr === 'login'
                ? `${LOGIN_HINT}：登录后这里才会显示真实的微信通道状态。`
                : wx?.logged_in
                  ? '已连上：扫码和配对码都在下面展开区里，出问题先「重新扫码」（会清登录态并重启机器人）。'
                  : '未连上：点「重新扫码」，再展开这张卡用微信扫码授权、必要时填配对码。'}
          </p>
        </>
      ),
    },
    { id: 'feishu', icon: 'plane', name: '飞书', closed: true },
    { id: 'telegram', icon: 'planeTilt', name: '纸飞机', closed: true },
  ];

  /* 一行通道卡：右侧操作槽固定宽度，所有通道的「配置 ›」落在同一条竖线上 */
  const renderChan = (ch) => (
    <div className="chan__item" key={ch.id}>
      <section className={ch.closed ? 'card chan chan--closed' : 'card chan'}>
        <span className="chan__icon">
          <Icon name={ch.icon} size={18} />
        </span>
        <div className="chan__main">
          <div className="chan__head">
            <span className="chan__name">{ch.name}</span>
            {ch.closed ? (
              <span className="chan__closed">暂未开放 · 正在规划中</span>
            ) : (
              <StatusBadge tone={ch.tone}>{ch.label}</StatusBadge>
            )}
          </div>
          {!ch.closed && <div className="chan__meta">{ch.meta}</div>}
          {!ch.closed && <div className="chan__facts">{ch.facts}</div>}
        </div>
        {!ch.closed && (
          <div className="chan__side">
            <button
              type="button"
              className="btn btn--ghost btn--sm chan__act"
              aria-expanded={open === ch.id}
              onClick={() => toggle(ch.id)}
            >
              {open === ch.id ? '收起' : '配置 ›'}
            </button>
          </div>
        )}
      </section>
      {!ch.closed && open === ch.id && <div className="chan__body">{ch.body}</div>}
    </div>
  );

  return (
    <>
      <header className="page-head">
        <div>
          <h1>接入</h1>
          <p>一个机器人挂多个平台，统一人格；每张卡直接给出关键信息，点「配置 ›」展开该通道的全部设置</p>
        </div>
      </header>

      {/* 功能分组：组内 14px，组间 24px（组外 > 组内），不靠藏内容换留白 */}
      <div className="chan-grp">
        {channels.filter((c) => !c.closed).map(renderChan)}
      </div>

      <div className="chan-grp chan-grp--plan">
        <div className="chan-grp__title">规划中通道</div>
        {channels.filter((c) => c.closed).map(renderChan)}
      </div>

      {msg && <div className="toast">{msg}</div>}
    </>
  );
}

/* 消息中心：与桌面端 message_center_page.py 1:1。
   实测：页头 → 过滤行（平台 24×35 / 下拉 85×35 / 刷新 56×33，行内间距 14）→ 玻璃面板
   （内边距 10/12/12，flex 撑满）→ 空态 60 高（9+18+6+18+9）。
   空态提示在桌面端是「236 宽、16 行高」的标签里放下两行（Qt 的 QLabel 只报 18 高，
   实际绘制溢出了第二行），所以这里固定 236×18 + overflow:visible，绘制和度量都对得上。
   这一页原来是整页空壳：rows 恒为 []、刷新按钮只弹一句
   「无头端还没有会话接口」，而接口其实早就有（GET /api/messages/list），首页「最近消息」
   （BrainStats.jsx）一直在用它。现在按真实接口接线，字段也换成后端真有的那几个。

   ⚠ 后端 messages_list 以前只透出白名单字段 key/title/name/platform/ts/last/last_text，
   而 message_store.load_conversations 造出来的字典里只有 platform/scene/room/count/last
   —— scene/room 被白名单丢掉，多个 QQ 会话在界面上就都显示成「QQ 会话」，分不清谁是谁。
   本轮后端已把 scene/room（以及按 platform+scene+room 还原出来的 key）加进返回，
   所以这里用 scene+room 拼出「QQ 群 123456 / QQ 好友 123456 / 微信 好友 xxx」这种可区分的标题。 */
const MESSAGE_PLATFORMS = [
  ['', '全部'],
  ['qq', 'QQ'],
  ['wechat', '微信'],
  ['feishu', '飞书'],
  ['telegram', '纸飞机'],
];
const PLATFORM_LABELS = { qq: 'QQ', wechat: '微信', feishu: '飞书', telegram: '纸飞机' };
const SCENE_LABELS = { group: '群', private: '好友' };

function MessageCenter({ loggedIn = true }) {
  const [rows, setRows] = useState(null);      // null = 还没读到；[] = 真的没有会话
  const [dsh, setDsh] = useState([]);
  const [needLogin, setNeedLogin] = useState(false);
  const [err, setErr] = useState('');
  const [platform, setPlatform] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!loggedIn) {                            // 别发这个必 401 的请求
      setRows([]);
      setDsh([]);
      setErr('');
      setNeedLogin(true);
      return;
    }
    setBusy(true);
    try {
      const d = await get('/api/messages/list?limit=200');
      setRows(d.conversations || []);
      setDsh(d.dsh || []);
      setErr('');
      setNeedLogin(false);
    } catch (e) {
      setRows([]);
      setDsh([]);
      if (isAuthError(e)) { setNeedLogin(true); setErr(''); } else { setNeedLogin(false); setErr(e.message); }
    } finally {
      setBusy(false);
    }
  }, [loggedIn]);

  useEffect(() => { load(); }, [load]);

  const platOf = (c) => String(c.platform || '').toLowerCase();
  const roomOf = (c) => String(c.room || '').trim();
  const sceneOf = (c) => {
    const scene = String(c.scene || '').toLowerCase();
    if (scene) return scene;
    return String(c.key || '').startsWith('group_') ? 'group' : '';
  };

  /* dsh 那批会话（QQ 消息由 dsh 落盘）在后端是单独一组：只回 key/count/ts，没有 last 正文。
     ⚠ load_conversations() 已经把 dsh 会话并进 conversations 了，所以这里只补 conversations
     里没有的那些（按 platform:room 去重），否则同一个 QQ 会话会在列表里出现两行。 */
  const seenRooms = new Set((rows || []).map((c) => `${platOf(c)}:${roomOf(c) || String(c.key || '')}`));
  const dshRows = (dsh || [])
    .map((d) => {
      const key = String(d.key || '');
      const isGroup = key.startsWith('group_');
      const room = isGroup ? key.slice(6) : key;
      return { ...d, platform: 'qq', scene: isGroup ? 'group' : 'private', room, key, _dsh: true };
    })
    .filter((d) => !seenRooms.has(`qq:${d.room}`));
  const all = [...(rows || []), ...dshRows];
  const shown = platform ? all.filter((c) => platOf(c) === platform) : all;
  const loading = rows === null;
  const has = shown.length > 0;

  /* 会话标题：后端给了 title/name 就直接用；否则用 platform + scene + room 拼出
     「QQ 群 123456 / QQ 好友 123456 / 微信 好友 xxx」—— 多个 QQ 会话因此能区分开。
     两个都拿不到（老后端）时才退回「<平台> 会话」。 */
  const givenName = (c) => String(c.title || c.name || '').trim();
  const label = (c) => {
    const given = givenName(c);
    if (given) return given;
    const plat = PLATFORM_LABELS[platOf(c)] || '未知平台';
    const room = roomOf(c) || String(c.key || '');
    if (!room) return `${plat} 会话`;
    return `${plat} ${SCENE_LABELS[sceneOf(c)] || '会话'} ${room}`;
  };
  const when = (c) => {
    const ts = Number(c.ts || 0);
    if (!ts) return '';
    try { return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false }); } catch { return ''; }
  };
  // 名字里已经带了平台（上面拼出来的那几种）时，meta 行就不再重复平台
  const meta = (c) => [
    givenName(c) ? (PLATFORM_LABELS[platOf(c)] || '') : '',
    c.count ? `${c.count} 条` : '',
    when(c),
  ].filter(Boolean).join(' · ');

  const refresh = async () => {
    await load();
    setMsg('已刷新会话列表');
  };

  return (
    <>
      <header className="page-head">
        <div>
          <h1>消息中心</h1>
          <p>跨平台会话列表：QQ 与 微信 ClawBot 的会话都在这里（数据来自机器人落盘的会话索引）</p>
        </div>
      </header>

      <div className="msg-bar">
        <span>平台</span>
        <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
          {MESSAGE_PLATFORMS.map(([key, labelText]) => (
            <option key={key} value={key}>
              {labelText}
            </option>
          ))}
        </select>
        <button type="button" className="btn" disabled={busy} onClick={refresh}>
          {busy ? '刷新中…' : '刷新'}
        </button>
        <span className="msg-bar__stat">
          {loading ? '读取中…' : needLogin ? '' : `共 ${all.length} 个会话${platform ? `（当前筛选：${PLATFORM_LABELS[platform]}，${shown.length} 个）` : ''}`}
        </span>
      </div>

      <section className="card card--strong card--fill card--msg">
        {has && (
          <div className="msg-list">
            {shown.map((c, i) => (
              <div className="msg-item" key={`${platOf(c)}-${c.key || c.title || c.name || i}`}>
                <div className="msg-item__head">
                  <span className="msg-item__who">{label(c)}</span>
                  <span className="msg-item__meta">{meta(c)}</span>
                </div>
                {(c.last_text || c.last) && <div className="msg-item__last">{c.last_text || c.last}</div>}
              </div>
            ))}          </div>
        )}
      </section>

      {!has && !loading && (
        <div className="empty-state empty-state--messages">
          {needLogin ? (
            <>
              <div className="empty-state__title">读不到会话列表</div>
              <div className="empty-state__hint">{LOGIN_HINT}</div>
            </>
          ) : err ? (
            <>
              <div className="empty-state__title">读取失败</div>
              <div className="empty-state__hint">
                {err}
                （点上面「刷新」重试；一直失败就是后端接口的问题，不是你没有会话）
              </div>
            </>
          ) : platform ? (
            <>
              <div className="empty-state__title">这个平台还没有会话</div>
              <div className="empty-state__hint">
                机器人已经有 {all.length} 个会话，但没有「{PLATFORM_LABELS[platform]}」的：
                把上面的「平台」改回「全部」就能看到。
              </div>
            </>
          ) : (
            <>
              <div className="empty-state__title">还没有会话记录</div>
              <div className="empty-state__hint">
                机器人收到过消息后这里就会出现会话。刚部署好、还没人跟机器人说过话时是正常的。
              </div>
            </>
          )}
        </div>
      )}

      {msg && <div className="toast">{msg}</div>}
    </>
  );
}

/* 全局管理（服务）：只回答「服务在不在跑」+ 每行一个动作。
   端口 / 目录 / 日志路径这些运维细节全部收进「运维细节」折叠区，默认不占版面。
   数据来自 /api/services/status（bot + dsh），动作走 /api/services/{start,stop,restart}。 */
function ServicesPage({ config, health, services, onAccess, onLogs, onDeps }) {
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState('');

  const act = async (action) => {
    const label = { start: '启动', stop: '停止', restart: '重启' }[action] || action;
    setBusy(action);
    try {
      await post(`/api/services/${action}`, { service: 'bot' });
      setMsg(`${label}指令已发送`);
    } catch (e) {
      setMsg(withAuthHint(e));
    } finally {
      setBusy('');
    }
  };

  const stopBot = () => {
    if (!window.confirm('确定停止机器人？\nQQ / 微信 会离线，机器人不再回复任何消息。')) return;
    act('stop');
  };

  /* 重启会打断正在进行的对话、让 QQ / 微信 离线约 10 秒 —— 全局管理页这一处原来没有确认，
     和首页/接入页的做法不一致，这里补齐。 */
  const restartBot = () => {
    if (!window.confirm('确定重启机器人？\n大约 10 秒内 QQ / 微信 会短暂离线，正在进行的对话会中断。')) return;
    act('restart');
  };

  const botState = services?.bot?.state;
  const botOn = botState === 'running';
  const botText =
    services == null
      ? '状态未知'
      : botOn
        ? '运行中'
        : botState === 'installed'
          ? '已停止（已部署）'
          : '未部署（点启动会用部署脚本装好）';
  const botTone = services == null ? 'unknown' : botOn ? 'running' : 'stopped';
  const botPort = config?.bot_port || health?.bot_port || 12113;
  const dshState = services?.dsh?.state || '';
  const dshText = dshState === 'running' ? '运行中' : '暂未开放（待接入）';

  return (
    <>
      <header className="page-head">
        <div>
          <h1>全局管理</h1>
          <p>服务状态与开关；端口、路径、日志位置在下面的「运维细节」里</p>
        </div>
      </header>

      <section className="card svc">
        <div className="svc__row">
          <div className="svc__main">
            <div className="svc__name">机器人（NoneBot）</div>
            <div className="svc__meta">QQ / 微信 共用一个进程，重启会短暂离线约 10 秒</div>
          </div>
          <div className="svc__side">
            <StatusBadge tone={botTone}>{botText}</StatusBadge>
            {botOn ? (
              <button type="button" className="btn" disabled={busy === 'restart'} onClick={restartBot}>
                重启
              </button>
            ) : (
              <button type="button" className="btn btn--primary" disabled={busy === 'start'} onClick={() => act('start')}>
                启动
              </button>
            )}
          </div>
        </div>

        <div className="svc__row">
          <div className="svc__main">
            <div className="svc__name">DSH 智能体</div>
            <div className="svc__meta">服务器上的本地智能体，接入后会出现在这里</div>
          </div>
          <div className="svc__side">
            <StatusBadge tone={dshState === 'running' ? 'running' : 'unknown'}>{dshText}</StatusBadge>
          </div>
        </div>
      </section>

      <details className="fold">
        <summary className="fold__summary">运维细节：端口 / 目录 / 日志路径</summary>
        <div className="fold__body">
          <section className="card">
            <div className="stat-rows">
              <div className="stat-row">
                <span>端口</span>
                <b>{botPort}</b>
              </div>
              <div className="stat-row">
                <span>机器人目录</span>
                <b>{services?.bot?.bot_dir || '—'}</b>
              </div>
              <div className="stat-row">
                <span>日志路径</span>
                <b>{services?.bot?.log || '—'}</b>
              </div>
              <div className="stat-row">
                <span>版本 / 机器码</span>
                <b>
                  {health?.version || '—'}
                  {health?.machine_id ? ` · ${String(health.machine_id).slice(0, 8)}…` : ''}
                </b>
              </div>
            </div>
            <div className="p-row">
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                title="无头端没有本地文件管理器：点这里复制路径，粘到 SSH / SFTP 里用"
                onClick={() => copyServerPath(setMsg, '机器人目录', botEnvPathBase)}
              >
                复制机器人目录
              </button>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => copyServerPath(setMsg, '日志路径', async () => services?.bot?.log || '')}
              >
                复制日志路径
              </button>
              <button type="button" className="btn btn--ghost btn--sm" onClick={onLogs}>
                实时日志
              </button>
              <button type="button" className="btn btn--ghost btn--sm" onClick={onDeps}>
                依赖管理
              </button>
              <button type="button" className="btn btn--ghost btn--sm" onClick={onAccess}>
                接入配置
              </button>
              {/* 危险动作：第三级样式 + 二次确认 */}
              {botOn && (
                <button type="button" className="btn btn--ghost btn--sm" onClick={stopBot}>
                  停止机器人
                </button>
              )}
            </div>
          </section>
        </div>
      </details>

      {msg && <div className="toast">{msg}</div>}
    </>
  );
}

/** 机器人目录（不是 .env 文件本身）：运维细节里复制用 */
async function botEnvPathBase() {
  const s = await get('/api/services/status');
  const dir = s && s.bot && s.bot.bot_dir;
  if (!dir) throw new Error('没拿到 bot 目录（机器人还没部署过）');
  return dir;
}

/* 设置：拆成「外观 / 账号 / 高级」三个 tab（每屏只放一件事，每屏一个主操作）。
   外观 = 主题、质感、动态背景（即时生效，一个「保存设置」写入配置）；
   账号 = 邮箱 / 套餐权益 / 版本更新 / 退出登录；
   高级 = 开发者模式、启动行为、以及全部运维动作（复制路径、端口、依赖、日志）。
   外观项只存浏览器本地（appearance.js），端口等仍走 /api/config。 */
const UI_THEME_OPTIONS = ['极光玻璃', '瑞士极简', '深空终端'];
const ACCENT_OPTIONS = ['深邃蓝', '暗夜紫', '赛博青', '暖阳橙', '薄荷绿', '深空绿（新色板）'];
const GLASS_OPTIONS = ['默认（原样）', '液态玻璃', '颗粒磨砂'];
const SETTING_TABS = [
  ['appearance', '外观'],
  ['account', '账号'],
  ['advanced', '高级'],
];

function Settings({
  config,
  services,
  onSaved,
  beginner,
  onBeginner,
  loggedIn,
  health,
  auth,
  onChanged,
  onToken,
  appearance,
  onAppearance,
  onGo = () => {},
}) {
  const [form, setForm] = useState(null);
  const [info, setInfo] = useState(null);
  const [msg, setMsg] = useState('');
  const [tab, setTab] = useState('appearance');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [latest, setLatest] = useState('');
  const [checkedAt, setCheckedAt] = useState('');
  // 未登录时 /api/status 与 console/dev-mode 都 401，组件里以前是 .catch(()=>{}) 静默吞掉：
  // 表现是「安装根目录恒 —」「开发者模式恒关」，用户以为功能没了。这里记一句实话，见下面对应位置。
  const [infoErr, setInfoErr] = useState('');
  const [devErr, setDevErr] = useState('');
  // 开发者模式：无头端存在服务器的 config_home/console.json（跟桌面端 settings 里的
  // developer_mode 一个语义），开了才能在插件页从 PyPI 装第三方插件。
  const [devMode, setDevMode] = useState(false);
  const ap = { ...APPEARANCE_DEFAULTS, ...(appearance || {}) };
  const set = (patch) => onAppearance({ ...ap, ...patch });

  useEffect(() => {
    if (form === null && config) setForm(config);
  }, [config, form]);
  useEffect(() => {
    get('/api/status')
      .then((d) => { setInfo(d); setInfoErr(''); })
      .catch((e) => { setInfo(null); setInfoErr(isAuthError(e) ? 'login' : String(e.message)); });
    get('/api/console/dev-mode')
      .then((d) => { setDevMode(Boolean(d.developer_mode)); setDevErr(''); })
      .catch((e) => setDevErr(isAuthError(e) ? 'login' : String(e.message)));
  }, []);
  const f = form || {};
  const isGlass = ap.theme === UI_THEME_OPTIONS[0];

  const todo = (what) => setMsg(`${what}：无头端暂不支持，请在服务器或桌面端操作`);
  // 检查更新：桌面端是查签发站的 /license/version（同源，控制台就挂在 astroswarm.cn 下）。
  // 「打开 settings.json / 打开安装目录 / 导入旧版本 / 卸载」在无头端没有任何可做的事
  // （服务器上没有本地文件管理器，卸载也不该由网页按钮代劳），已从界面上删掉。
  const checkUpdate = async () => {
    setMsg('正在检查更新…');
    try {
      const r = await fetch('/license/version', { cache: 'no-store' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      const v = String(d.version || '').trim();
      if (!v) throw new Error('返回里没有版本号');
      setLatest(v);
      setCheckedAt(new Date().toLocaleString('zh-CN', { hour12: false }));
      setMsg(v === APP_VERSION ? `已是最新版本 v${v}` : `有新版本 v${v}（当前 v${APP_VERSION}）${d.url ? '：' + d.url : ''}`);
    } catch (e) {
      setMsg(`检查更新失败：${e.message}（页面不在 astroswarm.cn 下时跨域会被拦）`);
    }
  };
  /* 这里原来有一个「保存设置」按钮，它写的其实只有端口（外观项是改一下就即时存本浏览器的），
     按钮名字和它做的事对不上，而且和独立折叠区里的「保存端口」职责重叠。
     现在端口归上面「网络端口」卡片管，外观本来就是即时生效，所以这个按钮连同 save() 一起删掉 ——
     同一屏不再出现两个「保存」。onSaved 仍被 savePorts 用着，没丢。 */
  // 端口：重排版时输入框丢了（f.port 全文只出现在 save() 的 PUT 里，没有任何控件写它），
  // 于是「保存设置」一直在回写没变的值。这里补回两个输入，单独走 PUT /api/config。
  const savePorts = async () => {
    const port = Number(f.port);
    const botPort = Number(f.bot_port);
    const bad = (n) => !Number.isInteger(n) || n < 1 || n > 65535;
    if (bad(port) || bad(botPort)) {
      setMsg('端口必须是 1–65535 之间的整数');
      return;
    }
    try {
      const saved = await put('/api/config', { port, bot_port: botPort });
      setForm({ ...f, ...saved });
      onSaved();
      setMsg('端口已写入服务器：改端口需要重启服务生效（控制台端口重启控制台，机器人端口重启 NoneBot）');
    } catch (e) {
      setMsg(`端口未写入服务器（${e.message}）`);
    }
  };
  // 选择本地文件：浏览器拿不到真实路径，只能给个本次会话有效的 blob URL；
  // 要长期生效就把图片放到服务器上、在路径里填 URL（/bg.jpg 或 https://…）。
  const pickFile = (file) => {
    if (!file) return;
    set({ enabled: true, path: URL.createObjectURL(file) });
    setMsg('已选本地文件（仅本次会话有效；要长期生效请在路径里填 URL）');
  };
  const login = async () => {
    try {
      const res = await post('/api/auth/login', { email, password });
      // 后端没回 token 就不算登录成功（以前这种情况也会提示「登录成功」，然后界面还是未登录）
      if (!res || !res.token) {
        setMsg('登录没有成功：服务器没有返回登录态，请检查邮箱与密码');
        return;
      }
      onToken(res.token);
      setPassword('');
      setMsg('登录成功');
      await onChanged();
    } catch (e) {
      setMsg(String(e.message));
    }
  };
  /* 退出登录：/api/auth/logout 是**要鉴权**的接口（api.py 的 _require_auth），
     token 过期/被清时后端回 401 → post 抛错。以前没有 try/catch，于是 onToken('') 不执行、
     提示不显示、界面毫无反应 —— 用户只会觉得「退出登录按钮坏了」。
     现在无论如何都清掉本地 token 并跳回未登录态；服务器没确认退出时如实说明。
     本地 token 才是真正的「已登录」判据（App 里 token 状态就是这么用的），清掉它 =
     本机已经退出了，服务器那侧只是把会话记录也注销一下。 */
  const logout = async () => {
    let note = '已退出登录';
    try {
      await post('/api/auth/logout', {});
    } catch (e) {
      if (isAuthError(e)) {
        note = '已退出登录（服务器说这个登录态早就过期了，本机已经清干净）';
      } else {
        note = `已退出本地登录，但服务器没确认（${e.message}）：本机已经退出，可稍后再试一次`;
      }
    } finally {
      onToken('');
      try {
        await onChanged();
      } catch {
        /* 刷新失败不影响「已退出」这件事，本地 token 已经清了 */
      }
      setMsg(note);
    }
  };
  const claim = async () => {
    try {
      await post('/api/auth/claim', { machine_id: health?.machine_id || '' });
      setMsg('已认领本机');
      await onChanged();
    } catch (e) {
      setMsg(String(e.message));
    }
  };
  const acct = auth?.email ? `已登录：${auth.email}` : '未登录';
  // 行高按桌面端实测钉死：值的换行数（Qt 的 wordWrap sizeHint）决定了 32/48 的行，
  // 无头端数据不同、换行数也不同，所以宽度和高度都按实测值固定，保证整块版面一致。
  const row = (label, value, mod = '', vw = 0) => (
    <div className={`set-row set-row--kv${mod}`} key={label}>
      <span>{label}</span>
      <b style={vw ? { width: `${vw}px` } : undefined}>{value}</b>
    </div>
  );

  return (
    <>
      <header className="page-head">
        <div>
          <h1>设置</h1>
          <p>环境信息与外观背景；外观改动实时预览并即时保存在本浏览器，端口在「高级」页签里改</p>
        </div>
      </header>

      <div className="tabbar" role="tablist" aria-label="设置分类">
        {SETTING_TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? 'tabbar__item tabbar__item--on' : 'tabbar__item'}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {/* 账号：邮箱 / 套餐权益 / 版本更新。主操作 = 登录或认领本机 */}
      {tab === 'account' && (
        <div className="tabpane">
          <section className="card">
            <h2 className="card__title">星群账号</h2>
            <p className="card__note">
              {auth?.email
                ? `已登录：${auth.email}。通道开通与插件安装都跟着这个邮箱走。`
                : '未登录：插件照常免费安装；微信通道的开通状态要登录后才能同步。'}
            </p>
            {loggedIn ? (
              <div className="p-row">
                <button type="button" className="btn btn--primary" onClick={claim}>
                  认领本机
                </button>
                <button type="button" className="btn btn--ghost" onClick={logout}>
                  退出登录
                </button>
              </div>
            ) : (
              <div className="p-row">
                <input
                  className="p-input"
                  value={email}
                  placeholder="邮箱"
                  spellCheck={false}
                  onChange={(e) => setEmail(e.target.value)}
                />
                <input
                  className="p-input"
                  type="password"
                  value={password}
                  placeholder="密码"
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button type="button" className="btn btn--primary" onClick={login}>
                  登录
                </button>
              </div>
            )}
            <div className="stat-rows">
              <div className="stat-row">
                <span>套餐 / 权益</span>
                <b>
                  {isMember(auth)
                    ? `${isFull(auth) ? '已开通 · 全功能' : '已开通'}${auth?.plan ? `（${auth.plan}）` : ''}`
                    : '未开通（仅 QQ）'}
                </b>
              </div>
            </div>
            {!isMember(auth) && (
              <a className="btn btn--ghost btn--self" href={ACTIVATE_URL} target="_blank" rel="noreferrer">
                去账号中心开通（含微信通道）
              </a>
            )}
          </section>

          <section className="card">
            <h2 className="card__title">版本与更新</h2>
            <div className="stat-rows">
              <div className="stat-row">
                <span>当前版本</span>
                <b>{health?.version || APP_VERSION}</b>
              </div>
              <div className="stat-row">
                <span>最新版本</span>
                <b>{latest || '—'}</b>
              </div>
              <div className="stat-row">
                <span>上次检查</span>
                <b>{checkedAt || '—'}</b>
              </div>
            </div>
            <button type="button" className="btn btn--self" onClick={checkUpdate}>
              检查更新
            </button>
          </section>
        </div>
      )}

      {/* 高级：网络端口 / 开发者选项 + 运维动作（路径类才折起来）
          端口输入原来藏在「高级 → 再展开一层折叠」里，得点三次才找得到，
          而且和外观页签的「保存设置」抢同一件事（两个按钮都写 /api/config 的端口）。
          现在端口独立成一个**默认可见**的小节，只留一个「保存端口」，外观页签那个多余的
          「保存设置」已经删掉（外观本来就是即时生效的）。 */}
      {tab === 'advanced' && (
        <div className="tabpane">
          <section className="card set-net">
            <h2 className="card__title">网络端口</h2>
            <p className="card__note">
              两个端口都要在 1–65535 之间；改完必须重启对应的服务才生效。
            </p>
            <div className="kv-row">
              <span>控制台端口</span>
              <input
                className="mono"
                type="number"
                min="1"
                max="65535"
                value={f.port ?? ''}
                placeholder="7860"
                onChange={(e) => setForm({ ...f, port: e.target.value })}
              />
            </div>
            <div className="kv-row">
              <span>机器人端口</span>
              <input
                className="mono"
                type="number"
                min="1"
                max="65535"
                value={f.bot_port ?? ''}
                placeholder="12113"
                onChange={(e) => setForm({ ...f, bot_port: e.target.value })}
              />
            </div>
            <p className="card__note">
              控制台端口 = 这个网页后台的端口（重启控制台进程生效）；
              机器人端口 = QQ 协议端反向连接用的端口（重启 NoneBot 生效）。
            </p>
            {!loggedIn && <p className="card__note">{LOGIN_HINT}（端口存在服务器上，读写都要登录）</p>}
            <div className="p-row">
              <button type="button" className="btn btn--primary btn--sm" onClick={savePorts}>
                保存端口
              </button>
            </div>
          </section>

          <section className="card set-ai">
            <h2 className="card__title">AI 插件</h2>
            <p className="card__note">
              内置 AI 插件已随程序自动安装到机器人，不可卸载，也没有开关：机器人启动时一定会加载它。
              接口配置、平台开关、人格与 MCP 都请到「AI 大脑」页设置。
            </p>
            {/* 这里原来是一个「启用 AI 插件」的假勾选框（无 state、无 onChange），
                点了只在本渲染里跳一下、刷新就还原，卡片文案还承诺了「关闭后不加载 AI 功能」
                这个无头端并不存在的能力。改成只读状态徽标，不再假装能点。 */}
            <div className="stat-row">
              <span>AI 插件状态</span>
              <b>已安装 · 常开（无头端不提供关闭开关）</b>
            </div>
          </section>

          <section className="card set-boot">
            <h2 className="card__title">启动行为与开发者选项</h2>
            <label className="check">
              <input
                type="checkbox"
                checked={devMode}
                onChange={async (e) => {
                  const on = e.target.checked;
                  try {
                    const d = await post('/api/console/dev-mode', { on });
                    setDevMode(Boolean(d.developer_mode));
                    setMsg(on ? '开发者模式已开启：插件页可以从 PyPI 装第三方插件了' : '开发者模式已关闭');
                  } catch (err) {
                    setDevMode(!on);
                    setMsg(withAuthHint(err));
                  }
                }}
              />
              <span>开发者模式（恢复第三方插件安装，后果自负）</span>
            </label>
            {devErr === 'login' && (
              <p className="card__note">
                {LOGIN_HINT}：开发者模式的当前状态读不到，上面的勾选框显示的不一定是服务器上的真实值。
              </p>
            )}
            {devErr && devErr !== 'login' && (
              <p className="card__note">开发者模式状态读取失败：{devErr}（可稍后刷新页面重试）</p>
            )}
            <label className="toggle">
              <span>小白模式（只显示常用功能）</span>
              <input
                type="checkbox"
                checked={Boolean(beginner)}
                onChange={(e) => onBeginner(e.target.checked)}
              />
              <i className="toggle__pill" />
            </label>
            {/* 这里原来还有「启动程序时自动启动全部服务」「开机自动启动 AstroSwarm」两个勾选框：
                无 state、无 onChange，点一下变样、刷新就还原 —— 点了没用的假控件，已删除。
                无头端这两个行为由 systemd 管，网页改不了，如实写在下面。 */}
            <p className="card__note">
              开机自启 / 随程序自动启动全部服务：无头端由 systemd 管理，网页上不可改
              （在服务器上执行 systemctl enable / disable astroswarm-headless 生效）；
              桌面端才有上面那两个注册表开关。
            </p>
          </section>

          <details className="fold">
            <summary className="fold__summary">运维：安装目录 / 环境信息 / 快捷入口</summary>
            <div className="fold__body">
              <section className="card">
                <div className="set-row set-row--kv">
                  <span>安装根目录</span>
                  <b>{info?.data_home || info?.config_home || (infoErr ? '未读到' : '—')}</b>
                </div>
                <div className="set-row set-row--kv">
                  <span>Python</span>
                  <b>部署虚拟环境（随机器人一起装）</b>
                </div>
                {/* 这一行以前读的是 config?.bot_dir —— bot_dir 不在后端 SAFE_KEYS 里，
                    /api/config 永远不会返回它，所以恒显示「—」。同一个值 /api/services/status
                    的 services.bot.bot_dir 里有（全局管理页用的就是它），改用那一个。 */}
                <div className="set-row set-row--kv">
                  <span>机器人目录</span>
                  <b>{services?.bot?.bot_dir || '—'}</b>
                </div>
                {infoErr === 'login' && (
                  <p className="card__note">{LOGIN_HINT}：安装根目录与机器人目录读不到。</p>
                )}
                {infoErr && infoErr !== 'login' && (
                  <p className="card__note">环境信息读取失败：{infoErr}</p>
                )}
                <p className="card__note">
                  ⚠ 当前为 BETA 测试版，未经充分测试，可能存在不兼容或 Bug。如遇问题，请等待后续更新。
                </p>
                <div className="p-row">
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    title="无头端没有本地文件管理器：点这里复制路径，粘到终端或 SFTP 里用"
                    onClick={() => copyServerPath(setMsg, '安装根目录', async () => (await get('/api/status')).data_home || (await get('/api/status')).config_home || '')}
                  >
                    复制安装目录
                  </button>
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    onClick={() => copyServerPath(setMsg, '插件目录', pluginsDirPath)}
                  >
                    复制插件目录
                  </button>
                  <button type="button" className="btn btn--ghost btn--sm" onClick={() => onGo('deps')}>
                    依赖管理
                  </button>
                  <button type="button" className="btn btn--ghost btn--sm" onClick={() => onGo('logs')}>
                    实时日志
                  </button>
                  <button type="button" className="btn btn--ghost btn--sm" onClick={() => onGo('services')}>
                    服务开关
                  </button>
                </div>
              </section>
            </div>
          </details>
        </div>
      )}

      {tab === 'appearance' && (
        <div className="tabpane">
        <section className="card card--strong set-appr">
          <h2 className="card__title">外观与动态背景</h2>
          <p className="card__note">
            背景只是氛围层，不影响任何后台任务；下面每一项改完立刻生效，并自动记在这个浏览器里。
          </p>
          <label className="check">
            <input
              type="checkbox"
              checked={ap.enabled}
              onChange={(e) => set({ enabled: e.target.checked })}
            />
            <span>启用背景（图片/视频）</span>
          </label>

          <div className="p-row p-row--top">
            <input
              className="p-input"
              value={ap.path}
              placeholder="背景图片 / 视频的 URL（如 /bg.jpg 或 https://…）"
              spellCheck={false}
              onChange={(e) => set({ path: e.target.value })}
            />
            <label className="btn" title="浏览器拿不到真实路径，选本地文件只在本次会话有效">
              选择文件 ...
              <input
                type="file"
                accept="image/*,video/*"
                style={{ display: 'none' }}
                onChange={(e) => pickFile(e.target.files && e.target.files[0])}
              />
            </label>
            <button type="button" className="btn" onClick={() => set({ path: '' })}>
              清除
            </button>
          </div>

          <div className="p-row p-row--chk">
            <label className="check">
              <input type="checkbox" checked={ap.autoplay} onChange={(e) => set({ autoplay: e.target.checked })} />
              <span>自动播放</span>
            </label>
            <label className="check">
              <input type="checkbox" checked={ap.loop} onChange={(e) => set({ loop: e.target.checked })} />
              <span>循环播放</span>
            </label>
          </div>

          <div className="set-row set-row--slider">
            <span>遮罩强度</span>
            <input
              type="range"
              min="30"
              max="95"
              value={ap.mask}
              onChange={(e) => set({ mask: Number(e.target.value) })}
            />
            <b>{(ap.mask / 100).toFixed(2)}</b>
          </div>

          <div className="set-box">
            <div className="set-row set-row--slider">
              <span>UI 不透明度</span>
              <input
                type="range"
                min="10"
                max="95"
                value={ap.opacity}
                onChange={(e) => set({ opacity: Number(e.target.value) })}
              />
              <b>{`${ap.opacity}%`}</b>
            </div>
          </div>

          <div className="set-row set-row--slider">
            <span>视频亮度</span>
            <input
              type="range"
              min="-100"
              max="100"
              value={ap.bright}
              onChange={(e) => set({ bright: Number(e.target.value) })}
            />
            <b>{String(ap.bright)}</b>
          </div>

          <label className="check">
            <input
              type="checkbox"
              checked={ap.animations}
              onChange={(e) => set({ animations: e.target.checked })}
            />
            <span>减少界面动效</span>
          </label>

          <div className="set-row">
            <span>UI 主题</span>
            <select
              className="p-select"
              value={ap.theme}
              onChange={(e) => set({ theme: e.target.value })}
              title="每个 UI 主题拥有独立的布局、导航、配色与质感"
            >
              {UI_THEME_OPTIONS.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          {isGlass && (
            <div className="set-box">
              <div className="set-row">
                <span>强调色</span>
                <select className="p-select" value={ap.accent} onChange={(e) => set({ accent: e.target.value })}>
                  {ACCENT_OPTIONS.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}

          <div className="set-box">
            <div className="set-row">
              <span>UI 框质感</span>
              <select className="p-select" value={ap.glass} onChange={(e) => set({ glass: e.target.value })}>
                {GLASS_OPTIONS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* 外观改动是「改一下就即时生效并存进本浏览器」的（App 里 useEffect → saveAppearance）。
              原来这里还有个「保存设置」按钮，实际只写端口 —— 名字和做的事不一致，也和外面上面的
              「保存端口」重复。现在这一屏没有任何「保存」：改动即时生效，端口归「高级 → 网络端口」。 */}
          <p className="card__note">
            以上外观改动都是即时生效的，并记在这个浏览器里，不需要点保存。
            端口、依赖、服务开关在「高级」页签里。
          </p>
        </section>
      </div>
      )}

      {msg && <div className="toast">{msg}</div>}
    </>
  );
}
function Deps() {
  const [summary, setSummary] = useState('尚未扫描');
  const [missing, setMissing] = useState([]);
  const [checked, setChecked] = useState(0);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  const absorb = (st) => {
    if (typeof st.checked === 'number') setChecked(st.checked);
    if (Array.isArray(st.missing)) setMissing(st.missing);
    // st.error 是后端任务异常原文（可能含 pip 输出/路径）：先说人话，再附原文
    if (st.error) setMsg(`上一个依赖任务出错了，请把下面这段发给开发者：${st.error}`);
  };

  // 进页面先接一次状态：可能在插件页刚点过「重装缺失依赖」，结果要接上
  useEffect(() => {
    get('/api/deps/status')
      .then((st) => {
        absorb(st);
        if (st.checked) {
          setSummary(`上次扫描：共检查 ${st.checked} 项依赖，缺失 ${(st.missing || []).length} 项`);
        }
        if (st.running) setBusy(true);
      })
      .catch(() => {});
  }, []);

  const scan = async () => {
    setBusy(true);
    setMissing([]);
    setSummary('正在后台扫描插件依赖 ...');
    try {
      const st = await runDeps('scan', (s) => setMsg(s.stage || '扫描中…'));
      absorb(st);
      const n = (st.missing || []).length;
      setSummary(`上次扫描：共检查 ${st.checked || 0} 项依赖，缺失 ${n} 项`);
      // st.error 来自后端 _scan_deps 的异常，里面可能是 pip 输出或路径：
      // 直接甩给用户看不懂，先说人话再附原文。
      setMsg(st.error
        ? `扫描出错，请把下面这段发给开发者：${st.error}`
        : (n ? `缺失 ${n} 项，可点「安装缺失依赖」` : '依赖齐全，无需安装'));
    } catch (e) {
      setMsg(withAuthHint(e));
      setSummary('扫描失败');
    } finally {
      setBusy(false);
    }
  };

  const installMissing = async () => {
    if (!missing.length) {
      setMsg('当前没有缺失依赖');
      return;
    }
    setBusy(true);
    try {
      const st = await runDeps('install', (s) => setMsg(s.stage || '安装中…'));
      setMissing([]);
      setSummary(`上次扫描：共检查 ${checked} 项依赖，缺失 0 项；缺失依赖已安装，建议重新扫描验证`);
      setMsg(st.error
        ? `安装出错，请把下面这段发给开发者：${st.error}`
        : `安装完成：成功 ${(st.installed || []).length} 项，建议重新扫描验证`);
    } catch (e) {
      setMsg(withAuthHint(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <header className="page-head">
        <div>
          <h1>依赖管理</h1>
          <p>扫描 src/plugins 下所有插件声明的依赖，检测缺失并一键安装（清华镜像，失败自动切官方源）</p>
        </div>
      </header>

      <section className="card dep-scan">
        <p className="dep-value">{summary}</p>
        <p className="card__note">扫描过程在后台任务中执行，页面不会卡顿；发现缺失依赖后会显示在下方清单中。</p>
        <div className="p-row">
          <button type="button" className="btn btn--primary" onClick={scan} disabled={busy}>
            开始全量扫描
          </button>
          <button
            type="button"
            className="btn"
            title="无头端没有本地文件管理器：点这里复制插件目录"
            onClick={() => copyServerPath(setMsg, '插件目录', pluginsDirPath)}
          >
            复制插件目录
          </button>
        </div>
      </section>

      <section className="card card--strong dep-missing">
        <h2 className="card__title">缺失依赖</h2>
        <div className="p-list dep-list">
          {missing.map((d) => (
            <div className="p-item" key={d}>
              {d}
            </div>
          ))}
        </div>
        <div className="p-row">
          <button
            type="button"
            className="btn btn--primary"
            disabled={!missing.length || busy}
            onClick={installMissing}
          >
            安装缺失依赖
          </button>
        </div>
      </section>

      {/* 这里原来是一张只有标题的「依赖任务」空卡片：页面顶部 dep-scan 已经写了
          扫描状态与进度，再挂一张空壳卡片只是白占版面，所以直接删掉，不再保留空卡片。 */}

      {msg && <div className="toast">{msg}</div>}
    </>
  );
}
