# qbm-bridge（dsh 侧服务插件，PoC 草稿）

让微信/飞书等外部平台通过本地 HTTP 进入 dsh 的唯一大脑（与 dsh-qqbot 同进程）。

## 安装到 profile（M2 时由程序自动执行）

```sh
cd <root>/dsh
node node_modules/@deepseek-ai/dsh/lib/bin.js plugin --profile qqbot add file:<本目录>
```

## profile 配置（cordis.patch.yml 追加）

```yaml
- id: qbm-bridge
  config:
    host: 127.0.0.1
    port: 18650
    provider: deepseek
    model: deepseek-v4-flash
    cwd: D:\\path\\to\\dsh\\workspace
```

## 调用

```sh
curl -X POST http://127.0.0.1:18650/v1/message \
  -H "Content-Type: application/json" \
  -d '{"session_key":"wechat:private:o123","text":"你好","is_group":false}'
```

## M1 联调清单（未验证项）

- `agents.resume/create` 返回结构与 sessionId 字段
- `session/event` 事件类型名与字段（assistant/message、turn/end）
- 回复累积逻辑（增量 or 整段）
- 安装方式（file: 路径 add 是否进 bundles）
