"""Produce the demo video: narration (Windows SAPI TTS) + scripted screen capture of the REAL app (Playwright) with zooms, spotlights,
a visible cursor, captions and title cards, muxed with ffmpeg.  Usage:  python scripts/make_video.py [--base http://localhost:8001]
Inputs: docs/video/storyboard.json (scenes: id, narration, headline, caption, emphasis).  Output: docs/video/blast-radius-demo.mp4"""
import json
import math
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "video"
WORK = ROOT / "data" / "video"
BASE = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else "http://localhost:8001"
W, H = 1600, 900
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
VOICE = "Microsoft Zira Desktop"

# ------------------------------------------------------------------ narration (SAPI)
def synth(scenes):
    WORK.mkdir(parents=True, exist_ok=True)
    for s in scenes:
        txt = WORK / f"{s['id']}.txt"
        wav = WORK / f"{s['id']}.wav"
        txt.write_text(s["narration"], encoding="utf-8")
        ps = (f"Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"$s.SelectVoice('{VOICE}'); $s.Rate = 2; $s.SetOutputToWaveFile('{wav}'); "
              f"$s.Speak([IO.File]::ReadAllText('{txt}', [Text.Encoding]::UTF8)); $s.Dispose()")
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], check=True, timeout=180)
        with wave.open(str(wav)) as w:
            s["audio"] = str(wav)
            s["dur"] = w.getnframes() / w.getframerate()
            s["rate"] = w.getframerate()
    return scenes


