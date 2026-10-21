#!/usr/bin/env python3
"""Generate an image with the local MOSS-SFT (INT8) model through CPA.

Public entry point (works from anywhere, no VPN needed):

    POST https://your-gateway.example.com/v1/images/generations

This wrapper exists so that an agent never has to hand-roll the HTTP call:
it resolves the API key, validates parameters, decodes the base64 image,
writes it to disk and prints a machine-readable summary.

    moss_generate.py "a cozy bookshop interior, warm lamplight"
    moss_generate.py "a lighthouse in a storm" --size 1024 --quality speed --out storm.png
    moss_generate.py "a wide banner" --aspect 21:9 --size 1024     # -> 1008x432
    moss_generate.py "two ceramic mugs" --n 2 --seed 42
    moss_generate.py "a green leaf" --format webp --url        # data: URI instead of a file
    moss_generate.py "一只猫" --enhance                        # 先用扩写器把短 prompt 展开（多花 ~10-60s）
Defaults follow the official MOSS baseline: 768x768, 50 steps, cfg 3.0, euler/simple.
Use --quality speed for 25 steps (~15s instead of ~30s).

Exit codes: 0 ok | 1 bad arguments | 2 network/auth | 3 upstream rejected | 4 timeout
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://your-gateway.example.com"
DEFAULT_MODEL = "moss-image-sft-int8"
KEY_ENV_VARS = ("MOSS_CPA_API_KEY", "CPA_API_KEY")
SIZE_RE = re.compile(r"^(\d{2,5})\s*[x×*]\s*(\d{2,5})$")

# Local overrides that never travel with the repo. Any of these keys may appear:
#   MOSS_CPA_BASE / MOSS_CPA_API_KEY / MOSS_CPA_SSH_HOST
# Precedence: CLI flag > environment variable > this file > placeholder default.
# Reading a file (rather than relying on exported env vars) means the skill works
# no matter how it is invoked - agent subprocess, cron, GUI app, fresh shell.
CONFIG_FILE = os.environ.get(
    "MOSS_T2I_CONFIG",
    os.path.expanduser("~/.config/moss-t2i/config"))


class Fail(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- #
# local config + key resolution
# --------------------------------------------------------------------------- #

def local_config() -> dict:
    """Parse ~/.config/moss-t2i/config (KEY=VALUE lines, # comments)."""
    values = {}
    try:
        with open(CONFIG_FILE) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"[warn] cannot read {CONFIG_FILE}: {exc}", file=sys.stderr)
    return values


def setting(name: str, env_names: tuple, default: str = "") -> str:
    """CLI/env/config/default precedence for a single setting."""
    for env in env_names:
        value = os.environ.get(env, "").strip()
        if value:
            return value
    return local_config().get(name, "").strip() or default


def ssh_host() -> str:
    return setting("MOSS_CPA_SSH_HOST", ("MOSS_CPA_SSH_HOST",), "your-gateway-host")


def resolve_key(args) -> str:
    for name in KEY_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    if args.key:
        return args.key.strip()
    if args.key_file:
        text = open(args.key_file).read()
        match = re.search(r"(?:MOSS_)?(?:CPA_)?API_KEY\s*[=:]\s*(\S+)", text)
        if match:
            return match.group(1)
        raise Fail(1, f"no API key found in {args.key_file}")
    from_file = local_config().get("MOSS_CPA_API_KEY", "").strip()
    if from_file:
        return from_file
    if args.no_ssh:
        raise Fail(2, "no API key: set MOSS_CPA_API_KEY, put it in "
                      f"{CONFIG_FILE}, or pass --key")
    # Last resort: read the device key straight off the gateway host.
    host = ssh_host()
    try:
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
             "grep -A3 '^access:' /opt/cliproxyapi/config.yaml "
             "| grep -oE 'sk-[A-Za-z0-9]+' | head -1"],
            capture_output=True, text=True, timeout=30)
    except Exception as exc:
        raise Fail(2, f"could not look up the key over SSH ({exc}); set "
                      f"MOSS_CPA_API_KEY or put it in {CONFIG_FILE}") from exc
    key = out.stdout.strip()
    if not key:
        raise Fail(2, f"no API key: set MOSS_CPA_API_KEY, put it in "
                      f"{CONFIG_FILE}, or pass --key")
    print(f"[key] resolved from {host} over SSH", file=sys.stderr)
    return key


# --------------------------------------------------------------------------- #
# http
# --------------------------------------------------------------------------- #

