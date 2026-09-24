#!/usr/bin/env bash
# AstroSwarm（星群）Linux 无头版 · 客户自助安装脚本
#
# 用法：sudo bash install.sh [选项]
#   --port N            控制台端口（默认 7860）
#   --host H            监听地址（默认 127.0.0.1，只本机；要对公网请自己套 nginx 反代）
#   --root DIR          安装目录（默认脚本所在目录）
#   --systemd           装成 systemd 服务（开机自启）
#   --user NAME         服务运行用户（配合 --systemd，默认 root；建议建个专用用户）
#   --bot               顺带部署机器人运行时（首次要几分钟）
#   --no-deps          跳过 pip 安装（离线包已自带依赖时用）
#   --account-base URL  星群账号服务地址（默认官方托管 https://astroswarm.cn/api/account；
#                       自建账号服务才需要改，等价于环境变量 ASTROSWARM_ACCOUNT_BASE）
#
# 账号服务地址从哪来：控制台登录 / 认领设备 / 兑换码 / 拉权益都请求它。
# 默认用官方托管服务（astroswarm.cn 的 nginx 把 /api/account/* 反代到账号服务），
# 所以客户装完直接就能注册登录。要改成自建服务：
#   1) 重新跑安装脚本并带上 --account-base https://你的域名  （会写进 config.json）
#   2) 或在 systemd 单元里加 Environment=ASTROSWARM_ACCOUNT_BASE=https://你的域名
#   3) 或在控制台「设置」把 account_base 改掉
# 优先级：config.json 的 account_base > 环境变量 ASTROSWARM_ACCOUNT_BASE > 官方默认。
#
# 前置：Python 3.10+；解压出来的目录里应当有：
#   src/astroswarm_linux/   后端
#   src/qbotmanager/        机器人核心
#   console-dist/           控制台前端产物（没有它控制台会 404）
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE"
PORT=7860
BIND_HOST=127.0.0.1
SYSTEMD=0
RUN_USER="root"
WITH_BOT=0
WITH_DEPS=1
ACCOUNT_BASE="${ASTROSWARM_ACCOUNT_BASE:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --port)   PORT="$2"; shift 2 ;;
    --host)   BIND_HOST="$2"; shift 2 ;;
    --root)   ROOT="$2"; shift 2 ;;
    --user)   RUN_USER="$2"; shift 2 ;;
    --account-base) ACCOUNT_BASE="$2"; shift 2 ;;
    --systemd) SYSTEMD=1; shift ;;
    --bot)    WITH_BOT=1; shift ;;
    --no-deps) WITH_DEPS=0; shift ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    *) echo "未知参数：$1（-h 看用法）"; exit 1 ;;
  esac
done

say()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------- 0. 前置检查 ----------
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || die "没找到 python3，请先安装（apt install python3 python3-venv）"
PYVER="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
"$PY" -c 'import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)' \
  || die "需要 Python 3.10 及以上，当前 $PYVER"

SRC_APP=""
for cand in "$HERE/src" "$HERE/app" "$HERE"; do
  if [ -d "$cand/astroswarm_linux" ]; then SRC_APP="$cand"; break; fi
done
[ -n "$SRC_APP" ] || die "在 $HERE 下找不到 astroswarm_linux 源码（应放在 src/ 里）"

CONSOLE_SRC=""
for cand in "$HERE/console-dist" "$HERE/app/console-dist" "$SRC_APP/console-dist"; do
  if [ -f "$cand/index.html" ]; then CONSOLE_SRC="$cand"; break; fi
done

say "安装目录：$ROOT"
say "Python：$PY ($PYVER)　监听：$BIND_HOST:$PORT"
[ -n "$CONSOLE_SRC" ] || warn "没找到 console-dist（控制台前端产物）——装完浏览器打开会是 404，请把 console-dist 放进安装目录"

mkdir -p "$ROOT/app" "$ROOT/bin" "$ROOT/data"

# ---------- 1. 虚拟环境 + 依赖 ----------
if [ ! -x "$ROOT/venv/bin/python" ]; then
  say "创建虚拟环境"
  "$PY" -m venv "$ROOT/venv"