# ------------------------------------------------------------------ in-page effects (overlay lives OUTSIDE <body> so zooming the app never scales it)
OVERLAY_JS = r"""
(() => {
  if (window.__vx) return;
  const root = document.createElement('div'); root.id = 'vx';
  root.innerHTML = `
  <style>
    #vx{position:fixed;inset:0;pointer-events:none;z-index:2147483000;font-family:Inter,system-ui,sans-serif}
    html{overflow:hidden;background:#0A0D14}
    body{transform-origin:0 0;transition:transform 1.3s cubic-bezier(.65,.05,.25,1)}
    #vx .dim{position:absolute;border-radius:12px;box-shadow:0 0 0 9999px rgba(4,7,12,.72),0 0 0 3px #FFB000,0 0 30px 6px rgba(255,176,0,.45);opacity:0;transition:all .7s cubic-bezier(.65,.05,.25,1)}
    #vx .cur{position:absolute;left:0;top:0;width:26px;height:26px;transition:transform .09s linear;filter:drop-shadow(0 3px 5px rgba(0,0,0,.6))}
    #vx .rip{position:absolute;width:12px;height:12px;border-radius:50%;border:3px solid #FFB000;opacity:0}
    #vx .cap{position:absolute;left:46px;bottom:46px;max-width:760px;padding:16px 22px 16px 20px;border-left:5px solid #FF6B4A;background:linear-gradient(90deg,rgba(8,11,18,.94),rgba(8,11,18,.78));border-radius:0 14px 14px 0;color:#E8ECF4;opacity:0;transform:translateY(22px);transition:all .6s cubic-bezier(.2,.8,.2,1)}
    #vx .cap.on{opacity:1;transform:none}
    #vx .cap h2{margin:0 0 4px;font-size:30px;line-height:1.1;font-weight:700;letter-spacing:-.01em}
    #vx .cap p{margin:0;font-size:17px;color:#B7C0D3}
    #vx .chips{display:flex;gap:8px;margin-bottom:9px;flex-wrap:wrap}
    #vx .chips span{background:#FFB000;color:#1A1203;font:700 13px 'JetBrains Mono',monospace;padding:3px 10px;border-radius:99px;opacity:0;transform:scale(.7);animation:pop .5s forwards}
    @keyframes pop{to{opacity:1;transform:none}}
    #vx .card{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;background:radial-gradient(circle at 50% 40%,#17203a,#07090f 70%);color:#E8ECF4;opacity:0;transition:opacity .9s}
    #vx .card.on{opacity:1}
    #vx .card .big{font-size:64px;font-weight:800;letter-spacing:-.02em;line-height:1.08;max-width:1200px}
    #vx .card .big em{font-style:normal;color:#FF6B4A}
    #vx .card .sub{margin-top:22px;font-size:25px;color:#98A2B8;max-width:980px}
    #vx .card .tag{font:600 15px 'JetBrains Mono',monospace;letter-spacing:.18em;color:#FFB000;margin-bottom:26px}
    #vx .card .links{margin-top:34px;font:600 22px 'JetBrains Mono',monospace;color:#7CC4FF;line-height:1.7}
    #vx .bar{position:absolute;left:0;bottom:0;height:5px;background:linear-gradient(90deg,#FF6B4A,#FFB000);width:0;transition:width .3s linear}
    #vx .logo{position:absolute;right:30px;top:62px;font:700 15px Inter,sans-serif;color:#E8ECF4;opacity:.85;display:flex;align-items:center;gap:8px;background:rgba(8,11,18,.6);padding:6px 12px;border-radius:99px}
    #vx .logo i{width:10px;height:10px;border-radius:50%;background:#FF6B4A;box-shadow:0 0 12px #FF6B4A}
  </style>
  <div class="dim"></div><div class="cap"><div class="chips"></div><h2></h2><p></p></div>
  <div class="card"><div class="tag"></div><div class="big"></div><div class="sub"></div><div class="links"></div></div>
  <div class="bar"></div>
  <svg class="cur" viewBox="0 0 24 24"><path d="M3 2l17 8-7 2-3 7z" fill="#fff" stroke="#111" stroke-width="1.5" stroke-linejoin="round"/></svg>`;
  document.documentElement.appendChild(root);
  const $ = (s) => root.querySelector(s), cur = $('.cur'), dim = $('.dim');
  document.addEventListener('mousemove', (e) => { cur.style.transform = `translate(${e.clientX - 3}px,${e.clientY - 2}px)`; }, true);
  document.addEventListener('mousedown', (e) => { const r = document.createElement('div'); r.className = 'rip'; r.style.left = (e.clientX - 6) + 'px'; r.style.top = (e.clientY - 6) + 'px'; root.appendChild(r);
    r.animate([{opacity: .95, transform: 'scale(1)'}, {opacity: 0, transform: 'scale(4.5)'}], {duration: 650}).onfinish = () => r.remove(); }, true);
  const W = innerWidth, H = innerHeight;
  const q = (sel) => { const m = sel.match(/^(.*):has-text\("(.*)"\)$/); return m ? ([...document.querySelectorAll(m[1])].find((e) => e.textContent.includes(m[2])) || null) : document.querySelector(sel); };
  window.__vx = {
    caption(h, p, chips) { const c = $('.cap'); c.classList.remove('on'); setTimeout(() => { c.querySelector('h2').textContent = h || ''; c.querySelector('p').textContent = p || '';
        c.querySelector('.chips').innerHTML = (chips || []).map((x, i) => `<span style="animation-delay:${.35 + i * .25}s">${x.replace(/</g, '&lt;')}</span>`).join(''); c.classList.add('on'); }, 350); },
    hideCaption() { $('.cap').classList.remove('on'); },
    card(on, tag, big, sub, links) { const c = $('.card'); if (on) { c.querySelector('.tag').textContent = tag || ''; c.querySelector('.big').innerHTML = big || ''; c.querySelector('.sub').textContent = sub || ''; c.querySelector('.links').innerHTML = links || ''; } c.classList.toggle('on', !!on); },
    zoom(sel, s, dy) { const el = q(sel); if (!el) return false; const b = document.body, prev = b.style.transform; b.style.transition = 'none'; b.style.transform = 'none';
      const r = el.getBoundingClientRect(); b.style.transform = prev; void b.offsetWidth; b.style.transition = '';
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2 + (dy || 0); let tx = W / 2 - cx * s, ty = H / 2 - cy * s; tx = Math.min(0, Math.max(W - W * s, tx)); ty = Math.min(0, Math.max(H - H * s, ty));
      b.style.transform = `translate(${tx}px,${ty}px) scale(${s})`; return true; },
    unzoom() { document.body.style.transform = 'none'; },
    spot(sel, pad) { const el = q(sel); if (!el) { dim.style.opacity = 0; return false; } const r = el.getBoundingClientRect(); const p = pad ?? 10;
      Object.assign(dim.style, {left: (r.left - p) + 'px', top: (r.top - p) + 'px', width: (r.width + 2 * p) + 'px', height: (r.height + 2 * p) + 'px', opacity: 1}); return true; },
    unspot() { dim.style.opacity = 0; },
    progress(f) { $('.bar').style.width = (f * 100) + '%'; },
    center(sel) { const el = q(sel); if (!el) return null; el.scrollIntoView({block: 'center', behavior: 'instant'}); return true; },
    click(sel) { const el = q(sel); if (!el) return false; const r = el.getBoundingClientRect(); const rp = document.createElement('div'); rp.className = 'rip'; rp.style.left = (r.left + r.width / 2 - 6) + 'px'; rp.style.top = (r.top + r.height / 2 - 6) + 'px'; root.appendChild(rp);
      rp.animate([{opacity: .95, transform: 'scale(1)'}, {opacity: 0, transform: 'scale(4.5)'}], {duration: 650}).onfinish = () => rp.remove(); el.click(); return true; },
    rect(sel) { const el = q(sel); if (!el) return null; const r = el.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height}; },
  };
})();
"""


