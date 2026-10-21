# moss-t2i

一个给 AI agent 用的 **Skill**：让模型通过一句自然语言描述，调用本机（或内网）部署的
**MOSS-SFT (INT8) 文生图模型**出图。

底层是一条已经跑通的链路：

```
agent → CPA(OpenAI 兼容网关) → private network → ComfyUI → MOSS-SFT INT8
```

Skill 把调用细节全部封装好：鉴权、参数校验、base64 解码、落盘、退出码。agent 只需要
跑一行命令，不需要理解 HTTP、不需要知道内网地址、不需要手写 curl。

---

## 这个 Skill 让 agent 会做什么

- 用户说「画一张…」「生成个配图」「来个示意图」「illustration / concept art / image of …」时，
  知道有这么一个生图能力，并知道**怎么调用**。
- 知道**参数怎么选**：尺寸、比例（8 种）、步数两档、cfg、种子、负向词、是否开提示词增强。
- 知道**什么时候不该用**：精确的架构图/流程图/带标注的示意图应该用 Mermaid/SVG，
  数据图表应该用代码画——扩散模型画不准框线箭头和相对位置（但图中的**文字**是可以生成的）。
- 知道**怎么写提示词**：五段式结构、负面词、短 prompt 用扩写器。

---

## 安装

### 方式 A：直接装进 PI-Desktop / Claude（推荐）

解压 `moss-t2i.skill`（就是个 zip），把里面的 `moss-t2i/` 目录放到 skills 目录：

```bash
# PI-Desktop
unzip moss-t2i.skill -d ~/.agents/skills/

# 或 Claude Code
unzip moss-t2i.skill -d ~/.claude/skills/
```

装完**重启应用**（skills 列表是启动时扫描的），之后 agent 就能通过 Skill 机制加载它。

### 方式 B：不用 Skill 机制，直接跑脚本

```bash
chmod +x moss-t2i/scripts/moss_generate.py
python3 moss-t2i/scripts/moss_generate.py "a cozy bookshop interior, warm lamplight" --out bookshop.png
```

效果完全一样，只是 agent 需要你明确告诉它脚本路径。

---

## 依赖

- Python 3.8+，**纯标准库**（转 jpeg/webp 时才用到 Pillow，可选）
- 一个能访问的生图服务（见下）
- 仅在使用「SSH 自动取 key」兜底时才需要 `ssh`

---

## ⚠️ 使用前必须配置的三项

脚本里的默认值是占位符，指向一个不存在的网关。三种覆盖方式，按优先级从高到低：

| 优先级 | 方式 | 适合 |
|---|---|---|
| 1 | 命令行参数 `--base` / `--key` | 临时试用 |
| 2 | 环境变量 `MOSS_CPA_BASE` / `MOSS_CPA_API_KEY` / `MOSS_CPA_SSH_HOST` | CI、一次性脚本 |
| 3 | **本地配置文件 `~/.config/moss-t2i/config`** | **推荐**，一次配置长期有效 |

### 推荐：本地配置文件

```bash
mkdir -p ~/.config/moss-t2i && chmod 700 ~/.config/moss-t2i
cat > ~/.config/moss-t2i/config <<'EOF'
MOSS_CPA_BASE=https://你的网关域名
MOSS_CPA_SSH_HOST=你的SSH别名
MOSS_CPA_API_KEY=sk-你的key
EOF
chmod 600 ~/.config/moss-t2i/config
```

**为什么推荐配置文件而不是环境变量**：环境变量依赖 shell 继承，已开着的终端、
agent 起的子进程、cron、GUI 应用都未必带得上——这是最常见的"脚本突然连不上"的原因。
配置文件是脚本自己读的，任何调用方式都能拿到。

三项都可以省，行为退化如下：

