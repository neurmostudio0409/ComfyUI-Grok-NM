# ComfyUI-Grok-NM

ComfyUI 的 xAI Grok API 整合套件:文字對話、視覺理解、Grok Imagine 圖片與影片生成。

## 節點一覽

| 節點 | 分類 | 功能 |
|------|------|------|
| Grok Chat 文字對話 | `AI/Grok/chat` | chat completions,支援 system prompt / temperature / max_tokens / seed |
| Grok Vision 視覺理解 | `AI/Grok/vision` | IMAGE + 提示詞 → 文字描述(batch 最多 8 張,單張 20 MiB 上限) |
| Grok Imagine 圖片生成 | `AI/Grok/image` | 文生圖,單次最多 10 張,回傳 IMAGE batch |
| Grok Imagine 影片生成 | `AI/Grok/video` | 文生 / 圖生影片(單張 `first_frame` 強制第一幀),非同步輪詢,輸出 `VIDEO` 型別 |
| Grok Imagine 參考圖影片・多圖 | `AI/Grok/video` | **多張參考圖**(IMAGE batch 全數送出,最多 8 張)引導風格、不強制第一幀;僅 `grok-imagine-video` 支援 |
| Grok Voice 文字轉語音 | `AI/Grok/audio` | TTS(eve/ara/leo/rex/sal + custom voice),輸出 `AUDIO` 型別 |
| Grok 模型列表 | `AI/Grok/utils` | 查詢帳戶可用模型(`GET /models`) |

> **設計原則:生成節點不自行保存。** 圖片輸出 `IMAGE`、影片輸出 `VIDEO`、語音輸出
> `AUDIO`,請接下游 **Save Image / Save Video / Save Audio** 決定保存位置——
> 節點本身只把影片暫存在 ComfyUI temp 目錄,不會在 `output/` 產生重複檔案。

## 安裝

1. 把本資料夾放進 `ComfyUI/custom_nodes/`
2. 執行 `install_requirements.bat`(自動使用 portable 版 `python_embeded`)
3. 複製 `config/.env.example` 為 `config/.env`,填入 API Key:

```env
XAI_API_KEY=xai-xxxxxxxx
```

API Key 從 [console.x.ai](https://console.x.ai) → **API Keys** 建立。

4. 重啟 ComfyUI

## 模型與計價(2026-07)

- **Chat / Vision**:`grok-4.5`、`grok-4.3` 等,下拉選單從 `GET /models` 動態載入(失敗時 fallback 內建列表)
- **圖片**:`grok-imagine-image`($0.02/張)、`grok-imagine-image-quality`($0.05/張)
- **影片**:`grok-imagine-video-1.5`($0.08/秒)、`grok-imagine-video`($0.05/秒,支援參考圖)
- **語音**:Voice API `POST /tts`,文字上限 15,000 字元,語速 0.7~1.5

影片為非同步 API:節點送出後自動輪詢 `GET /videos/{request_id}`,完成後下載到
temp 暫存並包成 `VIDEO` 型別輸出(另附 `video_url`),保存交給下游 Save Video。

## 結構

```
ComfyUI-Grok-NM/
├── __init__.py            # 節點註冊 + /grok/models 路由
├── config/
│   ├── settings.py        # 常數、分類、限制、.env 載入
│   └── .env.example
├── modules/
│   ├── grok_api.py        # xAI API 客戶端(chat/image/video/tts/models)
│   ├── grok_nodes.py      # ComfyUI 節點
│   └── media_utils.py     # IMAGE tensor ↔ base64、AUDIO 解碼、VIDEO 包裝
└── tests/                 # pytest(不打網路、不需 torch)
```

## 測試

```bash
pytest tests -v
```

GitHub Actions 於 push / PR 自動跑測試;推 `v*` tag 自動打包 zip 發 Release。

## API 路由

- `GET /grok/models` — 回傳帳戶可用模型列表(供前端 / 除錯使用)
