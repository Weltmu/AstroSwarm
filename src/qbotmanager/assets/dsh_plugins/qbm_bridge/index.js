/**
 * qbm-bridge — AstroSwarm 本地桥（dsh 侧服务插件）
 *
 * 打进 qqbot profile 与 dsh-qqbot 同进程运行，让微信/飞书等外部平台
 * 通过本地 HTTP 进入同一个 dsh agents 服务，实现"一个大脑、多个前端"。
 *
 * 协议（v1，本地回环）：
 *   POST /v1/message
 *   { "session_key": "wechat:private:<openid>", "text": "...",
 *     "sender_name": "..." , "is_group": false }
 *   -> { "session_id": "...", "reply": "..." }
 *
 * 会话规则：session_key 确定性 SHA-256 派生 SessionId（同 dsh-qqbot），
 * 同 key 自动续聊；跨平台用不同 key，天然隔离。
 *
 * 依赖 dsh 核心服务：ctx.agents（get/resume/create）+ session/event 出站。
 * 这些 API 处于 developer preview，M1 联调时若字段有变，只改本文件。
 */
import http from 'node:http';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { createUserMessage } from '@deepseek-ai/dsh-llm';
import Schema from '@deepseek-ai/schemastery';

export const name = 'qbm-bridge';
export const inject = ['agents', 'agentPresets'];

export const Config = Schema.object({
  host: Schema.string().default('127.0.0.1'),
  port: Schema.number().default(18650),
  provider: Schema.string().default('deepseek-official'),
  model: Schema.string().default('deepseek-v4-flash'),
  cwd: Schema.string(),
  preset: Schema.string().default('astros'),
  bindingsFile: Schema.string().default(''),
  debug: Schema.boolean().default(false),
});