class Rec:
    def __init__(self, page, t_base, total):
        self.p, self.t0, self.total = page, t_base, total

    def now(self):
        return time.time() - self.t0

    def until(self, t):
        d = t - self.now()
        if d > 0:
            time.sleep(d)
        self.p.evaluate(f"window.__vx.progress({min(1, self.now() / self.total):.4f})")

    def js(self, code):
        return self.p.evaluate(code)

    def move(self, sel, steps=28, dx=0, dy=0):
        r = self.js(f"window.__vx.rect({json.dumps(sel)})")
        if not r:
            return None
        self.p.mouse.move(r["x"] + dx, r["y"] + dy, steps=steps)
        return r

    def click(self, sel, **kw):
        r = self.move(sel, **kw)
        time.sleep(0.3)
        self.js(f"window.__vx.click({json.dumps(sel)})")
        return r

    def unzoom(self):
        self.js("window.__vx.unzoom()")
        time.sleep(1.4)

    def zoom(self, sel, s=1.8, dy=0):
        ok = self.js(f"window.__vx.zoom({json.dumps(sel)}, {s}, {dy})")
        time.sleep(1.4)                      # let the camera move finish so spotlights measure the final position
        return ok

    def spot(self, sel, pad=10):
        return self.js(f"window.__vx.spot({json.dumps(sel)}, {pad})")

    def center(self, sel):
        self.js(f"window.__vx.center({json.dumps(sel)})")
        time.sleep(0.5)

    def cap(self, s):
        self.js(f"window.__vx.caption({json.dumps(s['headline'])}, {json.dumps(s['caption'])}, {json.dumps(s.get('emphasis', []))})")


