#!/usr/bin/env python3
"""
yt_clipper — free, standalone "viral YouTube clipper" (no n8n, no Vizard, no paid APIs).

Replaces lucaswalter/n8n-ai-automations `viral_youtube_video_clipper.json`:
  n8n form        -> command line argument (YouTube URL or local video file)
  Vizard AI (paid)-> yt-dlp (free download) + free LLM scoring (Groq/Gemini/OpenRouter
                     free tiers) or built-in heuristic scoring with NO api key at all
  ffmpeg          -> cuts the clips (free, open source)
  Slack messages  -> a markdown report + clip files on your disk

Usage:
  python3 yt_clipper.py "https://www.youtube.com/watch?v=VIDEO_ID" --max-clips 8 --min-score 9
  python3 yt_clipper.py my_video.mp4 --srt my_captions.srt --vertical --burn-subs

Free LLM (optional, better scoring — auto-detected):
  export FREE_LLM_API_KEY="gsk_..."          # Groq free key (default)
  # or: GEMINI_API_KEY / OPENROUTER_API_KEY
  # optional overrides: FREE_LLM_BASE_URL, FREE_LLM_MODEL
"""

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# ----------------------------------------------------------------------------- config

STRONG_HOOKS = [
    r"\bsecret", r"\bmistake", r"\bnobody\b", r"\bno one\b", r"\beveryone\b", r"\btruth\b",
    r"\bbiggest\b", r"\bworst\b", r"\breveal", r"\bhidden\b", r"\bproven\b", r"\bhack",
    r"\btrick\b", r"\bshocking\b", r"\binsane\b", r"\bcrazy\b", r"\bmillion", r"\bbillion",
    r"here'?s why", r"here'?s what", r"the reason", r"most people", r"you need",
    r"you have to", r"stop doing", r"won'?t believe", r"changed (everything|my life)", r"\bwarning\b",
]
WEAK_HOOKS = [r"\bnever\b", r"\balways\b", r"\bwhy\b", r"\bhow\b", r"\bbest\b", r"\bdon'?t\b", r"\bstop\b"]
FILLER = [r"welcome back", r"thanks for watching", r"subscribe", r"sponsor", r"\bchapter\b",
          r"see you next time", r"before we start", r"today we.?re going to talk", r"let me tell you about"]
NUMBER_RE = re.compile(r"\b\d+([.,]\d+)?\s*(%|percent|dollars|bucks|\$|k\b|m\b|x\b|years?|hours?|minutes?|days?)?", re.I)
YOU_RE = re.compile(r"\byou\b|\byour\b|\byou'?re\b", re.I)
CONTRAST_RE = re.compile(r"\bbut\b|\bhowever\b|\bthe problem\b|\bmost people\b|\binstead\b", re.I)
EMOTION_RE = re.compile(r"\blove\b|\bhate\b|\bfear\b|\bamazing\b|\bincredible\b|\bweird\b|\bscary\b|\bexcit", re.I)
CURIOSITY_RE = re.compile(r"what happens|find out|turns out|the truth|nobody tells|won'?t believe|wait (for it|until)|plot twist", re.I)

LLM_PROVIDERS = {
    "FREE_LLM_API_KEY":  ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "GROQ_API_KEY":      ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "GEMINI_API_KEY":    ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash"),
    "OPENROUTER_API_KEY": ("https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct:free"),
}


def find_ffmpeg():
    for cand in (os.environ.get("FFMPEG_PATH"), shutil.which("ffmpeg")):
        if cand and Path(cand).is_file():
            return str(Path(cand).resolve())
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    sys.exit("ERROR: ffmpeg not found. Install it (https://ffmpeg.org) or set FFMPEG_PATH.")


def slugify(text, maxlen=48):
    text = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:maxlen].strip("-") or "clip"


# ----------------------------------------------------------------------------- input handling

def is_url(target):
    return re.match(r"https?://", target) is not None


