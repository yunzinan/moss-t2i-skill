# MOSS-T2I 排障

按出现频率从高到低。脚本退出码：`0` 成功｜`1` 参数错｜`2` 网络/鉴权｜`3` 上游拒绝｜`4` 超时。

| 现象 | 原因 | 处理 |
|---|---|---|
| `ERROR: no API key` / `HTTP 401` | 没有 CPA 设备 key | `export MOSS_CPA_API_KEY=sk-…`；或让脚本走 SSH 自动取（默认行为，需要本机免密 `ssh` 到网关机） |
| `timed out after Ns` | 排队久 + 生图慢，超过 `--timeout` | 加大 `--timeout`（默认 420s），或先确认队列深度 |
| `non-JSON response` | 打到的不是 CPA（比如域名被改、走了代理） | 确认 `--base` 是 `https://your-gateway.example.com`，且本地没设指向别处的 `MOSS_CPA_BASE` |
| `1000 is not a multiple of 16` | 尺寸不合法 | 换成 16 的倍数（`768x768`/`992x992`/`1024x1024`），或直接用 `--aspect` 让它算 |
| `side is out of range [256, 1024]` | 超出单卡能力 | 16G 卡上限就是长边 1024；要更大只能换卡或加机器 |
| `unknown --aspect '5:4'` | 比例不支持 | 只支持 1:1 4:3 3:4 3:2 2:3 16:9 9:16 21:9 |
| `size 700 is a bare integer` | 少了 `--aspect` | 单个整数表示"长边"，必须配合 `--aspect` 用 |
| `size 1000x1000 does not match --aspect 16:9` | 两个参数冲突 | 二选一：要么显式 WxH，要么长边整数 + `--aspect` |
| `HTTP 429 ... queue full` | 单卡忙，排队超过 8 个 | 等 10–30s 重试；**不要并发发多张**，改成 `--n 2` 让服务端串行 |
| `HTTP 400 steps must be … 1 and 50` | 超过保护壳上限 | 官方基线就是 50 步；想快用 `--quality speed`(25 步) |
| `HTTP 400 cfg must be … 0 and 5.0` | 超过保护壳上限 | 官方基线就是 3.0 |
| `prompt enhancer system prompt not found` | `workflows/prompt_enhancer_system.txt` 被删了 | 不用 `--enhance` 也能出图；要恢复该文件，从 ComfyUI 的 UI 工作流子图里重新导出 |
| `HTTP 502 / 503` | 生图机上 ComfyUI 挂了，或显存被同机其它程序占满 | 跑 `python3 "$S" --health`（返回 `comfy: down` 就是这问题）。恢复：`ssh <生图机> 'systemctl --user restart moss-comfy'` |
1. **本地脚本**：`python3 "$S" --health` → 不通就是 key 或网络问题。
2. **CPA**：`ssh <网关机> 'systemctl is-active cliproxyapi'`；看 Keeper 里最近一条
   usage 记录的状态码（`/opt/cpa-usage-keeper/data/app.db` 的 `usage_events` 表）。
3. **内网服务**：`ssh <生图机> 'systemctl --user status moss-comfy moss-image-api'`，
   日志 `journalctl --user -u moss-image-api -n 50`。
4. **GPU**：`ssh <生图机> 'nvidia-smi'`，看是不是别的程序把 16G 占满了。

## 已知限制（不是故障）

- 单卡串行，同时只出一张，别人用时你要排队。
- 冷启动首张慢 30–40s（要加载 9G 文本编码器 + 5G UNET），之后每张 5–50s。
- 1024×1024 显存贴顶，同机有别的程序用 GPU 时可能 OOM。
- 没有图片编辑/扩图能力，只有文生图。
- 没有公网图片 URL，只有 base64 / data URI。

完整部署与运维文档：pi-deploy 仓库 `docs/09-moss-image-t2i.md`。
