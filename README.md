# ComfyUI-Grok-NM

ComfyUI 的 xAI Grok API 整合套件:文字對話、視覺理解、Grok Imagine 圖片與影片生成。

## 節點一覽

| 節點 | 分類 | 功能 |
|------|------|------|
| Grok Chat 文字對話 | `AI/Grok/chat` | chat completions,支援 system prompt / temperature / max_tokens / seed |
| Grok Vision 視覺理解 | `AI/Grok/vision` | IMAGE + 提示詞 → 文字描述(batch 最多 8 張,單張 20 MiB 上限) |
| Grok Imagine 圖片生成 | `AI/Grok/image` | 文生圖,單次最多 10 張,回傳 IMAGE batch |
| Grok Imagine 圖片編輯・單/多圖 | `AI/Grok/image` | `/images/edits`:單一 `images` 孔位(batch / list 都吃),單圖編輯或**多圖合成**(官方上限 3 張) |
| Grok Imagine 影片生成 | `AI/Grok/video` | 文生 / 圖生影片(單張 `first_frame` 強制第一幀),非同步輪詢,輸出 `VIDEO` 型別 |
| Grok Imagine 參考圖影片・多圖 | `AI/Grok/video` | **多張參考圖**:`ref_image_1~4` 獨立輸入孔(**尺寸不限,免合批**)+ 可選同尺寸 batch,總上限 8 張;引導風格、不強制第一幀;僅 `grok-imagine-video` 支援 |
| Grok Voice 文字轉語音 | `AI/Grok/audio` | TTS(eve/ara/leo/rex/sal + custom voice),輸出 `AUDIO` 型別 |
| Grok 模型列表 | `AI/Grok/utils` | 查詢帳戶可用模型(`GET /models`) |

> **任務種子(seed)。** 圖片生成 / 圖片編輯 / 影片生成 / 參考圖影片 / 語音合成
> 都有一個 `seed` widget,控制設為 **randomize** 時每次送出佇列會自動換值。
> ComfyUI 會把「輸入完全相同」的節點視為已完成而**跳過執行**(log 只看到
> `Prompt executed in 0.0x seconds`),沒有這個 widget 時,重複送出同一組提示詞
> 會像是任務失敗,得改提示詞才跑得動。此值**不會送給 xAI**(這些端點沒有 seed
> 參數),純粹用來讓快取失效;要重複拿同一個結果把控制改成 **fixed** 即可。
>
> 從 **API(`POST /prompt`)**送工作流時(例如中控系統排程送任務),不會經過
> 前端,`control_after_generate` 不會換值。這五個節點另外實作了 `IS_CHANGED`:
> 工作流沒帶 seed(或 seed = 0)時一律重新執行,不會被快取跳過;要沿用上一次
> 的結果就帶同一個非 0 的 seed。

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

## ZDR 團隊帳號(影片生成)

如果影片節點回這個錯,代表你的 xAI **團隊**開了 Zero Data Retention:

```
Zero Data Retention teams must provide output.upload_url for video generation.
```

ZDR 下 xAI 不保存生成結果,所以沒有可供下載的代管網址,必須由呼叫方提供一個
presigned 上傳網址讓 xAI 把成品 `PUT` 進去。**ZDR 是 team 層級設定,無法只對
單一 API key 關閉** —— 同一份工作流換一把屬於 ZDR 團隊的 key 就會開始失敗。

一般帳號不受影響,也不需要任何設定。

### 二選一

**(A) 關閉 ZDR** — 到 [console.x.ai](https://console.x.ai) 關掉該 team 的 ZDR,
不必改任何設定。

**(B) 自備 S3 相容儲存** — 在 `config/.env` 填:

```env
XAI_OUTPUT_STORAGE=s3
XAI_OUTPUT_S3_ENDPOINT=https://xxxxxxxx.r2.cloudflarestorage.com
XAI_OUTPUT_S3_BUCKET=grok-video-output
XAI_OUTPUT_S3_REGION=auto
XAI_OUTPUT_S3_ACCESS_KEY_ID=...
XAI_OUTPUT_S3_SECRET_ACCESS_KEY=...
```

支援 AWS S3 / Cloudflare R2 / MinIO,全部設定項見 `config/.env.example`。
填好後重啟 ComfyUI。

運作方式:每次生成**各自**簽一組短效網址(預設 900 秒),影片存成
`<key_prefix><日期>/<uuid>.mp4`。xAI PUT 完成後節點再從同一個位置取回,
包成 `VIDEO` 輸出。

### 安全說明

- S3 金鑰只留在 `.env`,**只用於本機簽章,不會送給 xAI** —— 離開本機的只有
  簽好的網址
- 每次生成都是新的 object key(含 uuid4),presigned PUT **無法覆蓋**既有檔案
- presigned 網址本身就是該物件的通行證,主控台只印 `s3://bucket/key`,簽章一律遮蔽
- 但節點的 `video_url` 輸出在 ZDR 模式下是**含簽章的短效網址**。若把工作流
  連輸出一起存檔或分享,該網址在有效期內可被他人取用 —— 需要長期保存請接
  下游 Save Video,不要依賴這個字串
- 簽章不包含 Content-Type(xAI PUT 時帶什麼 Content-Type 官方未公開,
  簽進去會讓簽章失效)

> **尚待實機驗證。** 本功能依官方文件與錯誤訊息實作,但開發時手上沒有 ZDR
> 團隊帳號可測。SigV4 簽章已用 AWS 官方公開向量做單元測試釘住;真正未驗的是
> xAI 端的行為 —— PUT 的 Content-Type、完成回應是否仍帶 `video.url`。
> 程式兩種情況都處理:有 `video.url` 就用,沒有就從自備儲存取回。

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
│   ├── media_utils.py     # IMAGE tensor ↔ base64、AUDIO 解碼、VIDEO 包裝
│   └── output_storage.py  # ZDR 自備輸出儲存(SigV4 presign,無額外依賴)
└── tests/                 # pytest(不打網路、不需 torch)
```

## 測試

```bash
pytest tests -v
```

GitHub Actions 於 push / PR 自動跑測試;推 `v*` tag 自動打包 zip 發 Release。

## API 路由

- `GET /grok/models` — 回傳帳戶可用模型列表(供前端 / 除錯使用)

## 授權 License

本專案採用 [GNU General Public License v3.0](LICENSE) 授權。
This project is licensed under the GNU General Public License v3.0 — see the [LICENSE](LICENSE) file for details.
