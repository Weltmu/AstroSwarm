import { useCallback, useEffect, useState } from 'react';
import { get } from './api.js';

/* 未登录时后端一律 401「请先登录」（/api/stats/summary、/api/messages/list 都要鉴权），
   以前这个原始错误被直接拼成「读取失败：请先登录」贴在首页第一屏上 —— 默认首启状态就长这样，
   用户看到的是报错而不是「去登录」。这里统一换成可读文案（登录入口仍在侧栏「星群账号」/
   顶栏账号按钮 → 设置 → 账号，不在这里另加按钮，避免首页多一个主操作）。 */
const LOGIN_HINT = '登录后显示（侧栏「星群账号」或设置 → 账号）';

/* 会话标题：后端 messages_list 现在会给 platform/scene/room（还有还原出来的 key），
   用它拼出「QQ 群 123456 / QQ 好友 123456 / 微信 好友 xxx」，和消息中心同一套写法。
   后端没给 scene/room（老版本）时退回 title/name/key/「未命名会话」。 */
const PLATFORM_LABELS = { qq: 'QQ', wechat: '微信', feishu: '飞书', telegram: '纸飞机' };
const SCENE_LABELS = { group: '群', private: '好友' };
function convLabel(c) {
  const given = String(c.title || c.name || '').trim();
  if (given) return given;
  const plat = PLATFORM_LABELS[String(c.platform || '').toLowerCase()] || '未知平台';
  const key = String(c.key || '');
  const room = String(c.room || '').trim() || (key.startsWith('group_') ? key.slice(6) : key);
  if (!room) return '未命名会话';
  const scene = String(c.scene || '').toLowerCase() || (key.startsWith('group_') ? 'group' : '');
  return `${plat} ${SCENE_LABELS[scene] || '会话'} ${room}`;
}

function isAuthError(e) {
  const m = String((e && e.message) || '');
  return m.includes('请先登录') || m.includes('未登录') || m.includes('401');
}

/**
 * 首页真实统计（P6）。
 *
 * 数据源：GET /api/stats/summary（后端读机器人真实落盘数据：ai_config 的 manager/memory/identity 文件）。
 * 以前首页那 5 行写的是桌面端的「今日数据」，无头端没有对应字段，于是永远显示「—」。
 */
export function StatsPanel({ loggedIn = true }) {
  const [st, setSt] = useState(null);
  const [err, setErr] = useState('');
  const [needLogin, setNeedLogin] = useState(false);

  const load = useCallback(async () => {
    if (!loggedIn) {                       // 没登录就别发这个必 401 的请求
      setSt(null);
      setErr('');
      setNeedLogin(true);
      return;
    }
    try {
      setSt(await get('/api/stats/summary'));
      setErr('');
      setNeedLogin(false);
    } catch (e) {
      setSt(null);
      if (isAuthError(e)) { setNeedLogin(true); setErr(''); } else { setNeedLogin(false); setErr(e.message); }
    }
  }, [loggedIn]);

  useEffect(() => { load(); }, [load]);

  const rows = st
    ? [
        // 按设计规范把同类信息压成一行：状态行越少，越看得出重点
        ['消息总数', st.messages ?? 0],
        ['记忆', `${st.memory_global ?? 0} 条 · ${st.memory_users ?? 0} 个用户`],
        ['身份绑定', st.identity_binds ?? 0],
        ['MCP', `${st.mcp_enabled ? '已开启' : '未开启'} · ${st.mcp_servers ?? 0} 个服务器`],
        ['当前模型', st.model || '未配置'],
      ]
    : [];

  return (
    <div className="stat-rows">
      {err ? (
        <div className="stat-row"><span>运行数据</span><b>读取失败：{err}</b></div>
      ) : needLogin ? (
        <div className="stat-row"><span>运行数据</span><b>{LOGIN_HINT}</b></div>
      ) : st ? (
        rows.map(([label, value]) => (
          <div className="stat-row" key={label}>
            <span>{label}</span>
            <b>{String(value)}</b>
          </div>
        ))
      ) : (
        <div className="stat-row"><span>运行数据</span><b>读取中…</b></div>
      )}
    </div>
  );
}

/**
 * 最近消息（P4）。
 *
 * 数据源：GET /api/messages/list（message_store 的会话索引，只回标量字段）。
 * 以前这里写死「暂无消息记录」，即便机器人已经聊了很多也不显示。
 */
export function RecentMessages({ onOpen, loggedIn = true }) {
  const [list, setList] = useState(null);
  const [err, setErr] = useState('');
  const [needLogin, setNeedLogin] = useState(false);

  const load = useCallback(async () => {
    if (!loggedIn) {
      setList(null);
      setErr('');
      setNeedLogin(true);
      return;
    }
    try {
      const d = await get('/api/messages/list?limit=8');
      /* load_conversations() 已经把 dsh 的 QQ 会话并进 conversations 了：这里按
         platform:room 去重，否则同一个会话会在首页出现两行。 */
      const convs = d.conversations || [];
      const seen = new Set(convs.map((c) => `${c.platform || ''}:${c.room || c.key || ''}`));
      const extra = (d.dsh || []).filter((x) => !seen.has(`qq:${x.key || ''}`));
      setList(convs.concat(extra));
      setErr('');
      setNeedLogin(false);
    } catch (e) {
      setList(null);
      if (isAuthError(e)) { setNeedLogin(true); setErr(''); } else { setNeedLogin(false); setErr(e.message); }
    }
  }, [loggedIn]);

  useEffect(() => { load(); }, [load]);

  const label = (c) => convLabel(c);
  const when = (c) => {
    const ts = Number(c.ts || 0);
    if (!ts) return '';
    try { return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false }); } catch { return ''; }
  };

  return (
    <div className="recent-list">
      {err ? (
        <div className="recent-list__empty">读取失败：{err}</div>
      ) : needLogin ? (
        <div className="recent-list__empty">{LOGIN_HINT}</div>
      ) : list === null ? (
        <div className="recent-list__empty">读取中…</div>
      ) : list.length ? (
        list.map((c, i) => (
          <button type="button" className="recent-item" key={`${label(c)}-${i}`}
                  onClick={onOpen} title="打开消息中心">
            <span className="recent-item__t">{label(c)}</span>
            <span className="recent-item__m">{c.count ? `${c.count} 条` : ''}{when(c) ? ` · ${when(c)}` : ''}</span>
          </button>
        ))
      ) : (
        <div className="recent-list__empty">还没有消息记录：机器人收到过消息后这里会出现会话。</div>
      )}
    </div>
  );
}
