# AstroSwarm 星群（QBotManager）

> 一颗大脑，无数能力，任何通道。

把 AI 接进 QQ 和微信的自托管机器人中枢：Windows 桌面端 + Linux 无头版，一个账号管理多个机器人，
QQ 与微信共用同一套 AI 大脑、人设、记忆和授权。

**Windows 桌面端、Linux 无头端与网页控制台的源码都在本仓库，以 Apache-2.0 开源。** 官网与账号服务是可选的官方托管服务，不在本仓库内；客户端也可以指向你自建的账号服务。

- 桌面版：Windows（Python + PySide6，纯官方通道，数据本地）
- 无头版：Linux 服务器，浏览器里开控制台
- 手机端：星聊 App（单独发行）
- 官网与文档：<https://astroswarm.cn>

## 它能做什么

- 🤖 **QQ 机器人**：OneBot 标准协议接入（协议端如 LLOneBot / NapCat 由用户自备），群里 @ 即聊
- 💬 **微信机器人**：腾讯官方 iLink 通道，私聊 AI 回复
- 🧠 **统一 AI 大脑**：DeepSeek / 通义 / Kimi / 智谱 / OpenAI / 自定义接口
- 🧩 **插件与工具包**：人设、联网搜索、记忆、定时任务、群管理、回复节奏；插件是「目录 + `manifest.json`」的约定，可以自己写
- 🔐 **账号与登录**：默认走官方账号服务，也可以自建（见下文「账号服务地址」）
- 🖥️ **Linux 无头版**：Web 控制台管理，适合服务器托管

## 下载

- 官网下载中心：<https://astroswarm.cn/download.html>（附 sha256 校验值）
- 或前往 [Releases](../../releases)：

| 平台 | 文件 | 说明 |
| --- | --- | --- |
| Windows 安装版 | `AstroSwarm_Setup_*.exe` | 双击安装，自动创建桌面快捷方式 |
| Windows 便携版 | `AstroSwarm_*_Portable_*.zip` | 解压即用，绿色免安装 |
| Linux 无头版 | `astroswarm-linux-<版本>.tar.gz` | 服务器部署，解压后跑 `install.sh` |

> Windows 首次运行 exe 若出现「未知发布者」提示，点「更多信息 → 仍要运行」即可（暂未购买代码签名证书）。

## 一、Linux 无头版：三步装好

需要 Python 3.10+ 的 Linux（Debian/Ubuntu/CentOS 均可）。

```bash
# 1. 把发布包解压到任意目录，里面应当有 src/（或 app/）和 console-dist/
tar -xzf astroswarm-linux-<版本>.tar.gz -C ~ && cd ~/astroswarm

# 2. 安装（--systemd 装成开机自启服务；--bot 顺带装机器人运行时）
sudo bash install.sh --systemd --port 7860

# 3. 浏览器打开 http://<服务器IP>:7860/ ，注册/登录星群账号
```

安装脚本会：建虚拟环境、装齐后端依赖并**自检**（少一个就直接报错，不会装完带病运行）、
铺好 `app/` 与 `console-dist/`、初始化配置、可选装 systemd 服务（默认只监听 `127.0.0.1`，外网访问请用 nginx 反代）。

配置与登录态都在 `<安装目录>/data/`，**备份它 = 备份了整台机器人**。

### 账号服务地址（登录用）

控制台的账号相关操作（注册 / 登录 / 认领设备等）都要请求**星群账号服务**。
默认地址是官方托管服务 `https://astroswarm.cn/api/account`（站点的 nginx 把 `/api/account/*`
反代到账号服务），所以装完就能直接用，不需要任何额外配置。

要改成自建账号服务，按优先级从高到低任选一种：

| 方式 | 做法 |
|---|---|
| 配置文件（优先级最高） | `data/astroswarm/config.json` 里的 `"account_base"`，或在控制台「设置」里改 |
| 环境变量 | `ASTROSWARM_ACCOUNT_BASE=https://你的域名`（systemd 单元里加 `Environment=` 即可） |
| 装的时候一次写好 | `sudo bash install.sh --systemd --account-base https://你的域名` |

两种写法都认：`https://你的域名` 和 `https://你的域名/api/account`。
连不上账号服务时，登录页会直接提示「连不上星群账号服务（地址）：原因」，据此排查 DNS / 端口 / 反代。

## 二、Windows 桌面版

1. 运行 AstroSwarm.exe（或安装 AstroSwarm_Setup.exe）
2. 首次运行选择安装目录，等待部署完成
3. 「AI 大脑」页填 QQ 开放平台 AppID / AppSecret，配置模型
4. 「微信」页扫码绑定 ClawBot
5. 点「启动全部」

## 三、插件与工具包

插件是安装目录 `assets/` 下的一组文件：`manifest.json` 描述元信息与参数，`tools/*.py` 提供工具函数，机器人启动时自动加载。

