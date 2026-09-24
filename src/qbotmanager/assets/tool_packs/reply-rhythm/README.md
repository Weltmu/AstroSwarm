# 回复节奏能力包（reply-rhythm）

行为包（behavior-pack），不提供可调用的工具函数，而是给回复管线提供
「真人回复节奏」参数：忙/在外面时慢几分钟回、闲时偶尔慢半拍。

## 配置说明

`behavior.json` 的 `activity_delay` 字段：

- `busy_long_probability`：忙碌时进入长延迟的概率（0~1）
- `busy_long_seconds`：长延迟区间（秒）
- `busy_short_seconds`：忙碌但未进入长延迟时的区间（秒）
- `idle_probability`：空闲时偶尔慢一点的概率（0~1）
- `idle_seconds`：空闲慢回区间（秒）

李清菡人设包内置本行为包：安装李清菡人设包即自动生效；卸载后恢复默认节奏。