def download_video(url, workdir, ffmpeg_path, transcript_only=False, cookies_from_browser=None):
    """Download video + English captions with yt-dlp. Returns (video_path|None, sub_path|None, info)."""
    try:
        import yt_dlp
    except ImportError:
        sys.exit("ERROR: yt-dlp is needed for URLs. Install it:  pip install yt-dlp")

    opts = {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "outtmpl": str(workdir / "video.%(ext)s"),
        "merge_output_format": "mp4",
        "writeautosub": True,
        "writesubs": True,
        "subtitleslangs": ["en.*", "en"],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ffmpeg_location": str(Path(ffmpeg_path).parent),
    }
    if transcript_only:
        opts["skip_download"] = True
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)

    print(f"-> Downloading video + captions (yt-dlp) ...")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        sys.exit(
            f"\nERROR: yt-dlp could not download {url}\n  {str(e)[:400]}\n\n"
            "Common fixes:\n"
            "  1. Update yt-dlp:  pip install -U yt-dlp\n"
            "  2. If YouTube asks you to sign in (common on cloud servers/VPNs), pass browser cookies:\n"
            "       python3 yt_clipper.py URL --cookies-from-browser chrome   (or firefox/edge)\n"
            "  3. Or download the video any other way and clip the local file:\n"
            "       python3 yt_clipper.py video.mp4 --srt captions.srt"
        )

    sub_path = None
    for f in sorted(workdir.glob("video*.vtt")) + sorted(workdir.glob("video*.srt")):
        sub_path = f
        break
    videos = sorted(workdir.glob("video*.mp4"), key=lambda p: p.stat().st_size, reverse=True)
    if not videos:
        vids = sorted(workdir.glob("video.*"), key=lambda p: p.stat().st_size, reverse=True)
        videos = [v for v in vids if v.suffix not in (".vtt", ".srt", ".json")]
    video_path = None if transcript_only else (videos[0] if videos else None)
    return video_path, sub_path, info


def probe(ffmpeg_path, path):
    """Return (duration_seconds, width, height) by parsing ffmpeg output."""
    p = subprocess.run([ffmpeg_path, "-hide_banner", "-i", str(path)],
                       capture_output=True, text=True, timeout=120)
    blob = p.stderr
    dur = None
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", blob)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    size = None
    m = re.search(r",\s*(\d{2,5})x(\d{2,5})[\s\[]", blob)
    if m:
        size = (int(m.group(1)), int(m.group(2)))
    return dur, size


# ----------------------------------------------------------------------------- transcripts

