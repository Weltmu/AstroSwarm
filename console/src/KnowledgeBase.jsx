import { useCallback, useEffect, useRef, useState } from 'react';
import { get, post } from './api.js';

/**
 * 本地知识库（无头端真接口版）。
 *
 * 对应桌面端 BrainPage 的「本地知识库」：上传 txt / md 文档，AI 可检索回答（数据不出本机）。
 * 后端：GET /api/knowledge/list | POST /api/knowledge/add | POST /api/knowledge/delete
 * 说明：桌面端是"选文件上传"，无头端没有 multipart（不额外装依赖），
 * 所以这里用 FileReader 读成文本再以 JSON 提交；也支持直接粘贴一段文本。
 */
export default function KnowledgeBase() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [sel, setSel] = useState('');
  const fileRef = useRef(null);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const d = await get('/api/knowledge/list');
      setItems(d.items || []);
      setTotal(d.total || 0);
      setSel('');
      setMsg(d.total ? '' : '知识库还是空的：添加文档后，群里问相关问题它会照着资料回答。');
    } catch (e) {
      setMsg(`读取失败：${e.message}`);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const pickFile = (file) => {
    if (!file) return;
    if (!/\.(txt|md|markdown|json|csv|log)$/i.test(file.name)) {
      setMsg('只支持 txt / md / json / csv / log 这类纯文本文件。');
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      setMsg('文件超过 2MB，请拆分后再上传。');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setText(String(reader.result || ''));
      if (!title) setTitle(file.name.replace(/\.[^.]+$/, ''));
      setAdding(true);
      setMsg(`已读入 ${file.name}，确认内容后点「保存到知识库」。`);
    };
    reader.onerror = () => setMsg('读取文件失败，请重试。');
    reader.readAsText(file);
  };

  const save = async () => {
    if (!text.trim()) { setMsg('内容不能为空。'); return; }
    setBusy(true);
    try {
      const r = await post('/api/knowledge/add', { title, text });
      setMsg(`已加入知识库：${r.doc?.title || title}（切成 ${r.doc?.chunks ?? '?'} 段）。重启机器人后生效。`);
      setTitle(''); setText(''); setAdding(false);
      await load();
    } catch (e) {
      setMsg(`保存失败：${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const removeOne = async () => {
    if (!sel) { setMsg('先选一篇要删除的文档。'); return; }
    const name = items.find((i) => i.id === sel)?.title || sel;
    if (!window.confirm(`确定删除《${name}》？\n文档与它的检索切片会一起删掉，重启机器人生效。`)) return;
    setBusy(true);
    try {
      await post('/api/knowledge/delete', { id: sel, confirm: true });
      setMsg(`已删除《${name}》。`);
      await load();
    } catch (e) {
      setMsg(`删除失败：${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <p className="card__note">
        本地知识库（数据不出本机）：上传 txt / md 文档，AI 可检索回答。
        {total ? ` 当前 ${total} 篇。` : ''}
      </p>
      <div className="brain-list brain-list--90">
        {busy && !items.length ? (
          <p className="brain-list__empty">读取中…</p>
        ) : items.length ? (
          items.map((d) => (
            <button
              type="button"
              key={d.id}
              className={`brain-item${sel === d.id ? ' brain-item--on' : ''}`}
              onClick={() => setSel(d.id)}
              title={`${d.id} · ${d.chunks} 段`}
            >
              <span className="brain-item__t">{d.title}</span>
              <span className="brain-item__m">{d.chunks} 段</span>
            </button>
          ))
        ) : (
          <p className="brain-list__empty">知识库为空</p>
        )}
      </div>

      {adding ? (
        <>
          <div className="kv-row kv-row--wide">
            <span>标题</span>
            <input value={title} spellCheck={false} onChange={(e) => setTitle(e.target.value)}
                   placeholder="不填就取正文第一行" />
          </div>
          <textarea
            className="brain-textarea"
            value={text}
            spellCheck={false}
            rows={6}
            onChange={(e) => setText(e.target.value)}
            placeholder="把资料粘在这里（或点「选择文件」读入 txt / md）"
          />
        </>
      ) : null}

      <div className="btn-row btn-row--6">
        <input
          ref={fileRef}
          type="file"
          accept=".txt,.md,.markdown,.json,.csv,.log"
          style={{ display: 'none' }}
          onChange={(e) => { pickFile(e.target.files && e.target.files[0]); e.target.value = ''; }}
        />
        <button type="button" className="btn btn--primary" onClick={() => fileRef.current && fileRef.current.click()} disabled={busy}>
          添加文档
        </button>
        {adding ? (
          <>
            <button type="button" className="btn btn--primary" onClick={save} disabled={busy}>保存到知识库</button>
            <button type="button" className="btn btn--ghost" onClick={() => { setAdding(false); setText(''); setTitle(''); }} disabled={busy}>
              取消
            </button>
          </>
        ) : null}
        <button type="button" className="btn btn--ghost" onClick={load} disabled={busy}>刷新</button>
        <button type="button" className="btn btn--ghost" onClick={removeOne} disabled={busy || !sel}>删除选中</button>
      </div>
      {msg ? <p className="card__note">{msg}</p> : null}
    </>
  );
}
