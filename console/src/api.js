// 无头端控制台默认挂在根路径（FastAPI 直接托管 console-dist）。
// 预览版挂子路径时（nginx /preview/ → 反代 7860），构建时注入 VITE_API_BASE=/preview，
// 生产构建不带这个变量 → BASE 为空，行为与原来完全一致。
const BASE = (import.meta.env && import.meta.env.VITE_API_BASE) || '';

async function request(path, options = {}) {
  const token = localStorage.getItem('astroswarm_token');
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(BASE + path, {
    headers,
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.error || `HTTP ${res.status}`);
  }
  return data;
}

export const get = (path) => request(path);
export const post = (path, body) =>
  request(path, { method: 'POST', body: JSON.stringify(body) });
export const put = (path, body) =>
  request(path, { method: 'PUT', body: JSON.stringify(body) });
// SSE（EventSource 不能自定义 header，也不吃 fetch 的封装）要自己拼完整地址
export const apiUrl = (path) => BASE + path;

// 给「浏览器不能带 header」的请求用（EventSource 的日志流、<img> 的微信二维码）：
// 把登录 token 拼到查询串上。后端这两个接口同时接受 header 和 ?token=，
// 目的只是不让同一局域网里的其他人直接读到日志/扫码接管微信。
export const authUrl = (path) => {
  const token = localStorage.getItem('astroswarm_token');
  const full = BASE + path;
  if (!token) return full;
  return `${full}${full.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`;
};