def call(base: str, path: str, payload: dict, key: str, timeout: int) -> dict:
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}",
                 "User-Agent": "moss-t2i-skill/1.0"},
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(raw).get("error", {}).get("message", raw)
        except json.JSONDecodeError:
            detail = raw[:400]
        hint = ""
        if exc.code == 401:
            hint = " (check MOSS_CPA_API_KEY / --key)"
        elif exc.code == 400:
            hint = " (fix the request: see references/api-reference.md)"
        elif exc.code == 429:
            hint = " (queue full - the single GPU is busy, retry shortly)"
        elif exc.code in (502, 503):
            hint = " (the upstream ComfyUI is down or busy)"
        raise Fail(3 if exc.code >= 500 else 1,
                   f"HTTP {exc.code} from {path}: {detail}{hint}") from exc
    except urllib.error.URLError as exc:
        raise Fail(2, f"cannot reach {base} ({exc.reason})") from exc
    except TimeoutError as exc:
        raise Fail(4, f"timed out after {timeout}s") from exc
    try:
        return json.loads(body.decode("utf-8", "replace")), time.time() - started
    except json.JSONDecodeError as exc:
        raise Fail(2, f"non-JSON response from {path}: {body[:200]!r}") from exc


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

ASPECT_RATIOS = {"1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16", "21:9"}


