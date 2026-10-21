---
name: moss-t2i
description: |
  Generate images with the local MOSS-SFT (INT8) text-to-image model, reachable from
  anywhere through CPA at https://your-gateway.example.com/v1/images/generations (model
  `moss-image-sft-int8`). Use this whenever the user wants a picture drawn from a
  text description: 画一张图、生成图片、配图、插画、示意图、概念图、封面图、海报、
  photo-style render, illustration, concept art, "image of …", "visualize …", or when
  an agent needs a visual for a document / slide / README / blog post. Also use it
  when the user asks what image-generation tools are available, or wants to check
  whether the local image service is alive.
metadata:
  version: "1.0.0"
---

# MOSS-T2I 生图

一台带 16 GB 显存 GPU 的机器上跑着量化版 MOSS-SFT 文生图模型，已经包装成
OpenAI Images API 并通过 CPA 暴露到公网。**任何能跑 shell 的 agent 都能用它**，不需要
VPN、不需要知道内网地址。

链路：`你的脚本 → https://your-gateway.example.com → 网关机的 CPA → 内网 → 生图机的 ComfyUI → MOSS-SFT INT8`

## 最快路径：用封装好的脚本

`~/.agents/skills/moss-t2i/scripts/moss_generate.py` 已经把鉴权、参数校验、base64
解码、落盘全包了。**优先用它，不要手写 curl**——手写 curl 有 5 个容易踩的空
（key 从哪来、data URI 怎么解、多张图怎么命名、webp 怎么转、退出码怎么判），脚本都处理好了。

```bash
S=~/.agents/skills/moss-t2i/scripts/moss_generate.py

# 最常用：出一张 768×768 的图
python3 "$S" "a cozy bookshop interior, warm lamplight, 35mm photograph" --out bookshop.png

# 要更细的图：1024×1024 + 50 步（约 50s，显存吃满，慎用）
python3 "$S" "a lighthouse in a winter storm, dramatic sky" --aspect 1:1 --size 1024 --quality speed --out storm.png

# 一次出两张，固定种子便于复现
python3 "$S" "two ceramic mugs on a wooden shelf" --n 2 --seed 42 --out mugs.png

# 只要元数据不要文件（脚本化时用）
python3 "$S" "a single red apple on a white table" --json

# 探活 / 看模型列表
python3 "$S" --health
python3 "$S" --list-models
```

脚本成功时**把图片绝对路径打印在 stdout**，摘要（尺寸/步数/耗时/种子）打在 stderr，
所以 `$(python3 "$S" "..." --out x.png)` 能直接拿到路径。失败时非 0 退出码 +
stderr 上一行人类可读的原因。

## 参数怎么选

默认值就是 **MOSS 官方基线**：768×768、50 步、cfg 3.0、`euler`/`simple`。想快就
`--quality speed`（25 步，约 15s）。

| 场景 | 参数 |
|---|---|
| 文档配图、示意图、快速验证 | `--size 512 --aspect 1:1 --quality speed`（约 5s） |
| 默认，官方基线质量 | 什么都不加（768×768，50 步，约 30s） |
| 要快 | `--quality speed`（25 步，约 15s） |
| 封面图、要细节 | `--size 1024 --quality speed`（长边拉满，约 13–24s） |
| 横幅 / 竖图 / 宽屏 | `--aspect 16:9` / `9:16` / `21:9`，见下表 |
| 同一 prompt 要多张对比 | `--n 2`（串行，耗时翻倍） |
| 结果不满意想微调重抽 | 加 `--seed <上次的种子>` 只改 prompt，其它不变 |

### 尺寸与比例

两种问法：

```bash
--size 1024x576                    # 显式像素，比例必须自己算对
--aspect 16:9 --size 1024          # 1024 是长边，短边自动算 -> 1024x576
--aspect 16:9                      # 长边默认 768 -> 768x432
```

**每个比例实测的最大尺寸**（长边 1024，25 步，2026-10-21 在本机实测）：

| 比例 | 最大 W×H | 像素 | 耗时(25步) | 峰值显存 | 比例偏差 |
||---|---|---|---|---|---|
| `1:1` | 1024×1024 | 1,048,576 | 24.0 s | 15187 MiB | 0% |
| `4:3` | 1024×768 | 786,432 | 18.0 s | 14707 MiB | 0% |
| `3:4` | 768×1024 | 786,432 | 18.0 s | 14707 MiB | 0% |
| `3:2` | 1024×688 | 704,512 | 15.0 s | 14547 MiB | 0.78% |
| `2:3` | 688×1024 | 704,512 | 15.0 s | 14547 MiB | 0.78% |
| `16:9` | 1024×576 | 589,824 | 13.5 s | 14323 MiB | 0% |
| `9:16` | 576×1024 | 589,824 | 13.5 s | 14323 MiB | 0% |
| `21:9` | 1008×432 | 435,456 | 9.0 s | 14035 MiB | 0% |