# ------------------------------------------------------------------ scenes (what happens on screen). Each ends when its narration ends.
def run_scenes(page, scenes, t_base, total):
    R = Rec(page, t_base, total)
    starts = {}
    t = 1.2                                      # lead-in
    schedule = []
    for s in scenes:
        schedule.append((s, t, t + s["dur"] + 0.7))
        t += s["dur"] + 0.7
    R.until(0.9)
    for s, ts, te in schedule:
        starts[s["id"]] = ts
        R.until(ts)
        sid = s["id"]
        R.cap(s)
        L = lambda f: ts + (te - ts) * f            # a point inside the scene
        if sid == "hook":
            R.js("window.__vx.card(true,'GRAPH HACKS · TRACK 01','25 vulnerabilities.<br><em>How many can an attacker reach?</em>','Blast Radius: Reachability-to-Repair','')")
            R.js("window.__vx.hideCaption()")
            R.until(te - 0.9)
            R.js("window.__vx.card(false)")
        elif sid == "triage":
            R.until(L(.08))
            R.click(".chip >> nth=0".replace(" >> nth=0", ":nth-of-type(1)"))
            try:
                page.wait_for_selector("button.adv", timeout=60000)
            except Exception:
                pass
            R.until(L(.55))
            R.zoom(".tri", 2.1, dy=40); R.spot(".tri", 12)
            R.until(L(.9)); R.js("window.__vx.unspot()")
        elif sid == "path":
            R.unzoom(); R.until(L(.08))
            R.center('button.adv:has-text("CVE-2023-32681")')
            R.click('button.adv:has-text("CVE-2023-32681")')
            R.until(L(.35))
            R.zoom("#graph", 1.55, dy=0)
            R.until(L(.75)); R.unzoom()
            R.spot('button.adv:has-text("CVE-2023-32681")', 8)
            R.until(L(.97)); R.js("window.__vx.unspot()")
        elif sid == "cypher":
            R.unzoom(); R.until(L(.05))
            R.click("button[data-tab=hood]")
            R.until(L(.25))
            R.zoom("#tab-hood", 1.7, dy=-120)
            R.until(L(.62))
            R.zoom("#totals", 2.4)
            R.spot("#totals", 14)
            R.until(L(.95)); R.js("window.__vx.unspot()"); R.unzoom()
        elif sid == "plan":
            R.click("button[data-tab=answer]")
            R.until(L(.12))
            R.center('.act:has-text("Pin requests")'); R.spot('.act:has-text("Pin requests")', 8)
            R.until(L(.42)); R.js("window.__vx.unspot()")
            R.center('.act:has-text("Do NOT pin urllib3")'); R.spot('.act:has-text("Do NOT pin urllib3")', 8)
            R.until(L(.75)); R.js("window.__vx.unspot()")
            R.center('h4.sec:has-text("Verification")'); R.zoom('h4.sec:has-text("Verification")', 1.5, dy=140)
            R.until(L(.96)); R.unzoom()
        elif sid == "fixloop":
            R.unzoom(); R.until(L(.05))
            R.center('.act:has-text("Proposed fix for the blocked urllib3")'); R.spot('.act:has-text("Proposed fix for the blocked urllib3")', 8)
            R.until(L(.38)); R.js("window.__vx.unspot()")
            R.center('.claim:has-text("Verified fix path")'); R.spot('.claim:has-text("Verified fix path")', 8)
            R.until(L(.7)); R.js("window.__vx.unspot()")
            R.center('.claim:has-text("Plan outcome")'); R.spot('.claim:has-text("Plan outcome")', 8)
            R.until(L(.96)); R.js("window.__vx.unspot()")
        elif sid == "twist":
            R.unzoom(); R.until(L(.04))
            R.click(".chip:nth-of-type(2)")
            try:
                page.wait_for_selector('.claim:has-text("NO PATH FOUND")', timeout=40000)
            except Exception:
                pass
            R.until(L(.3))
            R.center('.claim:has-text("NO PATH FOUND")'); R.spot('.claim:has-text("NO PATH FOUND")', 8)
            R.until(L(.5)); R.js("window.__vx.unspot()")
            try:
                page.wait_for_selector('.claim:has-text("REACHABLE")', timeout=40000)
            except Exception:
                pass
            R.until(L(.72))
            R.center('.claim:has-text("REACHABLE")'); R.spot('.claim:has-text("REACHABLE")', 8)
            R.until(L(.85)); R.js("window.__vx.unspot()")
            R.center('.claim:has-text("Memory")'); R.spot('.claim:has-text("Memory")', 8)
            R.until(L(.97)); R.js("window.__vx.unspot()")
        elif sid == "why":
            R.unzoom(); R.until(L(.05))
            R.click("#btnPortfolio")
            R.until(L(.3))
            R.zoom("#modalP .mbox", 1.35)
            R.spot("#portfolioBody .pf.differs", 8)
            R.until(L(.62)); R.js("window.__vx.unspot()")
            R.click("#pClose"); R.unzoom()
            R.until(L(.7))
            R.click("#btnSchema")
            R.until(L(.95))
            R.click("#mClose")
        elif sid == "close":
            R.unzoom(); R.js("window.__vx.hideCaption()")
            R.js("window.__vx.card(true,'TRY IT','Blast Radius','Reachability-to-Repair: from alert, to evidence, to a fix that actually runs.','blast-radius-yeki.onrender.com<br>github.com/KrishnaAgarwal2206/blast-radius-falkordb')")
            R.until(te + 1.2)
    R.js("window.__vx.progress(1)")
    return starts


