# MOSS-T2I API 参考

公网入口：`https://your-gateway.example.com/v1/images/generations`
鉴权：`Authorization: Bearer <CPA 设备 key>`（与调用 CPA 上其它模型用同一个 key）

> 大多数情况请用 `scripts/moss_generate.py`，只有在需要绕过脚本、或要把服务接到
> 第三方系统时才直接发 HTTP。

## POST /v1/images/generations

### 请求字段

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `prompt` | string | **必填** | ≤8000 字符 |
| `model` | string | `moss-image-sft-int8` | 也可写 `moss-image` |
| `aspect_ratio` | string | 无（正方） | `1:1` `4:3` `3:4` `3:2` `2:3` `16:9` `9:16` `21:9` |
| `size` | string/int | 768 | `"WxH"` 显式像素，或**单个整数=长边**（配合 `aspect_ratio`） |
| `quality` | string | `quality` | `speed`→25 步，`quality`→50 步 |
| `steps` | int | 50 | 1–50；给了就覆盖 `quality` |
| `cfg` | number | 3.0 | 0–5.0 |
| `sampler_name` | string | `euler` | ComfyUI 的 45 个之一 |
| `scheduler` | string | `simple` | |
| `seed` | int | -1 | -1 随机；`n>1` 时固定种子逐张 +1 |
| `n` | int | 1 | 1–4，串行生成 |
| `negative_prompt` | string | `nsfw, worst quality, bad anatomy, watermark, jpeg artifact` | 整体覆盖，非追加；`""` = 不用负向词 |
| `prompt_enhance` | bool | `false` | 先用 ComfyUI `TextGenerate` 扩写 prompt 再出图（多花 ~7–60s） |
| `response_format` | string | `b64_json` | `b64_json` 或 `url` |
| `output_format` | string | `png` | `png`/`jpeg`/`webp` |
| `stream` | – | – | **不支持**，传了返回 400 |

`size` 与 `aspect_ratio` 的三种组合：

```json
"size": "1024x576"                        // 显式像素（给了 aspect_ratio 就必须匹配，偏差 >3% 报 400）
"aspect_ratio": "16:9", "size": 1024      // 1024 = 长边 -> 1024x576
"aspect_ratio": "16:9"                    // 长边默认 768 -> 768x432
```

短边按 16 取整，所以 3:2 / 2:3 会有 0.78% 的偏差，其余 6 个比例是精确的。

### 每个比例的最大尺寸（长边 1024，25 步实测）

| 比例 | W×H | 像素 | 耗时 | 峰值显存 |
|---|---|---|---|---|
| `1:1` | 1024×1024 | 1,048,576 | 24.0 s | 15187 MiB |
| `4:3` | 1024×768 | 786,432 | 18.0 s | 14707 MiB |
| `3:4` | 768×1024 | 786,432 | 18.0 s | 14707 MiB |
| `3:2` | 1024×688 | 704,512 | 15.0 s | 14547 MiB |
| `2:3` | 688×1024 | 704,512 | 15.0 s | 14547 MiB |
| `16:9` | 1024×576 | 589,824 | 13.5 s | 14323 MiB |
| `9:16` | 576×1024 | 589,824 | 13.5 s | 14323 MiB |
| `21:9` | 1008×432 | 435,456 | 9.0 s | 14035 MiB |

50 步耗时约翻倍，显存不变。真正的天花板是显存而不是这些数字：1:1 拉满时只剩约 1.2G。

### 不可控的参数

| 参数 | 固定值 | 原因 |
|---|---|---|
| SLG 跳层 `SkipLayerGuidanceDiTSimple` | `single_layers=22`、0.0→0.5 | MOSS 官方负分支配置，与 CFG 是两套独立机制 |
| `denoise` | 1.0 | 纯文生图 |
| `batch_size` | 1 | 16G 显存 |
| 模型权重 | UNET/CLIP/VAE 三件套 | 只有一套 INT8 量化权重 |

### 响应（200）

```json
{
  "created": 1792589758,
  "data": [
    {"b64_json": "iVBORw0KGgo…", "revised_prompt": "你发的 prompt 原文"}
  ],
  "usage": {
    "images_generated": 1,
    "model": "moss-image-sft-int8",
    "size": "768x768",
    "aspect_ratio": null,
    "steps": 50,
    "cfg": 3.0,
    "seeds": [843091416],
    "seconds": 30.02
  }
}
```

