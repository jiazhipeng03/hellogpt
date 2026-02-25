需要购买audio token才能继续，中止了。
https://openai.com/zh-Hans-CN/api/pricing/

# hellogpt

Windows Python 原型：本地 Vosk 监听唤醒词 `你好GPT`，唤醒后连接 OpenAI Realtime WebSocket 做语音对话；在对话中识别到 `再见GPT` 后退出会话并回到待机。

## 功能

- 待机状态持续监听麦克风（本地 Vosk）
- 唤醒后进入 Realtime 语音对话
- 播放 Realtime 返回的 PCM 音频
- 识别退出词后断开 WebSocket，回到待机
- 控制台打印关键状态，便于验收

## 安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 准备 Vosk 中文模型

将 Vosk 中文模型解压到 `assets/vosk-model-cn/`。

## 配置

1. 复制 `.env.example` 为 `.env`
2. 配置 `OPENAI_API_KEY`
3. 按需修改唤醒词、退出词、音频设备

## 运行

```bash
python -m src.main
```

## 验收日志（关键输出）

- 启动后应看到：`STATE=IDLE_LISTENING`
- 唤醒成功后应看到：`STATE=IN_CALL`
- 退出会话后应再次看到：`STATE=IDLE_LISTENING`

## 说明

- 默认采样率为 24kHz、16-bit PCM、单声道
- 依赖 `semantic_vad`，服务端语音段结束时会尝试发送 `input_audio_buffer.commit` 和 `response.create`
- 若未安装依赖或未放置 Vosk 模型，程序会在启动时给出错误/警告

