import { useCallback, useEffect, useState } from 'react';
import { authUrl, get, post } from './api.js';

/**
 * 记忆时间线（无头端真接口版）。
 *
 * 对应桌面端 BrainPage 的「记忆时间线（本地）」：读取机器人记忆库，可导出 / 单条删除 / 清空。
 * 后端：GET /api/memory/list | GET /api/memory/export | POST /api/memory/delete | POST /api/memory/clear
 * 安全：删除与清空都有代价（清空不可恢复），所以都要求二次确认；后端还会自动留一份 .bak 备份。
 */
export default function MemoryTimeline() {
  const [data, setData] = useState(null);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState(null);      // { scope: 'global'|'user', user, index }

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const d = await get('/api/memory/list');
      setData(d);
      setSel(null);
      setMsg(d.total ? '' : '还没有记忆：和机器人聊过天之后，这里会出现它记住的事。');
    } catch (e) {
      setMsg(`读取失败：${e.message}`);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const removeOne = async () => {
    if (!sel) { setMsg('先在下面选一条要删除的记忆。'); return; }
    const label = sel.scope === 'global' ? '全局记忆' : `用户 ${sel.user} 的记忆`;
    if (!window.confirm(`确定删除这条${label}？\n后端会自动留一份备份，但删除后机器人就记不得这件事了。`)) return;
    setBusy(true);
    try {
      const r = await post('/api/memory/delete', sel);
      setMsg(`已删除：${String(r.removed || '').slice(0, 40)}${r.backup ? `（备份：${String(r.backup).split(/[\\/]/).pop()}）` : ''}`);
      await load();
    } catch (e) {
      setMsg(`删除失败：${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const clearAll = async () => {
    const total = data?.total ?? 0;
    if (!total) { setMsg('现在没有记忆可清空。'); return; }
    if (!window.confirm(`确定清空全部 ${total} 条记忆？\n清空后不可恢复（后端会留一份 .bak 备份，但需要你自己去服务器上找回）。`)) return;
    setBusy(true);
    try {
      const r = await post('/api/memory/clear', { confirm: true });
      setMsg(`已清空 ${r.cleared} 条${r.backup ? `（备份：${String(r.backup).split(/[\\/]/).pop()}）` : ''}`);
      await load();
    } catch (e) {
      setMsg(`清空失败：${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const rows = [];
  // 后端 /api/memory/list 只回 global[-200:]（console_ext.memory_list），
  // 而删除接口是按**完整** data["global"] 的下标删的。
  // 全局记忆超过 200 条时，列表第 1 行其实不是第 1 条 —— 不回推 offset 就会删错条目，
  // 而且后端照样返回 ok，用户完全看不出来。这里与下面 users 分支用同一套回推。
  const globalOffset = Math.max(0, (data?.global_count || 0) - (data?.global || []).length);
  (data?.global || []).forEach((item, i) => {
    rows.push({ scope: 'global', user: '', index: globalOffset + i, text: toText(item), group: '全局' });
  });
  (data?.users || []).forEach((g) => {
    (g.items || []).forEach((item, i) => {
      // 后端只回每组最近 50 条，索引要按原数组算：用整组条数回推
      const offset = Math.max(0, (g.count || 0) - (g.items || []).length);
      rows.push({ scope: 'user', user: g.user, index: offset + i, text: toText(item), group: `用户 ${g.user}` });
    });
  });

  return (
    <>
      <p className="card__note">
        记忆时间线（本地）：读取机器人记忆库，可导出 / 单条删除 / 清空。
        {data ? ` 当前共 ${data.total} 条（全局 ${data.global_count || 0} 条，用户分组 ${(data.users || []).length} 个）。` : ''}
      </p>
      <div className="brain-list brain-list--130">
        {busy && !rows.length ? (
          <p className="brain-list__empty">读取中…</p>
        ) : rows.length ? (
          rows.map((r) => (
            <button
              type="button"
              key={`${r.scope}-${r.user}-${r.index}`}
              className={`brain-item${sel && sel.scope === r.scope && sel.user === r.user && sel.index === r.index ? ' brain-item--on' : ''}`}
              onClick={() => setSel({ scope: r.scope, user: r.user, index: r.index })}
              title={`${r.group} · 第 ${r.index + 1} 条`}
            >
              <span className="brain-item__t">{r.text}</span>
              <span className="brain-item__m">{r.group}</span>
            </button>
          ))
        ) : (
          <p className="brain-list__empty">{msg && msg.startsWith('读取失败') ? msg : '无记忆记录'}</p>
        )}
      </div>
      <div className="btn-row btn-row--6">
        <button type="button" className="btn btn--ghost" onClick={load} disabled={busy}>刷新</button>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => window.open(authUrl('/api/memory/export?fmt=md'), '_blank', 'noopener')}
        >
          导出记忆
        </button>
        <button type="button" className="btn btn--ghost" onClick={removeOne} disabled={busy || !sel}>
          删除选中
        </button>
        <button type="button" className="btn btn--ghost" onClick={clearAll} disabled={busy || !(data?.total)}>
          清空
        </button>
      </div>
      {msg ? <p className="card__note">{msg}</p> : null}
    </>
  );
}

function toText(item) {
  if (typeof item === 'string') return item;
  if (item && typeof item === 'object') {
    for (const k of ['text', 'content', 'summary', 'fact', 'value']) {
      if (item[k]) return String(item[k]);
    }
    return JSON.stringify(item).slice(0, 200);
  }
  return String(item ?? '');
}