def ts_to_seconds(ts):
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    parts = [float(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_vtt(path):
    """Parse .vtt/.srt into [(start, end, text)] with YouTube auto-caption rolling duplicates removed."""
    lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    cues, times, buf, prev_lines = [], None, [], []
    for line in lines + [""]:
        m = re.match(r"^\s*(\d+:\d+:\d+[.,]\d+)\s*-->\s*(\d+:\d+:\d+[.,]\d+)", line)
        if m or line.strip() == "" or line.strip().isdigit():
            if times and buf:
                new_lines = [l for l in buf if l and l not in prev_lines]
                if new_lines:
                    text = " ".join(new_lines).strip()
                    cues.append((times[0], times[1], clean_text(text)))
                prev_lines = [l for l in buf if l]
            if m:
                times = (ts_to_seconds(m.group(1)), ts_to_seconds(m.group(2)))
                buf = []
            elif line.strip() == "":
                times = None
            continue
        if times:
            buf.append(re.sub(r"<[^>]+>", "", line).strip())
    # merge micro-cues with identical timestamps
    merged = []
    for s, e, t in cues:
        if merged and abs(merged[-1][0] - s) < 0.05 and abs(merged[-1][1] - e) < 0.05:
            if t != merged[-1][2]:
                merged[-1] = (s, e, merged[-1][2] + " " + t)
        else:
            merged.append((s, e, t))
    return merged


def parse_srt(path):
    return parse_vtt(path)


def clean_text(t):
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", t)  # [Music] (applause)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def cues_to_sentences(cues):
    sents, buf, start, end = [], "", None, None
    for cs, ce, txt in cues:
        if not txt:
            continue
        if start is None:
            start = cs
        buf = (buf + " " + txt).strip()
        end = ce
        if (re.search(r'[.!?]["\')\]]*$', txt) and len(buf) > 20) or (end - start) > 15:
            sents.append((start, end, buf))
            buf, start = "", None
    if buf:
        sents.append((start, end, buf))
    return sents


def build_windows(sents, min_len, max_len):
    """Sliding windows of whole sentences, targeting the middle of the length range."""
    if not sents:
        return []
    n = len(sents)
    mid = (min_len + max_len) / 2
    step = max(1, n // 140)
    windows = []
    i = 0
    while i < n:
        j = i
        while j < n and sents[j][1] - sents[i][0] < mid:
            j += 1
        j = min(j, n - 1)
        dur = sents[j][1] - sents[i][0]
        if min_len * 0.7 <= dur <= max_len * 1.05:
            text = " ".join(s["2"] if isinstance(s, dict) else s[2] for s in sents[i:j + 1])
            windows.append({"start": sents[i][0], "end": sents[j][1], "text": text})
        i += step
    # drop near-duplicates
    out = []
    for w in windows:
        if not out or abs(out[-1]["start"] - w["start"]) > 2.0:
            out.append(w)
    return out


# ----------------------------------------------------------------------------- scoring

def heuristic_score(text, dur):
    """Score 0-10 with reasons, no API key needed. Calibrated so only strong hooks reach 9+."""
    text_l = text.lower()
    words = max(1, len(text_l.split()))
    reasons, score = [], 3.5

    strong = [h for h in STRONG_HOOKS if re.search(h, text_l)]
    if strong:
        rate = len(strong) * 40.0 / words          # hook density per ~40 words
        score += min(2.8, 0.9 * rate)
        reasons.append("hooks: " + ", ".join(re.sub(r"^\\b|\\b$", "", h) for h in strong[:4]))
    weak = [h for h in WEAK_HOOKS if re.search(h, text_l)]
    if weak:
        score += min(0.6, 0.3 * len(weak))

    nums = min(3, len(NUMBER_RE.findall(text)))
    if nums:
        score += min(1.5, 0.5 * nums)
        reasons.append("numbers/stats")

    nq = min(2, text.count("?"))
    if nq:
        score += 0.6 * nq
        reasons.append("questions")

    yous = len(YOU_RE.findall(text))
    if yous >= 3:
        score += 0.5
        reasons.append("talks to viewer")
    elif yous >= 1:
        score += 0.25

    if CONTRAST_RE.search(text_l):
        score += 0.4
        reasons.append("contrast/problem setup")
    if EMOTION_RE.search(text_l):
        score += 0.3
        reasons.append("emotion")
    if CURIOSITY_RE.search(text_l):
        score += 0.6
        reasons.append("curiosity gap")

    filler = [f for f in FILLER if re.search(f, text_l)]
    if filler:
        score -= min(1.0, 0.5 * len(filler))
        reasons.append("intro/filler talk (-)")

    if 25 <= dur <= 50:
        score += 0.5
        reasons.append("ideal length")
    elif 18 <= dur <= 60:
        score += 0.2

    return round(max(0.0, min(10.0, score)), 1), reasons or ["no strong viral signals"]


def best_title(window_text):
    """Pick the punchiest sentence as the clip title (heuristic mode)."""
    sents = re.split(r"(?<=[.!?])\s+", window_text)
    best = max(sents, key=lambda s: sum(1 for h in STRONG_HOOKS if re.search(h, s.lower())), default="")
    best = best or window_text
    best = re.sub(r"^(so|and|but|because|well),?\s+", "", best.strip(), flags=re.I)
    return (best[:57] + "...") if len(best) > 60 else best


def llm_config():
    for env, (base, model) in LLM_PROVIDERS.items():
        key = os.environ.get(env, "").strip()
        if key:
            base = os.environ.get("FREE_LLM_BASE_URL", base).rstrip("/")
            model = os.environ.get("FREE_LLM_MODEL", model)
            return {"key": key, "base": base, "model": model, "via": env}
    return None


def llm_rescore(candidates, cfg):
    """One cheap call: the LLM re-rates the top pre-scored candidates. Falls back to heuristic on any error."""
    listing = []
    for i, c in enumerate(candidates, 1):
        t = c["text"][:900]
        listing.append(f'{i}. [{c["start"]:.1f}s-{c["end"]:.1f}s] {t}')
    sys_prompt = ("You are a short-form video editor who finds the most viral moments in video transcripts. "
                  "Respond with JSON only, no prose.")
    user_prompt = (
        "Rate each candidate segment of a video transcript for viral clip potential on TikTok/YouTube Shorts/Reels.\n"
        "Scale: 9-10 = scroll-stopping hook, strong payoff, understandable standalone. 7-8.9 = good clip. "
        "Below 7 = filler or needs surrounding context. Be strict: most segments should NOT get 9+.\n"
        f"Return ONLY a JSON array covering ALL {len(candidates)} segments:\n"
        '[{"i": <segment number>, "score": <0-10 float>, "title": "<punchy <60-char title>", "reason": "<short>"}]\n\n'
        + "\n".join(listing)
    )
    body = json.dumps({
        "model": cfg["model"],
        "temperature": 0.2,
        "max_tokens": 4096,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }).encode()
    req = urllib.request.Request(
        cfg["base"] + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + cfg["key"]})
    try:
        print(f"-> Scoring {len(candidates)} candidates with free LLM ({cfg['model']} via {cfg['via']}) ...")
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        m = re.search(r"\[.*\]", content, re.S)
        arr = json.loads(m.group(0))
        got = {}
        for item in arr:
            if isinstance(item, dict) and isinstance(item.get("i"), int):
                got[item["i"]] = item
        hits = 0
        for i, c in enumerate(candidates, 1):
            item = got.get(i)
            if item and isinstance(item.get("score"), (int, float)):
                c["llm_score"] = float(min(10.0, max(0.0, item["score"])))
                c["title"] = str(item.get("title", ""))[:70] or c["title"]
                c["reason"] = str(item.get("reason", ""))[:160] or c["reason"]
                hits += 1
        if hits == 0:
            raise ValueError("no usable JSON in LLM reply")
        print(f"   LLM scored {hits}/{len(candidates)} candidates")
    except Exception as e:
        print(f"   ! LLM scoring failed ({e}); keeping heuristic scores.")


# ----------------------------------------------------------------------------- rendering

def fmt_time(s):
    s = max(0, int(round(s)))
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}" if s >= 3600 else f"{s//60:02d}:{s%60:02d}"


def srt_time(s):
    ms = int(round(max(0.0, s) * 1000))
    h, rem = divmod(ms, 3600000)
    mnt, rem = divmod(rem, 60000)
    sec, ms = divmod(rem, 1000)
    return f"{h:02d}:{mnt:02d}:{sec:02d},{ms:03d}"


def segment_srt(cues, start, end, path):
    """Write an SRT covering [start,end] with timestamps rebased to 0 for burning in."""
    idx = 1
    with open(path, "w", encoding="utf-8") as f:
        for cs, ce, txt in cues:
            if ce <= start or cs >= end or not txt:
                continue
            f.write(f"{idx}\n{srt_time(cs - start)} --> {srt_time(min(ce, end) - start)}\n{txt}\n\n")
            idx += 1


def render_clip(ffmpeg_path, video, start, end, out_path, vertical, size, sub_srt=None):
    vf = []
    if vertical and size and size[0] > size[1]:
        vf.append("crop=ih*9/16:ih")
        vf.append("scale=1080:1920")
    if sub_srt:
        vf.append(f"subtitles={sub_srt.name}")
    cmd = [ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y",
           "-ss", f"{start:.2f}", "-i", str(video), "-t", f"{max(0.5, end - start):.2f}"]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out_path)]
    r = subprocess.run(cmd, cwd=str(out_path.parent), capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-400:])