fi
VPY="$ROOT/venv/bin/python"

if [ "$WITH_DEPS" = "1" ]; then
  say "安装后端依赖（首次约 1-2 分钟）"
  "$VPY" -m pip install -q --upgrade pip
  INDEX="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
  # ⚠ 这些一个都不能少：
  #   pynacl       —— 市场清单验签 + 付费权益验签；缺了会被当成「清单可能被篡改」并按免费版跑
  #   cryptography —— 和风天气私钥生成
  #   segno        —— 微信登录二维码渲染（缺了二维码接口 503）
  #   httpx        —— 账号服务 / iLink 调用
  "$VPY" -m pip install -q -i "$INDEX" \
    fastapi 'uvicorn[standard]' pydantic httpx pynacl cryptography segno

  say "自检依赖（缺任何一个都会在这里直接报错，不再等到运行时静默降级）"
  "$VPY" - <<'PYEOF'
import importlib.util
import sys
need = {
    "fastapi": "后端框架", "uvicorn": "服务进程", "pydantic": "参数校验",
    "httpx": "账号服务调用", "nacl": "签名验签（pynacl）",
    "cryptography": "和风天气私钥", "segno": "微信二维码",
}
miss = [f"{m}（{why}）" for m, why in need.items() if not importlib.util.find_spec(m)]
if miss:
    print("缺少依赖：" + "、".join(miss))
    sys.exit(1)
print("  依赖齐全：" + "、".join(sorted(need)))
PYEOF
fi

# ---------- 2. 铺代码（app/ 下放 astroswarm_linux 与 qbotmanager）----------
if [ "$SRC_APP" != "$ROOT/app" ]; then
  say "复制代码到 $ROOT/app"
  rm -rf "$ROOT/app/astroswarm_linux" "$ROOT/app/qbotmanager"
  cp -r "$SRC_APP/astroswarm_linux" "$ROOT/app/astroswarm_linux"
  [ -d "$SRC_APP/qbotmanager" ] && cp -r "$SRC_APP/qbotmanager" "$ROOT/app/qbotmanager"
fi
[ -d "$ROOT/app/qbotmanager" ] || die "astroswarm_linux 同级缺 qbotmanager（机器人核心），源码树不完整"

if [ -n "$CONSOLE_SRC" ] && [ "$CONSOLE_SRC" != "$ROOT/console-dist" ]; then
  say "铺控制台前端产物到 $ROOT/console-dist"
  rm -rf "$ROOT/console-dist"
  cp -r "$CONSOLE_SRC" "$ROOT/console-dist"
fi

# ---------- 3. 启动器 ----------
cat > "$ROOT/bin/astroswarm" <<WRAPPER
#!/usr/bin/env bash
ROOT="$ROOT"
export PYTHONPATH="\$ROOT/app"
export ASTROSWARM_CONSOLE_DIST="\$ROOT/console-dist"
export XDG_DATA_HOME="\$ROOT/data"
export XDG_CONFIG_HOME="\$ROOT/data"
exec "\$ROOT/venv/bin/python" -m astroswarm_linux.cli "\$@"
WRAPPER
chmod +x "$ROOT/bin/astroswarm"

# ---------- 4. 初始化配置 ----------
say "初始化配置（端口 $PORT）"
XDG_DATA_HOME="$ROOT/data" XDG_CONFIG_HOME="$ROOT/data" PYTHONPATH="$ROOT/app" \
  "$VPY" -m astroswarm_linux.cli install --port "$PORT" || warn "cli install 返回非 0，请检查上面的输出"

# 账号服务地址：命令行给了就写进 config.json（不写则用官方托管默认值）。
# 注意写的是 config.json 里的 account_base，它优先级高于环境变量。
if [ -n "$ACCOUNT_BASE" ]; then
  say "账号服务地址写入配置：$ACCOUNT_BASE"
  ACCOUNT_BASE="$ACCOUNT_BASE" XDG_DATA_HOME="$ROOT/data" XDG_CONFIG_HOME="$ROOT/data" \
    PYTHONPATH="$ROOT/app" "$VPY" - <<'PYEOF' || warn "account_base 写入失败，请在控制台设置里手工填"
