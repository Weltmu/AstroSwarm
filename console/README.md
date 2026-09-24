# 星群控制台（网页前端）

Linux 无头版的网页界面：浏览器打开 `http://<服务器>:7860/` 看到的就是它。
React 18 + Vite，只有一个依赖面（react / react-dom），没有 UI 组件库和状态管理库。

## 构建

```bash
cd console
npm install
npm run build      # 产物写到仓库根的 console-dist/
```

`vite.config.js` 里 `outDir` 指的是仓库根的 `console-dist/` —— 这正是无头端要找的位置
（也可以设环境变量 `ASTROSWARM_CONSOLE_DIST` 指到别处）。
把 `console-dist/` 和 `src/` 一起放进安装目录，`install.sh` 就会自动铺好。

开发调试时控制台默认把 `/api` 代理到 `http://127.0.0.1:7860`（本机的无头端）：

```bash
npm run dev        # 打开提示的地址即可，登录/接口都走真实的本地无头端
```

## 文件

| 文件 | 作用 |
|---|---|
| `src/App.jsx` | 全部页面与业务逻辑（首页、插件、消息、日志、设置、通道、账号…） |
| `src/api.js` | 请求封装：带 token、401 统一识别为「未登录」、错误文案 |
| `src/appearance.js` | 外观（主题/字体/密度）读写 |
| `src/BrainStats.jsx` | 首页运行数据与最近消息 |
| `src/MemoryTimeline.jsx` | 记忆时间线 |
| `src/KnowledgeBase.jsx` | 知识库 |
| `src/ZipInstall.jsx` | 本地 zip 装能力包（仅开发者模式） |
| `src/tokens.css` / `src/tokens.json` | 设计变量（三套主题共用一份规则） |
| `src/styles.css` | 样式表 |

## 和后端的关系

所有数据都来自无头端 HTTP 接口（`src/astroswarm_linux/api.py` 与 `console_ext.py`），
前端不直连机器人进程、不读服务器文件。接口一律要登录态（`Authorization: Bearer <token>`），
只有探活与市场清单是公开的。

## 许可

Apache-2.0（见仓库根 `LICENSE`）。