换算到 50 步（`--quality quality`）耗时约翻倍，显存不变。比例偏差来自"边长必须是
16 的倍数"这个取整，只有 3:2 / 2:3 有 0.78%，肉眼看不出来；要绝对精确就自己算好
`--size WxH` 传显式像素。

### 硬约束

`size` 单边 256–1024 且是 16 的倍数；`steps` 1–**50**；`cfg` 0–**5.0**；`n` 1–4；
`aspect_ratio` 只认表里那 8 个。违反会返回 400，消息里直接给出合法值。

这些上限是**保护壳不是模型极限**，真正的天花板是显存：1:1 拉到 1024×1024 时峰值
15187/16380 MiB，只剩约 1.2G。所以同时只跑一张，别并发。

**单卡串行**：任何时刻只跑一张，别人在跑时你的请求会排队（上限 8 个，超出返回
429）。所以：出图前先跟用户说一句"正在生图，约 15 秒"，不要连发多张。

## 提示词怎么写

MOSS-SFT 是标准的扩散模型文生图，**吃描述性提示词，不吃关键词堆砌**。把画面要素
按"主体 → 环境 → 光线 → 视角/镜头 → 风格/媒介"的顺序写成一句自然话，效果最好：

```text
a cozy bookshop interior, warm lamplight, wooden shelves stacked with books,
a cat sleeping on the counter, 35mm photograph, shallow depth of field
```

- 用英文，描述具体到看得见的东西（材质、光线、颜色、镜头），别写"beautiful,
  amazing, high quality"这类空词——对扩散模型几乎无效。
- 默认已经带一条负向提示词（`nsfw, worst quality, bad anatomy, watermark,
  jpeg artifact`），一般不用管；要覆盖就 `--negative "..."`。
- **图中文字可以生成，但必须把文字本身写进 prompt**。只写"一个咖啡店招牌"，画面里的字就是
  乱码；把 `reads "OPEN" in tall white serif capitals, centered, clearly legible` 写清楚，
  字就能正确出现（实测 OCR 可准确读出 "OPEN"）。完整规则见 `references/prompting.md`。

### 短 prompt 用 `--enhance`

用户经常只给三五个字（"一只猫"、"加班到深夜的办公室"）。这种 prompt 直接喂给扩散模型，
画面要素太少，结果很平庸。ComfyUI 的 `TextGenerate` 节点就是干这个的：它用**同一个 9G
文本编码器**当 prompt 工程师，按"主体→动作→空间→场景→构图→光线→色调→文字"八个维度把
短 prompt 扩写成 200–500 词的详细英文描述，再送去出图。实测"一只猫"3 个字 → 1787 字符。

代价是**多跑一轮文本生成长文本**：512×512/25 步从 6.0s 变成 13.5s（+7.5s），768 约 +10s，
大图更多。所以：

- prompt 已经很详细（你自己写满了五段式）→ **不要开**，纯浪费时间。
- prompt 很短、很抽象、或者用户用中文随口一说 → **开**，收益远大于那几秒。
- 它自己也有随机性（`temperature=0.7`），同 seed 下开增强**不保证**复现同一张扩写结果。

## 什么时候不要用它

- **要精确的技术图**（架构图、流程图、时序图、ER 图、带标注的示意图）：用 Mermaid /
  SVG / matplotlib。扩散模型画不出准确的框、线、箭头和相对位置，用户会以为是 bug。
  **注意这只是说它不适合画"图"，不是说它不能画"字"**——招牌、海报、封面里的文字
  是可以生成的，写法见 `references/prompting.md`。
- **要改一张已有的图**（换背景、局部重绘、扩图）：本服务只有文生图，没有 edits 接口。
- **要数据图表**（柱状图、折线图）：用代码画，坐标轴才不会错。
- 用户只是问"有没有生图能力"：跑 `--health` 回答即可，别真的去烧 GPU。

如果用户要的是"示意图"但说不清精确度，先问一句"要 illustrative 的示意图还是要
准确的架构图"——前者用它，后者用 Mermaid。