def check_size(value, aspect: str | None):
    """Return the value to send as `size`, or None to let the server default it.

    - "1024x576"  explicit pixels (must be 16-multiples, 256..1024)
    - 1024        the long side; with --aspect the short side is derived, without
                  it the image is square
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise Fail(1, "size must be \"WxH\" or a single integer")
    text = str(value).strip().lower()
    if re.fullmatch(r"\d{2,5}", text):
        side = int(text)
        if side % 16:
            raise Fail(1, f"{side} is not a multiple of 16; try "
                          f"{(side // 16) * 16}")
        if not 256 <= side <= 1024:
            raise Fail(1, f"{side} is out of range [256, 1024] - the 16G card "
                          f"caps out at 1024 on the long side")
        return side
    match = SIZE_RE.match(text)
    if not match:
        raise Fail(1, f"size must look like 768x768, or a bare integer long side "
                      f"(with or without --aspect); got {value!r}")
    width, height = int(match.group(1)), int(match.group(2))
    for side in (width, height):
        if side % 16:
            suggestion = (side // 16) * 16
            raise Fail(1, f"{side} is not a multiple of 16; try "
                          f"{suggestion}x{(height // 16) * 16} or 768x768")
        if not 256 <= side <= 1024:
            raise Fail(1, f"{side} is out of range [256, 1024] - the 16G card "
                          f"caps out at 1024x1024")
    if aspect:
        a, b = (int(x) for x in aspect.replace("x", ":").split(":"))
        if abs(width / height - a / b) / (a / b) > 0.03:
            raise Fail(1, f"size {width}x{height} does not match --aspect {aspect}; "
                          f"drop one of them, or pass the long side as a bare integer")
    return f"{width}x{height}"


def decode_image(item: dict, fmt: str) -> bytes:
    """Accept b64_json, a data: URI, or a plain URL is not fetchable here."""
    if "b64_json" in item and item["b64_json"]:
        return base64.b64decode(item["b64_json"])
    url = item.get("url", "")
    if url.startswith("data:"):
        header, _, data = url.partition(",")
        if ";base64" not in header:
            raise Fail(2, "got a non-base64 data URI")
        return base64.b64decode(data)
    if url:
        raise Fail(2, f"upstream returned a bare URL ({url[:60]}...); this "
                      f"wrapper can only decode b64_json or data: URIs - "
                      f"use --format url only together with the default data URI mode")
    raise Fail(2, "response contained neither b64_json nor url")


def convert(data: bytes, fmt: str) -> tuple[bytes, str]:
    if fmt == "png":
        return data, "png"
    try:
        from PIL import Image
    except ImportError as exc:
        raise Fail(1, f"--format {fmt} needs Pillow ({exc})") from exc
    import io
    with Image.open(io.BytesIO(data)) as im:
        buf = io.BytesIO()
        if fmt in ("jpg", "jpeg"):
            im.convert("RGB").save(buf, "JPEG", quality=92, optimize=True)
        elif fmt == "webp":
            im.save(buf, "WEBP", quality=92)
        else:
            raise Fail(1, f"unsupported --format {fmt}")
        return buf.getvalue(), fmt


def default_name(ext: str) -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"moss-{stamp}.{ext}"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt", nargs="*", help="the text prompt (quote it)")
    ap.add_argument("--prompt", dest="prompt_opt", help="prompt as a flag")
    ap.add_argument("--negative", help="override the negative prompt")
    ap.add_argument("--enhance", "--prompt-enhance", dest="enhance", action="store_true",
                    help="expand the prompt with ComfyUI's TextGenerate first "
                         "(adds ~10-60s; short/vague prompts benefit most)")
    ap.add_argument("--size", default=None,
                    help="\"WxH\" explicit pixels, or a bare integer = the long side "
                         "(with --aspect). Omit to let the server default to 768.")
    ap.add_argument("--aspect", "--aspect-ratio", dest="aspect",
                    help="aspect ratio: " + ", ".join(sorted(ASPECT_RATIOS)))
    ap.add_argument("--quality", choices=["speed", "quality"], default="quality",
                    help="speed=25 steps (~15s), quality=50 steps (~30s). Default quality.")
    ap.add_argument("--steps", type=int, help="override steps directly (1-50)")
    ap.add_argument("--cfg", type=float, help="classifier-free guidance (default 3.0)")
    ap.add_argument("--sampler", help="sampler_name (default euler)")
    ap.add_argument("--scheduler", help="scheduler (default simple)")
    ap.add_argument("--seed", type=int, default=-1, help="-1 = random")
    ap.add_argument("--n", type=int, default=1, help="how many images (1-4, serial)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--format", dest="fmt", default="png",
                    choices=["png", "jpg", "jpeg", "webp"])
    ap.add_argument("--url", action="store_true",
                    help="ask for a data: URI and print it instead of writing a file")
    ap.add_argument("--out", help="output path (default moss-<timestamp>.<ext>)")
    ap.add_argument("--base", help="gateway base URL (default: $MOSS_CPA_BASE, "
                    f"then {CONFIG_FILE}, then {DEFAULT_BASE})")
    ap.add_argument("--key")
    ap.add_argument("--key-file")
    ap.add_argument("--no-ssh", action="store_true",
                    help="never fall back to SSH for the key")
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--json", action="store_true", help="print metadata as JSON")
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--health", action="store_true")
    args = ap.parse_args()

    try:
        return _run(args)
    except Fail as exc:
        print(f"ERROR: {exc.message}", file=sys.stderr)
        return exc.code


def _diagnostic(args, key: str) -> int:
    """--health / --list-models both just GET /v1/models (it is not a POST)."""
    base = (args.base or setting("MOSS_CPA_BASE", ("MOSS_CPA_BASE",), DEFAULT_BASE)).rstrip("/")
    url = base + "/v1/models"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            code, body = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        code, body = exc.code, exc.read()
    except urllib.error.URLError as exc:
        raise Fail(2, f"cannot reach {base} ({exc.reason})") from exc
    if args.health:
        print(f"{base} -> HTTP {code}")
        return 0 if code == 200 else 2
    if code != 200:
        raise Fail(2, f"HTTP {code} from /v1/models: {body[:200]!r}")
    print(json.dumps(json.loads(body.decode("utf-8", "replace")), indent=2))
    return 0

def _run(args) -> int:
    base = (args.base or setting("MOSS_CPA_BASE", ("MOSS_CPA_BASE",), DEFAULT_BASE)).rstrip("/")
    if args.list_models or args.health:
        return _diagnostic(args, resolve_key(args))

    prompt = " ".join(args.prompt).strip() or (args.prompt_opt or "").strip()
    if not prompt:
        print(__doc__.strip(), file=sys.stderr)
        return 1

    if args.aspect and args.aspect.replace("x", ":") not in ASPECT_RATIOS:
        raise Fail(1, f"unknown --aspect {args.aspect!r}; supported: "
                      f"{', '.join(sorted(ASPECT_RATIOS))}")
    size = check_size(args.size, args.aspect)
    key = resolve_key(args)
    body = {
        "model": args.model,
        "prompt": prompt,
        "quality": args.quality,
        "n": args.n,
        "seed": args.seed,
        "response_format": "url" if args.url else "b64_json",
    }
    if size is not None:
        body["size"] = size
    if args.aspect:
        body["aspect_ratio"] = args.aspect.replace("x", ":")
    if args.enhance:
        body["prompt_enhance"] = True
    for source, target in ((args.negative, "negative_prompt"), (args.cfg, "cfg"),
                           (args.sampler, "sampler_name"),
                           (args.scheduler, "scheduler"),
                           (args.steps, "steps")):
        if source is not None:
            body[target] = source

    payload, seconds = call(base, "/v1/images/generations", body, key,
                            args.timeout)
    data = payload.get("data") or []
    if not data:
        raise Fail(3, f"no image in response: {json.dumps(payload)[:300]}")

    usage = payload.get("usage", {})
    seeds = usage.get("seeds") or []
    results = []
    for index, item in enumerate(data):
        raw = decode_image(item, args.fmt)
        raw, ext = convert(raw, args.fmt)
        if args.url:
            print(f"data:image/{ext};base64,{base64.b64encode(raw).decode()}")
            results.append({"mode": "data-uri", "bytes": len(raw)})
            continue
        if args.n == 1 and args.out:
            path = args.out
        else:
            path = args.out or default_name(ext)
            if index:
                stem, dot, tail = path.rpartition(".")
                path = f"{stem}-{index + 1}.{tail}" if dot else f"{path}-{index + 1}"
        with open(path, "wb") as fh:
            fh.write(raw)
        results.append({"path": os.path.abspath(path), "bytes": len(raw)})

    meta = {
        "model": usage.get("model", args.model),
        "size": usage.get("size", size),
        "aspect_ratio": usage.get("aspect_ratio"),
        "steps": usage.get("steps"),
        "seeds": seeds,
        "seconds": usage.get("seconds", round(seconds, 2)),
        "images": results,
        "prompt": prompt,
    }
    if args.json:
        print(json.dumps(meta, indent=2))
    elif not args.url:
        for entry in results:
            print(entry["path"])
        print(f"[{meta['size']} {meta['steps']} steps, "
              f"{meta['seconds']}s, seed(s) {seeds}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