import os
from astroswarm_linux import headless_config
cfg = headless_config.load()
cfg["account_base"] = os.environ["ACCOUNT_BASE"]
headless_config.save(cfg)
print("  account_base =", headless_config.load().get("account_base"))
PYEOF
fi

# ---------- 5. systemd（可选）----------
if [ "$SYSTEMD" = "1" ]; then
  if [ "$(id -u)" != "0" ]; then die "--systemd 需要 root（sudo bash install.sh --systemd）"; fi
  say "安装 systemd 服务（用户：$RUN_USER）"
  if [ "$RUN_USER" != "root" ] && ! id "$RUN_USER" >/dev/null 2>&1; then
    warn "用户 $RUN_USER 不存在，先创建"
    useradd -r -s /usr/sbin/nologin "$RUN_USER" 2>/dev/null || true
  fi
  chown -R "$RUN_USER":"$RUN_USER" "$ROOT/data" 2>/dev/null || true
  cat > /etc/systemd/system/astroswarm.service <<UNIT
[Unit]
Description=AstroSwarm (astroswarm-headless) port $PORT
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$ROOT
Environment=PYTHONPATH=$ROOT/app
Environment=ASTROSWARM_CONSOLE_DIST=$ROOT/console-dist
Environment=ASTROSWARM_ACCOUNT_BASE=${ACCOUNT_BASE:-https://astroswarm.cn/api/account}
Environment=XDG_DATA_HOME=$ROOT/data
Environment=XDG_CONFIG_HOME=$ROOT/data
Environment=PYTHONUNBUFFERED=1
ExecStart=$ROOT/venv/bin/python -m astroswarm_linux.cli serve --host $BIND_HOST --port $PORT
Restart=always
RestartSec=3
# 基本加固：不给新特权、系统目录只读、家目录隔离（数据在 $ROOT/data，不受影响）
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=read-only
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl enable astroswarm.service >/dev/null 2>&1 || true
  systemctl restart astroswarm.service || warn "服务启动失败，看 journalctl -u astroswarm -n 50"
  sleep 3
  systemctl is-active astroswarm.service >/dev/null && say "服务已启动：systemctl status astroswarm" \
    || warn "服务没起来，看 journalctl -u astroswarm -n 50"
fi

# ---------- 6. 机器人运行时（可选）----------
if [ "$WITH_BOT" = "1" ]; then
  say "部署机器人运行时（首次需几分钟）"
  XDG_DATA_HOME="$ROOT/data" XDG_CONFIG_HOME="$ROOT/data" PYTHONPATH="$ROOT/app" \
    "$VPY" -m astroswarm_linux.cli deploy
fi

# ---------- 7. 收尾 ----------
echo ""
say "完成！"
echo "  启动控制台：$ROOT/bin/astroswarm serve --host $BIND_HOST --port $PORT"
echo "  浏览器打开：http://<服务器IP>:$PORT/（本机：http://127.0.0.1:$PORT/）"
[ "$BIND_HOST" = "127.0.0.1" ] && echo "  注意：当前只监听 127.0.0.1，公网访问请用 nginx 反代（别直接绑 0.0.0.0）。"
[ "$SYSTEMD" = "1" ] && echo "  服务管理：systemctl {start|stop|restart|status} astroswarm"
[ "$WITH_BOT" = "1" ] || echo "  还没装机器人运行时：$ROOT/bin/astroswarm deploy（或重跑 install.sh --bot）"
echo "  数据目录：$ROOT/data（备份它就等于备份了配置与登录态）"
echo "  账号服务：${ACCOUNT_BASE:-https://astroswarm.cn/api/account}（自建账号服务改 config.json 的 account_base）"
[ -n "$CONSOLE_SRC" ] || warn "提醒：没铺 console-dist，控制台页面会 404"
