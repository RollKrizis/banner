import asyncio, json, os, random, shlex
from dataclasses import dataclass

FFMPEG = os.getenv("FFMPEG", "ffmpeg")
FFPROBE = os.getenv("FFPROBE", "ffprobe")
SR = 44100


@dataclass
class Settings:
    banner: str = os.getenv("BANNER_PATH", "banners/default.mp4")
    mode: str = os.getenv("MODE", "auto")
    freeze_below: float = 10.0
    target_w: int = 1080
    target_h: int = 1920
    fit: str = os.getenv("FIT", "auto")
    key_color: str = os.getenv("KEY_COLOR", "0x00FF00")
    similarity: float = 0.30
    blend: float = 0.12
    scale: float = 0.92
    y_pos: float = 0.5
    cut_frames: int = 3
    jitter: bool = True
    duck: float = 0.18
    banner_vol: float = 1.4
    fade: float = 0.25
    blur: float = 0.0
    crf: int = 20
    preset: str = os.getenv("PRESET", "veryfast")

async def _run(cmd: list[str]) -> str:
    p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                             stderr=asyncio.subprocess.STDOUT)
    out, _ = await p.communicate()
    if p.returncode != 0:
        raise RuntimeError(f"{shlex.join(cmd[:1])} failed:\n{out.decode()[-1500:]}")
    return out.decode()


async def probe(path: str) -> dict:
    raw = await _run([FFPROBE, "-v", "error", "-print_format", "json",
                      "-show_format", "-show_streams", path])
    d = json.loads(raw)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    num, den = (v.get("avg_frame_rate") or "30/1").split("/")
    fps = (float(num) / float(den)) if float(den or 0) else 30.0
    w, h = int(v["width"]), int(v["height"])
    if str(v.get("rotation") or "") in ("90", "-90", "270", "-270"):
        w, h = h, w
    return {"w": w, "h": h, "fps": round(fps, 4) or 30.0,
            "dur": float(d["format"].get("duration") or v.get("duration") or 0),
            "audio": any(s["codec_type"] == "audio" for s in d["streams"])}