# ------------------------------------------------------------------ audio bed
def build_audio(scenes, starts, total, out):
    rate = scenes[0]["rate"]
    n = int((total + 1) * rate)
    buf = [0] * n
    for s in scenes:
        with wave.open(s["audio"]) as w:
            raw = w.readframes(w.getnframes())
            ch = w.getnchannels()
        samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
        if ch == 2:
            samples = samples[::2]
        off = int(starts[s["id"]] * rate)
        for i, v in enumerate(samples):
            if off + i < n:
                buf[off + i] = int(v * 0.95)
    # soft ambient pad (A minor add9 drifting), mixed far below the voice
    for i in range(n):
        t = i / rate
        pad = 0.0
        for f, a in ((110, .5), (164.8, .35), (220, .3), (329.6, .18)):
            pad += a * math.sin(2 * math.pi * f * t + 0.6 * math.sin(2 * math.pi * 0.07 * t))
        fade = min(1, t / 3, max(0, (total + 1 - t) / 3))
        buf[i] = max(-32000, min(32000, buf[i] + int(pad * 520 * fade)))
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(struct.pack("<" + "h" * n, *buf))


def main():
    sb = json.loads((OUT / "storyboard.json").read_text(encoding="utf-8"))["scenes"]
    scenes = synth(sb)
    total = 1.2 + sum(s["dur"] + 0.7 for s in scenes) + 1.4
    print("narration", round(sum(s["dur"] for s in scenes), 1), "s; video length ~", round(total, 1), "s")
    vdir = WORK / "rec"
    for f in vdir.glob("*.webm") if vdir.exists() else []:
        f.unlink()
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--force-device-scale-factor=1"])
        t_base = time.time()
        ctx = b.new_context(viewport={"width": W, "height": H}, record_video_dir=str(vdir), record_video_size={"width": W, "height": H})
        page = ctx.new_page()
        page.goto(BASE, wait_until="load")
        page.wait_for_selector("#heroGo")
        page.evaluate(OVERLAY_JS)
        page.mouse.move(W / 2, H / 2)
        time.sleep(0.8)
        starts = run_scenes(page, scenes, t_base, total)
        time.sleep(0.6)
        ctx.close()
        b.close()
    webm = sorted(vdir.glob("*.webm"))[-1]
    wav = WORK / "bed.wav"
    build_audio(scenes, starts, total, wav)
    out = OUT / "blast-radius-demo.mp4"
    subprocess.run([FFMPEG, "-y", "-i", str(webm), "-i", str(wav), "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-r", "30",
                    "-c:a", "aac", "-b:a", "160k", "-vf", f"fade=t=in:st=0:d=0.6,fade=t=out:st={total - 1.0:.2f}:d=1.0", "-af", f"afade=t=out:st={total - 1.2:.2f}:d=1.2", "-shortest", str(out)], check=True, capture_output=True)
    srt = []
    for i, s in enumerate(scenes, 1):
        a, b2 = starts[s["id"]], starts[s["id"]] + s["dur"]
        fmt = lambda x: f"{int(x // 3600):02}:{int(x % 3600 // 60):02}:{int(x % 60):02},{int(x % 1 * 1000):03}"
        srt.append(f"{i}\n{fmt(a)} --> {fmt(b2)}\n{s['narration']}\n")
    (OUT / "blast-radius-demo.srt").write_text("\n".join(srt), encoding="utf-8")
    print("wrote", out, round(out.stat().st_size / 1e6, 1), "MB")


if __name__ == "__main__":
    main()