# ----------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Free viral YouTube clipper (no n8n, no Vizard, no paid APIs)")
    ap.add_argument("target", help="YouTube URL or local video file")
    ap.add_argument("--srt", help="transcript .srt/.vtt for local files")
    ap.add_argument("--max-clips", type=int, default=8, help="max clips to render (default 8)")
    ap.add_argument("--min-score", type=float, default=9.0, help="only keep clips scoring >= this (default 9; auto-relaxed to fill quota)")
    ap.add_argument("--min-len", type=float, default=20, help="min clip seconds (default 20)")
    ap.add_argument("--max-len", type=float, default=60, help="max clip seconds (default 60)")
    ap.add_argument("--vertical", action="store_true", help="crop to 9:16 vertical for Shorts/Reels/TikTok")
    ap.add_argument("--burn-subs", action="store_true", help="burn captions into the clips")
    ap.add_argument("--transcript-only", action="store_true", help="score and report, don't render clips")
    ap.add_argument("--cookies-from-browser", metavar="BROWSER",
                    help="pass browser cookies to yt-dlp (chrome/firefox/edge) if YouTube demands sign-in")
    ap.add_argument("--out", default="clips", help="output directory (default ./clips)")
    ap.add_argument("--keep-video", action="store_true", help="keep the downloaded full video afterwards")
    args = ap.parse_args()

    ffmpeg_path = find_ffmpeg()
    cfg = llm_config()

    title = Path(args.target).stem or "video"
    video_path, cues, duration, size = None, [], None, None

    if is_url(args.target):
        outdir = Path(args.out).resolve()
        outdir.mkdir(parents=True, exist_ok=True)
        video_path, sub_path, info = download_video(args.target, outdir, ffmpeg_path,
                                                    args.transcript_only, args.cookies_from_browser)
        title = info.get("title") or title
        duration = info.get("duration") or None
        if sub_path:
            cues = parse_vtt(sub_path)
    else:
        video_path = Path(args.target).resolve()
        if not video_path.is_file():
            sys.exit(f"ERROR: file not found: {video_path}")
        outdir = Path(args.out).resolve() / slugify(title, 60)
        outdir.mkdir(parents=True, exist_ok=True)
        if args.srt:
            cues = parse_vtt(args.srt)

    if not cues:
        print("! No transcript found — clips will be evenly spaced and unscored.")
        print("  (for local files pass --srt; for URLs the video needs captions)")
        if args.transcript_only:
            sys.exit("Nothing to score without a transcript.")

    if video_path and (duration is None or size is None):
        try:
            dur, sz = probe(ffmpeg_path, video_path)
            duration = duration or dur
            size = size or sz
        except Exception:
            pass

    print(f"\n== {title}")
    print(f"   duration: {fmt_time(duration or 0)}   transcript cues: {len(cues)}   mode: {'free-LLM' if cfg else 'no-key heuristic'}\n")

    # 1. candidates
    if cues:
        sents = cues_to_sentences(cues)
        candidates = build_windows(sents, args.min_len, args.max_len)
        if not candidates:
            sys.exit("ERROR: transcript too short to build clips from.")
        for c in candidates:
            c["score"], c["reasons"] = heuristic_score(c["text"], c["end"] - c["start"])
            c["title"] = ""
            c["reason"] = "; ".join(c["reasons"])
        candidates.sort(key=lambda c: c["score"], reverse=True)
        # 2. LLM re-scores only the top slice (cheap even on free tiers)
        to_score = candidates[:30]
        if cfg:
            llm_rescore(to_score, cfg)
        for c in to_score:
            c["final"] = c.get("llm_score", c["score"])
        for c in candidates:
            c.setdefault("final", c["score"])
            if not c["title"]:
                c["title"] = best_title(c["text"])
        candidates.sort(key=lambda c: c["final"], reverse=True)
        # drop candidates that mostly overlap an already-ranked better clip
        picked, dropped = [], []
        for c in candidates:
            clash = False
            for p in picked:
                inter = min(c["end"], p["end"]) - max(c["start"], p["start"])
                if inter > 8 and inter > 0.25 * min(c["end"] - c["start"], p["end"] - p["start"]):
                    clash = True
                    break
            (dropped if clash else picked).append(c)
        candidates = picked
    else:
        duration = (duration if video_path is None else (probe(ffmpeg_path, video_path)[0] or duration)) or 0
        n_win = min(args.max_clips * 2, max(1, int(duration // 45)))
        candidates = []
        for k in range(n_win):
            s = k * (duration - args.max_len) / max(1, n_win - 1) if n_win > 1 else 0
            candidates.append({"start": s, "end": s + min(args.max_len, duration),
                               "text": "", "score": None, "final": None,
                               "title": f"segment {k+1}", "reason": "no transcript available"})
        candidates = candidates[:args.max_clips]

    # 3. filter by score, auto-relax to fill the quota (like "up to 8 clips")
    chosen = [c for c in candidates if c["final"] is not None and c["final"] >= args.min_score]
    if len(chosen) < args.max_clips:
        floor = min(args.min_score, 7.0)
        extra = [c for c in candidates if c not in chosen and c["final"] is not None and c["final"] >= floor]
        chosen += extra[: args.max_clips - len(chosen)]
        if len(chosen) < args.max_clips:
            rest = [c for c in candidates if c not in chosen and c["final"] is not None]
            chosen += rest[: args.max_clips - len(chosen)]
            if rest:
                print(f"! Only found {len([c for c in candidates if c['final'] >= floor])} clips >= {floor}; "
                      f"filling with best remaining (scores shown honestly below).")
    chosen = chosen[: args.max_clips]
    if not chosen:
        sys.exit("ERROR: nothing to clip.")

    # 4. render + report
    mode = "free-LLM" if cfg else "heuristic (no API key)"
    report = [f"# Viral clips — {title}", "",
              f"- source: `{args.target}`",
              f"- duration: {fmt_time(duration or 0)}",
              f"- scoring: {mode}" + (f" ({cfg['model']})" if cfg else ""),
              f"- filters: min score {args.min_score}, max {args.max_clips} clips, "
              f"{args.min_len:.0f}-{args.max_len:.0f}s" + (", 9:16 vertical" if args.vertical else "")
              + (", burned captions" if args.burn_subs else ""), ""]

    print(f"{'#':>2}  {'score':>5}  {'time':>13}  title")
    for rank, c in enumerate(chosen, 1):
        score_s = f"{c['final']:.1f}" if c["final"] is not None else "  -"
        stamp = f"{fmt_time(c['start'])} - {fmt_time(c['end'])}"
        print(f"{rank:>2}  {score_s:>5}  {stamp:>13}  {c['title'][:60]}")
        report.append(f"## {rank}. {c['title']}")
        report.append(f"- score: {score_s} | {stamp} | length {c['end']-c['start']:.0f}s")
        report.append(f"- why: {c['reason']}")
        if c["text"]:
            report.append(f"- transcript: {c['text'][:400]}{'...' if len(c['text'])>400 else ''}")
        report.append("")

    clip_files = []
    if not args.transcript_only and video_path:
        print(f"\n-> Rendering {len(chosen)} clips with ffmpeg"
              + (" (vertical 9:16)" if args.vertical else "") + " ...")
        for rank, c in enumerate(chosen, 1):
            safe_title = slugify(c["title"] or f"clip-{rank}", 40)
            name = f"{rank:02d}_score{(c['final'] if c['final'] is not None else 0):.1f}_{safe_title}.mp4"
            out_path = outdir / name
            sub = None
            if args.burn_subs and cues:
                sub = outdir / f".tmp_{rank:02d}.srt"
                segment_srt(cues, c["start"], c["end"], sub)
            try:
                render_clip(ffmpeg_path, video_path, c["start"], c["end"], out_path,
                            args.vertical, size, sub)
                clip_files.append(out_path)
                print(f"   [{rank}/{len(chosen)}] {name}")
            except Exception as e:
                print(f"   [{rank}/{len(chosen)}] FAILED: {e}")
            finally:
                if sub and sub.exists():
                    sub.unlink()

        if clip_files:
            report.append("---")
            report.append("## Files")
            for f in clip_files:
                report.append(f"- `{f.name}`")
        # cleanup downloaded artifacts
        if is_url(args.target) and not args.keep_video:
            for f in outdir.glob("video.*"):
                if f.suffix not in (".md",):
                    f.unlink(missing_ok=True)
            for f in outdir.glob("video-*.vtt"):
                f.unlink(missing_ok=True)

    report_path = outdir / "report.md"
    report_path.write_text("\n".join(report), encoding="utf-8")
    print(f"\nDone. Report: {report_path}")
    if clip_files:
        print(f"Clips:   {clip_files[0].parent}")


if __name__ == "__main__":
    main()