`response_format=url` 时 `data[0].url` 是 `data:image/png;base64,…` 形式的 data URI
（自带 MIME，任何客户端都能直接用，不依赖内网可达）。

### 错误

统一信封 `{"error": {"message", "type", "code", "param"}}`。

| HTTP | type / code | 含义 |
|---|---|---|
| 400 | `invalid_request_error` / `invalid_size` | 尺寸不合法，message 里会给合法建议 |
| 400 | `invalid_request_error` / `invalid_aspect_ratio` | 比例不在支持的 8 个里 |
| 400 | `invalid_request_error` / `size_ratio_mismatch` | `size` 与 `aspect_ratio` 对不上 |
| 400 | `invalid_request_error` / `missing_prompt` | 缺 prompt |
| 400 | `invalid_request_error` / `stream_unsupported` | 传了 `stream:true` |
| 400 | `invalid_request_error` / `invalid_steps` | `steps` 超过 50 |
| 400 | `invalid_request_error` / `invalid_cfg` | `cfg` 超过 5.0 |
| 401 | `authentication_error` | key 缺失或错误 |
| 429 | `rate_limit_error` / `queue_full` | 排队超过 8 个，带 `Retry-After` |
| 502 | `upstream_error` / `comfyui_error` | ComfyUI 执行失败或不可达 |
| 504 | `timeout_error` | 单张超过 900s |

## 最小可复现调用

```bash
curl -s -H "Authorization: Bearer $MOSS_CPA_API_KEY" \
     -H 'Content-Type: application/json' \
     -d '{"model":"moss-image-sft-int8","prompt":"a lone tree on a hill at dusk",
          "size":"768x768","quality":"quality"}' \
     https://your-gateway.example.com/v1/images/generations \
  | python3 -c 'import sys,json,base64;d=json.load(sys.stdin);open("out.png","wb").write(base64.b64decode(d["data"][0]["b64_json"]))'
```

## 异步任务（仅内网直连可用）

CPA 只透传 `/v1/images/generations`，不透传下面的路径。只有在你能访问
`your-image-server:8318` 时才能用，且要用**上游 key**（不是 CPA 设备 key）：

```bash
K=<生图机上 ~/.config/moss-image-api/env 里的 MOSS_API_KEY>
U=http://your-image-server:8318

TID=$(curl -s -H "Authorization: Bearer $K" -H 'Content-Type: application/json' \
      -d '{"prompt":"…","size":"768x768"}' $U/v1/tasks \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

curl -s -H "Authorization: Bearer $K" $U/v1/tasks/$TID
# {"id":"tsk_…","status":"queued|running|succeeded|failed|canceled",
#  "progress":0.5,"position":0,"seeds":[…],"seconds":…}

curl -s -H "Authorization: Bearer $K" $U/v1/tasks/$TID/result   # 就绪返回完整 images 响应，未就绪 202
curl -X DELETE -H "Authorization: Bearer $K" $U/v1/tasks/$TID  # 取消
```

任务状态只在内存中，服务重启即丢。长任务（排队久）时才值得用异步。

## 其它端点

| 端点 | 说明 |
|---|---|
| `GET /v1/models` | 模型列表，含 `moss-image-sft-int8` / `moss-image` |
| `GET http://your-image-server:8318/healthz` | 无需鉴权；`comfy: up/down`、队列深度、显存余量；ComfyUI 挂返回 503 |
| `GET http://your-image-server:8318/v1/images/<文件名>` | 取回已生成的文件（仅内网） |

## 给大模型当 tool 的声明

```json
{
  "name": "generate_image",
  "description": "Generate an image from a text prompt with the local MOSS-SFT model. Returns base64 PNG.",
  "input_schema": {
    "type": "object",
    "properties": {
      "prompt":  {"type": "string"},
      "aspect_ratio": {"type": "string", "enum": ["1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16", "21:9"], "default": "1:1"},
      "size":    {"type": "string", "description": "long side in px, 256-1024, multiple of 16", "default": "768"},
      "quality": {"type": "string", "enum": ["speed", "quality"], "default": "quality"},
      "prompt_enhance": {"type": "boolean", "default": false, "description": "expand a short/vague prompt first; costs ~7-60s extra"}
    },
    "required": ["prompt"]
  }
}
```

tool 超时建议 ≥120s：单卡串行，一次调用 5–50s，前面排了队会更久。
