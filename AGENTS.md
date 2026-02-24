# hellogpt 开发约定

- 不引入 GUI，全部通过控制台日志验收
- 所有配置从 `.env` 读取
- 所有线程需要支持 Ctrl+C 优雅退出
- 待机阶段使用本地 Vosk；唤醒后使用 OpenAI Realtime WebSocket

