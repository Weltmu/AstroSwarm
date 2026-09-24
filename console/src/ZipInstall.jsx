import { useEffect, useRef, useState } from 'react';
import { get, post } from './api.js';

/**
 * 本地 zip 安装（开发者模式）。
 *
 * 对应桌面端「选择 zip ... → 安装」：上传一个能力包 zip 安装到本机。
 * 安全（后端也各有一道，这里是第一道）：
 *  - 只有开发者模式开启才让点（按钮 disabled + 后端 403 双保险）
 *  - 安装前 window.confirm，明确"第三方包风险自负"
 *  - 只把文件内容（base64）发给后端，本地路径不出浏览器
 */
export default function ZipInstall() {
  const [devMode, setDevMode] = useState(false);
  const [name, setName] = useState('');
  const [b64, setB64] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);

  useEffect(() => {
    get('/api/console/dev-mode')
      .then((d) => setDevMode(Boolean(d.developer_mode)))
      .catch(() => setDevMode(false));
  }, []);

  const pick = (file) => {
    if (!file) return;
    if (!/\.zip$/i.test(file.name)) { setMsg('只支持 .zip。'); return; }
    if (file.size > 20 * 1024 * 1024) { setMsg('文件超过 20MB。'); return; }
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result || '');
      setB64(dataUrl.includes(',') ? dataUrl.split(',')[1] : '');
      setName(file.name);
      setMsg(`已读入 ${file.name}（${Math.round(file.size / 1024)}KB），点「安装」继续。`);
    };
    reader.onerror = () => setMsg('读取文件失败，请重试。');
    reader.readAsDataURL(file);
  };

  const install = async () => {
    if (!b64) { setMsg('先选一个 zip。'); return; }
    if (!window.confirm(`确定安装「${name}」？\n第三方能力包的兼容性、安全性与平台合规由你自负；装完需要重启机器人。`)) return;
    setBusy(true);
    try {
      const r = await post('/api/tools/install-zip',
        { filename: name, content_b64: b64, confirm: true });
      setMsg(`已安装：${r.pack?.name || name} v${r.pack?.version || '?'}。重启机器人生效。`);
      setB64(''); setName('');
      if (fileRef.current) fileRef.current.value = '';
    } catch (e) {
      setMsg(`安装失败：${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="p-row">
        <input
          className="p-input"
          value={name}
          readOnly
          placeholder={devMode ? '选择一个 .zip 能力包' : '本地 zip 安装需要先开启开发者模式'}
          title={devMode ? '' : '设置 → 开发者模式'}
        />
        <input
          ref={fileRef}
          type="file"
          accept=".zip"
          style={{ display: 'none' }}
          onChange={(e) => { pick(e.target.files && e.target.files[0]); }}
        />
        <button type="button" className="btn" disabled={!devMode || busy}
                onClick={() => fileRef.current && fileRef.current.click()}>
          选择 zip ...
        </button>
        <button type="button" className="btn btn--primary" disabled={!devMode || !b64 || busy}
                onClick={install}>
          安装
        </button>
      </div>
      <p className="p-drop">
        {devMode
          ? '⇩ 开发者模式已开启：可安装本机 zip 能力包（zip slip / 大小 / manifest 由后端校验）'
          : '⇩ 本地 zip 安装仅在开发者模式下可用（设置 → 开发者模式）'}
      </p>
      {msg ? <p className="card__note">{msg}</p> : null}
    </>
  );
}
