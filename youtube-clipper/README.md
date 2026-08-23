# Free viral YouTube clipper — no n8n, no Vizard, no paid APIs

A standalone, 100%-free replacement for the `viral_youtube_video_clipper.json` workflow from
[lucaswalter/n8n-ai-automations](https://github.com/lucaswalter/n8n-ai-automations).

Point it at any YouTube video (or a local video file) and it will:

1. **Download the video + captions** with [yt-dlp](https://github.com/yt-dlp/yt-dlp) (free, open source)
2. **Find the most viral moments** — using a free LLM (Groq / Gemini / OpenRouter free tiers) if you
   set an API key, or a built-in **heuristic scorer that needs no key at all**
3. **Cut up to 8 clips** with ffmpeg, optionally cropped to vertical 9:16 with burned-in captions
   (ready for Shorts / Reels / TikTok)
4. Write a **report.md** with every clip's score, timestamps, title and reasoning
   (replaces the original workflow's Slack messages)

| Original n8n workflow | This tool | Cost |
|---|---|---|
| Vizard AI API (clipping + virality score) | yt-dlp + ffmpeg + LLM/heuristic scoring | **$0** |
| n8n (cloud or self-hosted) | one Python file | **$0** |
| Slack for reviewing clips | `report.md` + clip files on disk | **$0** |

---

## Setup (2 minutes)

Requires Python 3.8+.

```bash
pip install yt-dlp
```

**ffmpeg** — pick one:

- **Linux:** `sudo apt install ffmpeg`
- **macOS:** `brew install ffmpeg`
- **Windows:** `winget install ffmpeg` (or download a build from https://ffmpeg.org, then set `FFMPEG_PATH` to its location)
- **No admin?** `pip install imageio-ffmpeg` — the script finds and uses that copy automatically.

## Optional (recommended): free LLM scoring

The heuristic scorer works with zero signups, but a free LLM rates clips much better.
Get **one** free API key and export it:

| Provider | Get a free key at | Export |
|---|---|---|
| Groq (default) | https://console.groq.com | `export FREE_LLM_API_KEY="gsk_..."` |
| Google Gemini | https://aistudio.google.com | `export GEMINI_API_KEY="..."` |
| OpenRouter | https://openrouter.ai | `export OPENROUTER_API_KEY="sk-or-..."` |

All have free tiers. One LLM call per video re-scores the top ~30 candidate moments —
usually well within free limits. No key? It just runs in heuristic mode.

## Usage

```bash
# the classic run: up to 8 clips scoring 9+ (auto-relaxes the bar if fewer qualify)
python3 yt_clipper.py "https://www.youtube.com/watch?v=VIDEO_ID"

# vertical clips with burned-in captions for Shorts/Reels/TikTok
python3 yt_clipper.py "https://youtu.be/VIDEO_ID" --vertical --burn-subs

# just see the scores first, render nothing
python3 yt_clipper.py "https://youtu.be/VIDEO_ID" --transcript-only

# clip a video you already have (any format), with its own captions file
python3 yt_clipper.py podcast.mp4 --srt captions.srt --max-clips 5

# YouTube asks you to sign in (happens on cloud servers / VPNs)? pass browser cookies:
python3 yt_clipper.py "https://youtu.be/VIDEO_ID" --cookies-from-browser chrome
```

Output lands in `./clips/<video-name>/`: numbered mp4 files
(`01_score9.4_heres-the-secret-...mp4`) plus `report.md`.

### Options

```
--max-clips N       max clips to render (default 8, like the original workflow)
--min-score X       only keep clips scoring >= X (default 9; auto-relaxed to fill quota)
--min-len / --max-len   clip length range in seconds (default 20–60)
--vertical          crop to 9:16 (1080x1920)
--burn-subs         burn captions into the clips
--transcript-only   score + report only, no rendering
--srt FILE          transcript for local video files (.srt or .vtt)
--cookies-from-browser B   chrome/firefox/edge cookies for yt-dlp
--out DIR           output directory (default ./clips)
--keep-video        keep the downloaded full video
```

## Troubleshooting

- **"yt-dlp could not download..."** — update yt-dlp (`pip install -U yt-dlp`); if YouTube wants
  sign-in, use `--cookies-from-browser`. You can always download the video separately and run on
  the local file with `--srt`.
- **"No transcript found"** — the video has no English captions. The tool falls back to evenly
  spaced clips (unscored), or supply your own `.srt`.
- **Windows + `--burn-subs`** — ffmpeg must be built with libass (official builds are).

## Legal note

Download and clip only videos you own or have permission to use — this tool is meant for
repurposing your own content, same as the original workflow.
