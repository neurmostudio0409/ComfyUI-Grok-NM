# ComfyUI-Grok-NM

ComfyUI 的 xAI Grok API 整合套件:文字對話、視覺理解、Grok Imagine 圖片與影片生成。

## 節點一覽

| 節點 | 分類 | 功能 |
|------|------|------|
| Grok Chat 文字對話 | `AI/Grok/chat` | chat completions,支援 system prompt / temperature / max_tokens / seed |
| Grok Vision 視覺理解 | `AI/Grok/vision` | IMAGE + 提示詞 → 文字描述(batch 最多 8 張,單張 20 MiB 上限) |
| Grok Imagine 圖片生成 | `AI/Grok/image` | 文生圖,單次最多 10 張,回傳 IMAGE batch |
| Grok Imagine 影片生成 | `AI/Grok/video` | 文生 / 圖生影片(最長 15 秒),非同步輪詢後自動下載 MP4 |
| Grok 模型列表 | `AI/Grok/utils` | 查詢帳戶可用模型(`GET /models`) |

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

影片為非同步 API:節點送出後自動輪詢 `GET /videos/{request_id}`,完成即下載到
`ComfyUI/output/grok/`,並輸出 `video_path` 與 `video_url`。

## 結構

```
ComfyUI-Grok-NM/
├── __init__.py            # 節點註冊 + /grok/models 路由
├── config/
│   ├── settings.py        # 常數、分類、限制、.env 載入
│   └── .env.example
├── modules/
│   ├── grok_api.py        # xAI API 客戶端(chat/image/video/models)
│   ├── grok_nodes.py      # ComfyUI 節點
│   └── media_utils.py     # IMAGE tensor ↔ base64、影片存檔
└── tests/                 # pytest(不打網路、不需 torch)
```

## 測試

```bash
pytest tests -v
```

GitHub Actions 於 push / PR 自動跑測試;推 `v*` tag 自動打包 zip 發 Release。

## API 路由

- `GET /grok/models` — 回傳帳戶可用模型列表(供前端 / 除錯使用)