def normalize(src: dict, s: Settings) -> tuple[list[str], int, int, str]:
    """[pre] -> [base]. Upscales anything smaller than the target frame."""
    w, h, tw, th = src["w"], src["h"], s.target_w, s.target_h
    if w >= tw and h >= th:
        return ["[pre]setsar=1[base]"], w, h, "none"

    fit = s.fit
    if fit == "auto":
        fit = "cover" if abs((w / h) - (tw / th)) / (tw / th) <= 0.15 else "blur"

    if fit == "cover":
        f = [f"[pre]scale={tw}:{th}:force_original_aspect_ratio=increase:flags=lanczos,"
             f"crop={tw}:{th},setsar=1,format=yuv420p[base]"]
    elif fit == "contain":
        f = [f"[pre]scale={tw}:{th}:force_original_aspect_ratio=decrease:flags=lanczos,"
             f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,format=yuv420p[base]"]
    else:  # blur: upscaled blurred fill behind the letterboxed frame
        f = ["[pre]split=2[bg][fg]",
             f"[bg]scale={tw}:{th}:force_original_aspect_ratio=increase:flags=fast_bilinear,"
             f"crop={tw}:{th},gblur=sigma=28[bgb]",
             f"[fg]scale={tw}:{th}:force_original_aspect_ratio=decrease:flags=lanczos[fgs]",
             "[bgb][fgs]overlay=x=(W-w)/2:y=(H-h)/2:format=auto,"
             "setsar=1,format=yuv420p[base]"]
    return f, tw, th, fit


def _keyed_banner(s: Settings, w: int) -> str:
    bw = int(w * s.scale) // 2 * 2
    return (f"[1:v]scale={bw}:-2:flags=lanczos,format=rgba,"
            f"colorkey={s.key_color}:{s.similarity}:{s.blend},"
            f"despill=type=green:mix=0.5:expand=0.2")


def build(src: dict, ban: dict, s: Settings) -> tuple[str, str, str, dict]:
    fps = src["fps"]
    cut = s.cut_frames / fps
    dur = max(src["dur"] - cut, 0.1)
    mode = s.mode if s.mode in ("freeze", "duck") else (
        "freeze" if dur < s.freeze_below else "duck")
    bdur = ban["dur"]
    mid = round(max(dur / 2, 0) * fps) / fps
    y = f"(H-h)*{s.y_pos:.3f}"
    f: list[str] = []

    pre = f"[0:v]trim=start_frame={s.cut_frames},setpts=PTS-STARTPTS"
    if s.jitter:
        j = random.randint(1, 2)
        pre += f",crop=iw-{2*j}:ih-{2*j}:{j}:{j},scale={src['w']}:{src['h']}"
    f.append(pre + f",fps={fps},format=yuv420p,setsar=1[pre]")

    norm, w, h, fit = normalize(src, s)
    f += norm

    src_a = ("[0:a]aresample=async=1" if src["audio"]
             else f'anullsrc=r={SR}:cl=stereo,atrim=end={src["dur"]:.4f}')
    ban_a = ("[1:a]aresample=async=1" if ban["audio"]
             else f'anullsrc=r={SR}:cl=stereo,atrim=end={ban["dur"]:.4f}')
    AF = f"aformat=sample_fmts=fltp:sample_rates={SR}:channel_layouts=stereo"

    if mode == "freeze":
        nf = max(int(round(bdur * fps)), 1)
        fdur = nf / fps
        f.append("[base]split=3[p1][fz][p3]")
        f.append(f"[p1]trim=end={mid:.4f},setpts=PTS-STARTPTS[a1]")
        f.append(f"[p3]trim=start={mid:.4f},setpts=PTS-STARTPTS[a3]")
        frz = (f"[fz]trim=start={mid:.4f},select='eq(n\\,0)',"
               f"loop=loop={nf-1}:size=1:start=0,setpts=N/{fps}/TB,fps={fps}")
        if s.blur > 0:
            frz += f",gblur=sigma={s.blur}"
        f.append(frz + ",format=yuv420p,setsar=1[frozen]")
        f.append(_keyed_banner(s, w) + "[ban]")
        f.append(f"[frozen][ban]overlay=x=(W-w)/2:y={y}:eof_action=pass:"
                 "shortest=0:format=auto,format=yuv420p,setsar=1[frozenb]")
        f.append("[a1][frozenb][a3]concat=n=3:v=1:a=0[v]")

        f.append(f"{src_a},asetpts=PTS-STARTPTS,atrim=start={cut:.4f},"
                 f"asetpts=N/{SR}/TB,{AF},asplit=2[sa][sb]")
        f.append(f"[sa]atrim=end={mid:.4f},asetpts=N/{SR}/TB,apad=whole_dur={mid:.4f}[aa1]")
        f.append(f"[sb]atrim=start={mid:.4f},asetpts=N/{SR}/TB[aa3]")
        f.append(f"{ban_a},asetpts=N/{SR}/TB,{AF},volume={s.banner_vol},"
                 f"apad=whole_dur={fdur:.4f},atrim=end={fdur:.4f},asetpts=N/{SR}/TB[bana]")
        f.append(f"[aa1][bana][aa3]concat=n=3:v=0:a=1,{AF}[a]")
        info = {"mode": "freeze", "at": mid, "hold": fdur}
    else:
        start = max((dur - bdur) / 2, 0)
        end = start + bdur
        fd = min(s.fade, bdur / 4)
        f.append(_keyed_banner(s, w) + f",setpts=PTS-STARTPTS+{start:.4f}/TB[ban]")
        f.append(f"[base][ban]overlay=x=(W-w)/2:y={y}:eof_action=pass:"
                 "shortest=0:format=auto[v]")
        duck = (f"volume=enable='between(t,{start:.4f},{end:.4f})':volume={s.duck}"
                if fd <= 0 else
                f"volume=volume='if(between(t,{start:.4f},{end:.4f}),"
                f"{s.duck}+(1-{s.duck})*(max(0,1-(t-{start:.4f})/{fd:.4f})"
                f"+max(0,1-({end:.4f}-t)/{fd:.4f})),1)':eval=frame")
        f.append(f"{src_a},asetpts=PTS-STARTPTS,atrim=start={cut:.4f},"
                 f"asetpts=N/{SR}/TB,{AF},{duck}[duckd]")
        f.append(f"{ban_a},asetpts=N/{SR}/TB,{AF},volume={s.banner_vol},"
                 f"adelay={int(start*1000)}|{int(start*1000)}[bana]")
        f.append("[duckd][bana]amix=inputs=2:duration=first:dropout_transition=0:"
                 f"normalize=0,alimiter=limit=0.97,{AF}[a]")
        info = {"mode": "duck", "at": start, "hold": 0.0}

    info.update(cut_sec=cut, fit=fit, out_w=w, out_h=h,
                out_dur=dur + info["hold"])
    return ";".join(f), "[v]", "[a]", info




async def compress_video(src_path: str, dst_path: str, max_size_mb: int = 20, s: Settings = Settings()) -> bool:
    """Сжимает видео, если оно больше max_size_mb. Возвращает True если сжимал."""
    import os
    file_size_mb = os.path.getsize(src_path) / (1024 * 1024)
    if file_size_mb <= max_size_mb:
        return False
    
    src = await probe(src_path)
    crf = max(20, min(28, int(20 + (file_size_mb - max_size_mb) / 5)))
    
    cmd = [FFMPEG, "-y", "-i", src_path,
           "-c:v", "libx264", "-crf", str(crf), "-preset", "ultrafast",
           "-c:a", "aac", "-b:a", "128k",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", dst_path]
    await _run(cmd)
    return True


async def process(src_path: str, out_path: str, s: Settings = Settings()) -> dict:
    src, ban = await probe(src_path), await probe(s.banner)
    chain, vlab, alab, info = build(src, ban, s)
    cmd = [FFMPEG, "-y", "-i", src_path, "-i", s.banner,
           "-filter_complex", chain, "-map", vlab, "-map", alab,
           "-c:v", "libx264", "-preset", s.preset, "-crf", str(s.crf),
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
           "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-ac", "2",
           "-movflags", "+faststart", "-map_metadata", "-1", "-map_chapters", "-1",
           "-fflags", "+bitexact", out_path]
    await _run(cmd)
    info["src"], info["banner"] = src, ban
    return info