function deriveSessionId(sessionKey) {
  const hash = createHash('sha256').update(sessionKey).digest('hex');
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-${hash.slice(12, 16)}-${hash.slice(16, 20)}-${hash.slice(20, 32)}`;
}

function extractText(message) {
  const blocks = message?.content;
  if (!Array.isArray(blocks)) return '';
  return blocks
    .filter((b) => b?.type === 'text' && b.text)
    .map((b) => b.text)
    .join('\n')
    .trim();
}

export async function apply(ctx, config = {}) {
  console.log('[qbm-bridge] apply() called');
  const agents = ctx.agents;
  const presets = ctx.agentPresets;
  const logger = ctx.logger ?? console;
  const host = config.host ?? '127.0.0.1';
  const port = Number(config.port ?? 18650);
  const cwd = config.cwd ?? process.cwd();
  const presetId = config.preset || 'astros';
  const bindingsPath = config.bindingsFile
    ? resolve(config.bindingsFile)
    : join(cwd, 'qbm_bindings.json');
  const debug = Boolean(config.debug);

  const sessions = new Map();   // sessionKey -> record
  const pending = new Map();    // sessionId -> [{resolve, timeout}]

  function readBindings() {
    try {
      const data = JSON.parse(readFileSync(bindingsPath, 'utf8') || '{}');
      return (data && typeof data === 'object') ? data : {};
    } catch {
      return {};
    }
  }

  // ── 出站：把 agent 回复转给等待中的 HTTP 请求 ──
  ctx.on('session/event', (session, evt) => {
    if (debug) {
      console.log('[qbm-bridge] event', session?.header?.id, evt?.type,
                  JSON.stringify(evt).slice(0, 240));
    }
    try {
      const sessionId = session?.header?.id;
      if (!sessionId || !pending.has(sessionId)) return;
      if (evt?.type === 'assistant/chunk') {
        const chunk = evt?.data?.chunk;
        const text = chunk?.type === 'text-delta' ? String(chunk.text ?? '') : '';
        if (text) {
          for (const p of pending.get(sessionId)) p.buffer += text;
        }
      } else if (evt?.type === 'assistant/message') {
        const text = extractText(evt?.data?.message);
        if (text) {
          // 整段消息是权威完整文本：直接用它覆盖流式累积，避免重复
          for (const p of pending.get(sessionId)) p.buffer = text;
        }
      } else if (evt?.type === 'turn/end') {
        const list = pending.get(sessionId);
        if (list) {
          pending.delete(sessionId);
          for (const p of list) {
            clearTimeout(p.timer);
            const kind = evt?.data?.reason?.kind ?? 'completed';
            const reply = p.buffer.trim();
            p.resolve({
              reply,
              session_id: sessionId,
              ...(reply ? {} : { turn_end: kind }),
            });
          }
        }
      }
    } catch (err) {
      logger.error(`qbm-bridge event handler: ${err instanceof Error ? err.message : String(err)}`);
    }
  });

  // ── getOrCreate：live → resume → create（对齐 dsh-qqbot） ──
  async function getOrCreate(sessionKey, route) {
    const existing = sessions.get(sessionKey);
    if (existing) return existing;
    const sessionId = deriveSessionId(sessionKey);
    let agent;
    let handle;
    const setup = async (agentCtx) => {
      if (presets) await presets.mount(agentCtx, presetId);
    };
    const live = agents.get(sessionId);
    if (live) {
      agent = live;
      handle = { agent, dispose: async () => {} };
    } else {
      try {
        const resumed = await agents.resume({
          resumeSessionId: sessionId,
          ...(route ? { agentOptions: route } : {}),
          ...(presets ? { setup } : {}),
        });
        agent = resumed.agent;
        handle = resumed;
      } catch {
        const created = await agents.create({
          sessionId,
          meta: { cwd },
          ...(route ? { agentOptions: route } : {}),
          ...(presets ? { setup } : {}),
        });
        agent = created.agent;
        handle = created;
      }
    }
    const record = { sessionKey, sessionId, agent, handle, lastActivity: Date.now() };
    sessions.set(sessionKey, record);
    return record;
  }

  async function handleMessage(body) {
    let sessionKey = String(body?.session_key || '').trim();
    const text = String(body?.text || '').trim();
    if (!sessionKey || !text) return { error: 'session_key and text are required' };
    // 微信→QQ 同人绑定：绑定的账号直接复用 QQ 会话，跨平台记忆天然互通
    const mapped = readBindings()[sessionKey];
    if (typeof mapped === 'string' && mapped.trim() && mapped.trim() !== sessionKey) {
      console.log(`[qbm-bridge] binding ${sessionKey} -> ${mapped.trim()}`);
      sessionKey = mapped.trim();
    }

    const route = {
      provider: config.provider ?? 'deepseek',
      model: config.model ?? 'deepseek-v4-flash',
    };
    const record = await getOrCreate(sessionKey, route);
    const message = createUserMessage({
      content: [{ type: 'text', text }],
      source: { kind: 'user' },
    });

    // 同一会话串行：等上一个请求完成再发（简单队列）
    const reply = await new Promise((resolve, reject) => {
      const list = pending.get(record.sessionId) ?? [];
      const entry = { buffer: '', resolve, reject, timer: null };
      list.push(entry);
      pending.set(record.sessionId, list);
      entry.timer = setTimeout(() => {
        const arr = pending.get(record.sessionId);
        if (arr) {
          const i = arr.indexOf(entry);
          if (i >= 0) arr.splice(i, 1);
          if (arr.length === 0) pending.delete(record.sessionId);
        }
        reject(new Error('reply timeout'));
      }, 180000);
      record.agent.followup(message);
    });

    record.lastActivity = Date.now();
    if (debug) {
      console.log('[qbm-bridge] followup sent', record.sessionId, 'pending=', pending.size);
    }
    // 协议 v1：reply 必须是字符串（扁平结构），与文档保持一致
    return { session_id: record.sessionId, reply: reply.reply ?? '' };
  }

  const server = http.createServer((req, res) => {
    if (req.method === 'POST' && req.url === '/v1/message') {
      let raw = '';
      req.on('data', (c) => (raw += c));
      req.on('end', async () => {
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        try {
          const body = JSON.parse(raw || '{}');
          const result = await handleMessage(body);
          if (result.error) {
            res.statusCode = 400;
            res.end(JSON.stringify(result));
          } else {
            res.end(JSON.stringify(result));
          }
        } catch (err) {
          res.statusCode = 500;
          res.end(JSON.stringify({ error: err instanceof Error ? err.message : String(err) }));
        }
      });
      return;
    }
    res.statusCode = 404;
    res.end(JSON.stringify({ error: 'not found' }));
  });

  ctx.effect(() => {
    server.listen(port, host, () => {
      console.log(`[qbm-bridge] listening on http://${host}:${port}`);
      logger.info(`qbm-bridge listening on http://${host}:${port}`);
    });
    return () => {
      server.close();
      for (const list of pending.values()) {
        for (const p of list) {
          clearTimeout(p.timer);
          p.reject(new Error('bridge shutting down'));
        }
      }
      pending.clear();
    };
  });
}