| 缺哪项 | 结果 |
|---|---|
| `MOSS_CPA_BASE` | 打占位符 `your-gateway.example.com`，必然连不上 |
| `MOSS_CPA_API_KEY` | 回退到 SSH 到 `MOSS_CPA_SSH_HOST` 那台机器，从 CPA 的 `config.yaml` 里读 key（需要免密登录） |
| `MOSS_CPA_SSH_HOST` | 同上，SSH 目标变成占位符 `your-gateway-host`，回退失败 |

配置文件路径也可用环境变量 `MOSS_T2I_CONFIG` 改到别处。

密钥**不在仓库里**。取 key 的完整优先级：`--key` > `MOSS_CPA_API_KEY`/`CPA_API_KEY`
环境变量 > `--key-file` > 上述配置文件 > SSH 回退。

---

## 快速上手

```bash
export MOSS_CPA_API_KEY=sk-你的key

# 最常用：默认参数（768×768 / 50 步 / cfg 3.0 / euler，即 MOSS 官方基线）
python3 moss-t2i/scripts/moss_generate.py "a cozy bookshop interior, warm lamplight" --out bookshop.png

# 要快：25 步
python3 moss-t2i/scripts/moss_generate.py "..." --quality speed

# 横幅：只给比例和长边，短边自动算
python3 moss-t2i/scripts/moss_generate.py "a wide panoramic mountain range" --aspect 21:9 --size 1024

# 短 prompt 先扩写再出图（多花 7–60s）
python3 moss-t2i/scripts/moss_generate.py "一只猫" --enhance

# 探活 / 看模型列表
python3 moss-t2i/scripts/moss_generate.py --health
python3 moss-t2i/scripts/moss_generate.py --list-models
```

完整参数、错误码、比例尺寸表见 [`moss-t2i/references/api-reference.md`](moss-t2i/references/api-reference.md)。

---

## 目录

```text
moss-t2i/
├── SKILL.md                       # 入口：触发条件、调用流程、参数选择、何时不该用
├── scripts/
│   └── moss_generate.py           # CLI 封装（prompt 进 → 图片文件出）
├── references/
│   ├── api-reference.md           # 完整 HTTP 契约 + 8 种比例的实测最大尺寸表
│   ├── prompting.md               # 五段式提示词模板、负面词、尺寸/质量取舍
│   └── troubleshooting.md         # 症状 → 原因 → 处理，含逐层定位顺序
└── evals/
    └── evals.json                 # 3 个测试 prompt
```

Skill 采用三级加载：元数据（name + description，常驻上下文）→ SKILL.md 正文（触发时加载）
→ references/（按需再读）。所以 SKILL.md 保持在 211 行，细节都放 references。

---

## 关于上游服务

这个 Skill 只是**客户端**，它不包含生图服务本身。原作者的上游是：

- 一台带 16 GB 显存 GPU 的机器，ComfyUI 跑 MOSS-SFT 的 INT8 量化版
  （UNET 5.04G + 文本编码器 9.08G + VAE 0.23G）
- 包成一个 OpenAI Images API，只监听内网地址，不对公网开放
- 一台网关机上的 CPA 用一条 `openai-compatibility` 渠道接上，公网统一走
  `https://…/v1/images/generations`

如果你要从零搭这套服务，`references/api-reference.md` 里的接口契约可以直接照着实现；
服务端实现参考原作者仓库里的 `api/moss_image_api.py`（约 900 行，纯标准库 + Pillow）。

---

## 已知限制

- **单卡串行**：任何时刻只出一张，排队上限 8。并发请求会被排队，不是并行。
- **1024 是硬上限**：显存决定，1:1 拉满时峰值约 15.2G / 16G。
- **没有图片编辑能力**：只有文生图，没有 img2img / inpaint / outpaint。
- **图中文字能生成，但要写进 prompt**：只写"一个招牌"字就是乱码；把 `reads "OPEN" in tall
  white serif capitals, clearly legible` 写清楚就能正确出现（实测 OCR 可读出）。要像素级
  精确的排版仍然用 SVG。
- **`stream` 不支持**：要进度就轮询（服务端有 `/v1/tasks` 异步接口）。

---

## License

MIT，见 [LICENSE](LICENSE)。