- **装插件**：控制台「插件管理」里启用 / 禁用；开发者模式下也能直接上传本地 zip
- **自己写**：照 `src/qbotmanager/assets/tool_packs/qweather/` 抄一份目录结构与 `manifest.json`，改工具函数即可
- **可参考**：`assets/plugin_market/`（插件市场清单）、`src/qbotmanager/assets/plugins/`（AI 大脑、人设等内置插件）

> 想让 AI 直接帮你写插件，见 [`ROADMAP.md`](ROADMAP.md) 里的「AI 插件工坊」。

## 四、常见问题

| 现象 | 原因 / 处理 |
|---|---|
| 页面打开是空白 / 404 | 没铺 `console-dist`。放到安装目录，或设 `ASTROSWARM_CONSOLE_DIST` 指向它；启动日志里会有明确告警 |
| 机器人收到消息却不回 | 检查「AI 大脑」里的平台开关与 API Key；智能体档案模式下要填 `agent_owner_qq` |
| 微信扫码后没反应 | 二维码 2 分钟一换，点「重新扫码登录」；确认 `segno` 已装（安装脚本会装） |
| QQ 通道显示未连接 | 反向 WS 需要协议端（NapCat/LLOneBot）连到 `ws://<主机>:<bot_port>/onebot/v11/ws` |
| 微信通道必须付费吗 | 适配器源码就在本仓库，你可以自己接；付费买的是官方开通 + 扫码答疑 + 通道维护与更新。QQ 通道与全部能力包不收费 |
| 配置读不出来 | 日志里会有 `config.json 解析失败`，坏文件已另存 `.corrupt.*`，**能救回的字段（含登录态 account_token）已自动抢救**，其余字段回默认值；要整份回滚就用上一份好配置 `config.json.bak`（控制台「设置 → 回滚配置」或 `POST /api/config/restore-last-good`） |
| 登录页报「连不上星群账号服务」 | 账号服务地址不对或网络不通：改 `config.json` 的 `account_base`（或 `ASTROSWARM_ACCOUNT_BASE`） |

## 五、开发

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .            # 或见 install.sh 里的依赖清单
PYTHONPATH=src pytest tests -q
```

- 后端（Linux 无头端）：`src/astroswarm_linux/`
- 机器人核心与内置插件：`src/qbotmanager/`
- 网页控制台（Linux 无头版的网页界面）：`console/`（React + Vite）。
  构建：`cd console && npm install && npm run build`，产物写到仓库根的 `console-dist/`，由无头端直接托管
- 打包 Linux 客户包：`python tools/build_linux_release.py --version <版本> --console-dist <产物目录>`
- 交付包验收：`python tools/verify_linux_package.py <解包后的目录>`
- 公开导出：`python tools/export_public.py <输出目录>`（导出后自动复扫敏感串；**不要直接 push 现有历史**，见脚本里的说明）

## 六、许可、开源范围与收费

**开源范围**：Windows 桌面端、Linux 无头端、网页控制台，以及全部能力包 / 插件 / 人设包（含微信 iLink 适配器 `src/qbotmanager/assets/plugins/nonebot_adapter_ilink/`）都在本仓库，Apache-2.0（见 `LICENSE`）。仓库里没有"留一手的付费代码"——你自己接、自己改、自己部署都行。

**不收费的部分**：QQ 通道（官方 QQ 机器人或自备 OneBot 协议端）、AI 大脑（人设、记忆、主动聊天、群管理）、插件市场里的全部能力包（点歌、天气、定时提醒、打卡打工、知识库等），装好即用，不需要任何授权。

**收费的只有一项**：微信通道开通。收的不是代码，是开通、扫码答疑、通道维护与后续更新（微信走腾讯官方 iLink 通道）。你完全可以不付费、用仓库里的适配器自己接，只是那部分不含官方支持。

其他边界：

- 官网后端、账号与签发服务、服务器运维脚本属于私有部分，不在公开范围；客户端可以指向自建的账号服务（`account_base` / `ASTROSWARM_ACCOUNT_BASE` / `install.sh --account-base`）
- QQ 接入使用 OneBot 标准协议，**协议端（如 LLOneBot / NapCat）由用户自行安装和使用**，本项目不内置、不分发任何 QQ 协议端；使用第三方协议存在账号风险，请用小号测试、风险自担
- 微信使用腾讯官方 iLink 通道，能力以平台官方限制为准
- 使用云端大模型时，对话内容会发送给所选模型服务商
- 测试版按现状提供，不承诺稳定可用

## 七、路线图

近期方向见 [`ROADMAP.md`](ROADMAP.md)：AI 插件工坊（用自然语言让 AI 生成、校验并安装插件）、
插件权限与沙箱、多通道能力对齐等。

## 联系与支持

- 问题与建议：GitHub Issues
- QQ 交流群：768272849
- 官网：<https://astroswarm.cn>

© AstroSwarm 星群
