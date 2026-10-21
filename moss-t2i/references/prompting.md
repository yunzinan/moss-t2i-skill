# MOSS-T2I 提示词写法

MOSS-SFT 是扩散模型文生图，和 LLM 的提示词逻辑不同：**它奖励具体、可视、有序的
描述，惩罚空泛的形容词堆砌**。这份文档讲怎么把需求翻成它能听懂的 prompt。

## 五段式结构

按这个顺序写，一句自然话，逗号分隔：

```
主体 → 环境/背景 → 光线 → 视角/镜头 → 风格/媒介
```

**例：文档配图（一个人在看书的安静场景）**

```text
a person reading a thick hardcover book at a wooden desk by a rain-streaked
window, stacks of books and a steaming mug beside them, soft overcast daylight
from the left, medium shot from across the desk, 35mm photograph, shallow depth
of field, muted warm tones
```

## 各类需求的骨架

| 需求 | 模板 |
|---|---|
| 写实照片 | `<主体>，<场景>，<自然光或棚拍布光>，<35mm/50mm/85mm> photograph，<景深>，<色调>` |
| 产品图 | `<产品> on <表面>，<纯色/场景化背景>，studio softbox lighting from upper left，product photography，centered composition， crisp focus` |
| 插画/概念图 | `<主体>，<环境>，<艺术风格：watercolor / flat vector illustration / cel-shaded anime / oil painting>，<配色>，<构图>` |
| 场景/氛围图 | `<场景>，<时间与天气>，<光源与方向>，<整体氛围>，wide angle establishing shot，cinematic |
| 抽象/装饰 | `<形状语言>，<配色>，<质感：grain / gradient / geometric>，centered，minimal，no text |

## 尺寸与质量怎么权衡

步数只有两档，都用官方 cfg 3.0：`--quality speed`=25 步，`--quality quality`=50 步（默认）。

| 档位 | 参数 | 耗时 | 峰值显存 | 适合 |
|---|---|---|---|---|
| 草稿 | `--aspect 1:1 --size 512 --quality speed` | ~5 s | ~14.0 G | 试 prompt、批量筛方向 |
| 快 | `--aspect 1:1 --size 768 --quality speed` | ~15 s | ~14.3 G | 文档配图、示意图 |
| 官方基线 | `--aspect 1:1 --size 768 --quality quality` | ~30 s | ~14.3 G | 默认，质量稳 |
| 大图 | `--aspect 1:1 --size 1024 --quality speed` | ~24 s | ~15.2 G | 要更多细节 |
| 极限 | `--aspect 1:1 --size 1024 --quality quality` | ~48 s | ~15.2 G | 海报级；**贴显存顶，别并发** |

非正方比例用 `--aspect`，长边一样能拉到 1024，像素更少所以更快更省：

| 比例 | 长边 1024 时 | 像素 | 25 步耗时 | 峰值显存 |
|---|---|---|---|---|
| `1:1` | 1024×1024 | 1,048,576 | 24.0 s | 15187 MiB |
| `4:3` | 1024×768 | 786,432 | 18.0 s | 14707 MiB |
| `3:4` | 768×1024 | 786,432 | 18.0 s | 14707 MiB |
| `3:2` | 1024×688 | 704,512 | 15.0 s | 14547 MiB |
| `2:3` | 688×1024 | 704,512 | 15.0 s | 14547 MiB |
| `16:9` | 1024×576 | 589,824 | 13.5 s | 14323 MiB |
| `9:16` | 576×1024 | 589,824 | 13.5 s | 14323 MiB |
| `21:9` | 1008×432 | 435,456 | 9.0 s | 14035 MiB |

- 先用 512 的草稿档把 prompt 试对，再升到目标尺寸重抽——比一上来就 1024 省一半时间。
- **prompt 太短就别硬写**：用户只给"一只猫"这种三五个字时，加 `--enhance` 让 ComfyUI 的
  `TextGenerate` 按八个维度扩写成 200–500 词英文描述，比你自己堆形容词效果好得多
  （代价是单张多 7–60s）。prompt 已经写满了五段式就别开，纯浪费。
- 横幅/封面/宽屏优先用 `16:9`、`3:2`、`21:9`，比把正方图裁掉一半更自然（构图是按比例生成的）。
- 想复现/微调：记住种子。`--seed <种子>` + 只改 prompt，构图和构图元素会保持，
  方便做 A/B。

## 负面提示词

默认值已经够用：

```text
nsfw, worst quality, bad anatomy, watermark, jpeg artifact
```

需要时再加强，常见追加项：

- 手/结构崩坏：`bad hands, extra fingers, mutated hands, deformed`
- 不要文字/水印：`text, signature, logo, username, border, frame`
- 不要的颜色或元素：`oversaturated, purple, lens flare`

覆盖默认值：`--negative "<你的>"`。注意会**整体替换**，不是追加。

## 两条硬约束

1. **要精确的技术图不要用它**。架构图、流程图、时序图、ER 图、带标注和连线的示意图，
   用 Mermaid / SVG / matplotlib——扩散模型画不出准确的框、线、箭头和相对位置，
   用户看到框线歪了会以为是 bug。**但这不等于它不能画文字**，见下。
2. **别写空词**。`beautiful, amazing, best quality, 8k, masterpiece` 对扩散模型
   收益极低，还会挤占真正有用的描述长度。写你**希望看见什么**。

## 图中文字：可以生成，前提是写清楚

这个模型**具备文字渲染能力**，不要因为"扩散模型通常画不好字"就替它放弃。实测
（768×768 / 50 步，同 seed）：

| prompt 写法 | OCR 读出 |
|---|---|
| `…a hanging wooden sign above the door reads "OPEN" in tall white serif capital letters, centered above the entrance, clearly legible…` | `OPEN` ← 准确 |
| `A rustic coffee shop storefront…`（完全不提文字） | `— ie a \ WS Ak i a a."` ← 乱码 |

差别只在**有没有把文字本身写进 prompt**。规则：

- **内容原样 + 双引号**：`reads "OPEN" in …`。要写的中文就保持中文，不要翻译。
- **说清载体**：sign / poster / card face / packaging / screen / T-shirt print。
- **说清位置和相对大小**：centered above the door、occupying the upper third。
- **说清字体风格和颜色**：tall white serif capitals、bold black sans-serif。
- **说清可读性**：clearly readable / slightly blurred / partly occluded。
- **别用占位词**：不要写 `some text`、`headline here`，要给出具体字符串。
- **短字符串远好于长段**：一个词、两三个词最稳；整段长文案容易糊。

```text
A minimalist poster for a jazz night. Centered text reads "BLUE NOTE" in bold
condensed sans-serif capitals, deep navy on a cream background, clearly legible,
occupying the upper third. Below it, smaller text reads "SAT 9PM · DOOR 8PM".
```

要**像素级精确**的排版（多行对齐、特定字号、真实字体文件）仍然应该用 SVG / HTML 渲染，
但这个模型足以产出"看起来是那么回事"的招牌、海报、封面字。

## 快速自检

出图后问自己三个问题，不合格就改 prompt 重抽（草稿档很便宜）：

- 主体是不是第一个被描述的？——扩散模型对开头的内容权重最高。
- 有没有写"看不见的东西"（情绪、抽象概念）？——改成可见的细节。
- 构图说清楚了吗？——补 `centered / medium shot / wide angle / close-up`。