## 可控与不可控

可控（都验证过真的作用到采样器上，不是回声参数）：

| 参数 | 默认 | 范围 |
|---|---|---|
| `size` / `--size` | 768×768 | WxH 或长边整数，单边 256–1024，16 的倍数 |
| `aspect_ratio` / `--aspect` | 无（正方） | 表里那 8 个比例 |
| `quality` / `--quality` | `quality`(50 步) | `speed`(25 步) / `quality`(50 步) |
| `steps` / `--steps` | 50 | 1–50 |
| `cfg` / `--cfg` | 3.0 | 0–5.0 |
| `sampler_name` / `--sampler` | `euler` | ComfyUI 的 45 个之一 |
| `scheduler` / `--scheduler` | `simple` | normal/karras/exponential/simple/… |
| `seed` / `--seed` | -1 随机 | -1 或 ≥0 |
| `n` / `--n` | 1 | 1–4，串行 |
| `negative_prompt` / `--negative` | 官方负向词 | 字符串（**整体覆盖**，不是追加）；传 `""` 表示不用负向词 |
| `prompt_enhance` / `--enhance` | `false` | 布尔；开启后先用 ComfyUI 的 `TextGenerate` 把 prompt 扩写成详细英文描述再出图 |
| `response_format` / `--url` | `b64_json` | `b64_json` / `url`(data URI) |
| `output_format` / `--format` | `png` | png / jpeg / webp |

不可控（有意固定，改了会破坏模型特性）：

| 参数 | 固定值 | 原因 |
||---|---|---|
| SLG 跳层（`SkipLayerGuidanceDiTSimple`） | `single_layers=22`、0.0→0.5 | MOSS 官方负分支配置；它和 CFG 是两套独立引导机制 |
| `denoise` | 1.0 | 纯文生图，没有输入图可 denoise |
| `batch_size` | 1 | 16G 显存不允许 batch>1 |
| 模型权重 | UNET/CLIP/VAE 三件套 | 只有一套 INT8 量化权重 |
| `stream` | 不支持 | 返回 400，提示改用异步任务 |

## 交付

- 图默认落在当前目录，命名 `moss-<时间戳>.png`；用 `--out` 指定更明确的名字。
- 交付时告诉用户：**文件绝对路径**、尺寸、耗时、种子。种子很重要——用户想微调时
  带上种子重抽，构图才不会飘。
- 需要把图嵌进文档/网页时，优先直接引用文件路径；只有下游必须要内嵌数据时再用
  `--url`（返回 `data:` URI，注意它会把整张图 base64 进输出，很长）。
- 生成后可以顺手打开给用户看（有 BrowserPreview 之类的工具时）。

## 出错怎么办

脚本的退出码：`0` 成功｜`1` 参数错｜`2` 网络/鉴权｜`3` 上游拒绝｜`4` 超时。
stderr 上那一行通常就够了。完整对照表见 `references/troubleshooting.md`。

最常见的三种：

| 现象 | 处理 |
|---|---|
| `ERROR: no API key` | 最常见原因是**换了终端/agent 没继承环境变量**。别依赖 export，把三项写进 `~/.config/moss-t2i/config`（权限 600），脚本自己会读 |
| `cannot reach …` / `non-JSON response` | 打到了占位符域名。`--base`、`MOSS_CPA_BASE` 或配置文件里的 `MOSS_CPA_BASE` 至少设一个 |
| `HTTP 429 ... queue full` | 单卡忙，等 10–30s 重试，别并发 |
| `HTTP 502/503` | 生图机上 ComfyUI 挂了或显存被别的程序占满，`--health` 看不动就报给用户 |
| `HTTP 400 steps must be … 1 and 50` | 超过保护壳上限了；官方基线就是 50，要更快用 `--quality speed`(25) |
| `HTTP 400 … not a multiple of 16` | 边长取整到 16 的倍数，或直接用 `--aspect` 让它算 |

## 参考

- `references/api-reference.md` —— 完整 HTTP 契约（字段、错误码、异步任务接口）。
  需要绕过脚本直接发请求、或要把服务接到别的系统时读它。
- `references/prompting.md` —— 提示词写法、尺寸/质量取舍、负面提示词。
- `references/troubleshooting.md` —— 症状 → 原因 → 处理对照表。

部署细节、运维命令、CPA 渠道配置在 pi-deploy 仓库的 `docs/09-moss-image-t2i.md`。
