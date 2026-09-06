import asyncio, json, logging, os, tempfile, time
from dataclasses import asdict, replace
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import FSInputFile, Message

import video
from video import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("banner-bot")

TOKEN = os.environ["BOT_TOKEN"]
WORK = Path(os.getenv("WORK_DIR", "./work")); WORK.mkdir(parents=True, exist_ok=True)
BANNERS = Path(os.getenv("BANNER_DIR", "./banners")); BANNERS.mkdir(parents=True, exist_ok=True)
STATE = Path(os.getenv("STATE_FILE", "./state.json"))
LIMIT = asyncio.Semaphore(int(os.getenv("CONCURRENCY", 2)))
ALLOWED = {int(x) for x in os.getenv("ALLOWED_USERS", "").replace(" ", "").split(",") if x}

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ---------------------------------------------------------------- per-user state
_state: dict[str, dict] = json.loads(STATE.read_text()) if STATE.exists() else {}


def cfg(uid: int) -> Settings:
    return Settings(**{**asdict(Settings()), **_state.get(str(uid), {})})


def save(uid: int, **kw) -> Settings:
    _state.setdefault(str(uid), {}).update(kw)
    STATE.write_text(json.dumps(_state, indent=1))
    return cfg(uid)


def guard(m: Message) -> bool:
    return not ALLOWED or m.from_user.id in ALLOWED


HELP = (
    "Кидай видео - верну его с баннером по центру и без первых кадров.\n"
    "Короткие ролики (&lt;10с) ставятся на стоп-кадр, длинные идут без паузы, но со звуком вниз.\n\n"
    "<b>Настройки</b>\n"
    "/mode auto|freeze|duck - auto: короче 10с → стоп-кадр, длиннее → без остановки с приглушением\n"
    "/limit 10 - порог в секундах для auto\n"
    "/duck 0.18 - громкость оригинала под баннером\n"
    "/vol 1.4 - громкость голоса с баннера\n"
    "/blur 0 - размытие стоп-кадра (напр. 8)\n"
    "/size 1080x1920 - целевой кадр, меньшее видео апскейлится\n"
    "/fit auto|cover|contain|blur - как вписывать кадр при апскейле\n"
    "/cut 3 - сколько кадров срезать с начала\n"
    "/scale 0.92 - ширина баннера от ширины видео\n"
    "/pos 0.5 - вертикаль баннера (0 верх, 1 низ)\n"
    "/key 0x00FF00 0.30 0.12 - цвет хромакея, similarity, blend\n"
    "/jitter on|off - микро-кроп для уникального хеша\n"
    "/banner - ответь этой командой на видео, чтобы сменить баннер\n"
    "/settings - текущие значения"
)


@dp.message(Command("start", "help"))
async def start(m: Message):
    await m.answer(HELP)


@dp.message(Command("settings"))
async def show(m: Message):
    s = cfg(m.from_user.id)
    await m.answer(
        f"<code>cut_frames  {s.cut_frames}\n"
        f"banner_scale {s.scale}\n"
        f"banner_y     {s.y_pos}\n"
        f"mode         {s.mode} (порог {s.freeze_below:g}с)\n"
        f"target       {s.target_w}x{s.target_h}, fit {s.fit}\n"
        f"duck/vol     {s.duck} / {s.banner_vol}\n"
        f"freeze_blur  {s.blur:g}\n"
        f"key          {s.key_color} {s.similarity} {s.blend}\n"
        f"jitter       {'on' if s.jitter else 'off'}\n"
        f"banner       {Path(s.banner).name}</code>"
    )


@dp.message(Command("cut"))
async def set_cut(m: Message, command: CommandObject):
    try:
        n = max(0, min(int(command.args), 30))
    except (TypeError, ValueError):
        return await m.answer("Формат: /cut 3")
    save(m.from_user.id, cut_frames=n)
    await m.answer(f"Срезаю {n} кадр(ов) с начала.")


@dp.message(Command("scale"))
async def set_scale(m: Message, command: CommandObject):
    try:
        v = max(0.2, min(float(command.args.replace(",", ".")), 1.0))
    except (TypeError, ValueError, AttributeError):
        return await m.answer("Формат: /scale 0.92")
    save(m.from_user.id, scale=v)
    await m.answer(f"Ширина баннера: {v:g} от кадра.")


@dp.message(Command("pos"))
async def set_pos(m: Message, command: CommandObject):
    try:
        v = max(0.0, min(float(command.args.replace(",", ".")), 1.0))
    except (TypeError, ValueError, AttributeError):
        return await m.answer("Формат: /pos 0.5")
    save(m.from_user.id, y_pos=v)
    await m.answer(f"Вертикальная позиция: {v:g}.")


@dp.message(Command("key"))
async def set_key(m: Message, command: CommandObject):
    parts = (command.args or "").split()
    if not parts:
        return await m.answer("Формат: /key 0x00FF00 0.30 0.12")
    kw = {"key_color": parts[0]}
    try:
        if len(parts) > 1: kw["similarity"] = float(parts[1])
        if len(parts) > 2: kw["blend"] = float(parts[2])
    except ValueError:
        return await m.answer("similarity и blend - числа, напр. 0.30 0.12")
    save(m.from_user.id, **kw)
    await m.answer("Ок, обновил хромакей.")


@dp.message(Command("jitter"))
async def set_jitter(m: Message, command: CommandObject):
    on = (command.args or "").strip().lower() in {"on", "1", "да", "yes"}
    save(m.from_user.id, jitter=on)
    await m.answer(f"Микро-кроп {'включён' if on else 'выключен'}.")


@dp.message(Command("mode"))
async def set_mode(m: Message, command: CommandObject):
    v = (command.args or "").strip().lower()
    if v not in {"auto", "freeze", "duck"}:
        return await m.answer("Формат: /mode auto | freeze | duck")
    save(m.from_user.id, mode=v)
    names = {"auto": "авто по длине ролика", "freeze": "всегда стоп-кадр",
             "duck": "без паузы, звук вниз"}
    await m.answer(f"Режим: {names[v]}.")


def _num(command: CommandObject, lo: float, hi: float):
    return max(lo, min(float((command.args or "").replace(",", ".")), hi))


@dp.message(Command("limit"))
async def set_limit(m: Message, command: CommandObject):
    try:
        v = _num(command, 0, 600)
    except ValueError:
        return await m.answer("Формат: /limit 10")
    save(m.from_user.id, freeze_below=v)
    await m.answer(f"Стоп-кадр для роликов короче {v:g}с.")


@dp.message(Command("duck"))
async def set_duck(m: Message, command: CommandObject):
    try:
        v = _num(command, 0, 1)
    except ValueError:
        return await m.answer("Формат: /duck 0.18")
    save(m.from_user.id, duck=v)
    await m.answer(f"Оригинал под баннером: {v:g} от громкости.")


@dp.message(Command("vol"))
async def set_vol(m: Message, command: CommandObject):
    try:
        v = _num(command, 0, 4)
    except ValueError:
        return await m.answer("Формат: /vol 1.4")
    save(m.from_user.id, banner_vol=v)
    await m.answer(f"Громкость баннера: {v:g}.")


@dp.message(Command("blur"))
async def set_blur(m: Message, command: CommandObject):
    try:
        v = _num(command, 0, 40)
    except ValueError:
        return await m.answer("Формат: /blur 8 (0 = выкл)")
    save(m.from_user.id, blur=v)
    await m.answer(f"Размытие стоп-кадра: {v:g}.")


@dp.message(Command("size"))
async def set_size(m: Message, command: CommandObject):
    raw = (command.args or "").lower().replace("х", "x").replace("*", "x").replace(" ", "")
    try:
        w, h = (int(v) for v in raw.split("x"))
        assert 240 <= w <= 4096 and 240 <= h <= 4096
    except (ValueError, AssertionError):
        return await m.answer("Формат: /size 1080x1920")
    save(m.from_user.id, target_w=w // 2 * 2, target_h=h // 2 * 2)
    await m.answer(f"Целевой кадр: {w}x{h}. Всё, что меньше, будет апскейлиться.")


@dp.message(Command("fit"))
async def set_fit(m: Message, command: CommandObject):
    v = (command.args or "").strip().lower()
    if v not in {"auto", "cover", "contain", "blur"}:
        return await m.answer("Формат: /fit auto | cover | contain | blur")
    save(m.from_user.id, fit=v)
    names = {"auto": "авто (вертикаль - cover, иначе blur)",
             "cover": "заполнить с обрезкой",
             "contain": "вписать, чёрные поля",
             "blur": "вписать, размытый фон"}
    await m.answer(f"Апскейл: {names[v]}.")


def file_of(m: Message):
    if m.video: return m.video
    if m.animation: return m.animation
    if m.video_note: return m.video_note
    if m.document and (m.document.mime_type or "").startswith("video/"): return m.document
    return None


@dp.message(Command("banner"))
async def set_banner(m: Message):
    src = m.reply_to_message and file_of(m.reply_to_message)
    if not src:
        return await m.answer("Ответь /banner на сообщение с новым баннером (видео с хромакеем).")
    dst = BANNERS / f"{m.from_user.id}.mp4"
    await bot.download(src, destination=dst)
    save(m.from_user.id, banner=str(dst))
    await m.answer("Баннер обновлён.")


@dp.message(F.video | F.animation | F.video_note | F.document)
async def handle_video(m: Message):
    if not guard(m):
        return await m.answer("Нет доступа.")
    src = file_of(m)
    if not src:
        return
    s = cfg(m.from_user.id)
    if not Path(s.banner).exists():
        return await m.answer("Баннер не найден. Приши его и ответь /banner.")

    # Проверяй размер файла
    file_size_mb = src.file_size / (1024 * 1024)
    if file_size_mb > 500:
        return await m.answer(f"Видео слишком большое ({file_size_mb:.0f} МБ). Максимум 500 МБ.")

    note = await m.reply("Качаю видео...")
    
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        inp, out = Path(tmp) / "in.mp4", Path(tmp) / "out.mp4"
        try:
            # Скачивай файл
            await bot.download(src, destination=inp)
            
            # Проверяй реальный размер после скачивания
            file_size_mb = inp.stat().st_size / (1024 * 1024)
            if file_size_mb > 20:
                await note.edit_text(f"Видео {file_size_mb:.0f} МБ, сжимаю до 20 МБ...")
                compressed = inp.parent / "compressed.mp4"
                did_compress = await video.compress_video(str(inp), str(compressed))
                if did_compress:
                    inp.unlink()
                    inp = compressed
                    file_size_mb = inp.stat().st_size / (1024 * 1024)
                    await note.edit_text(f"Сжато до {file_size_mb:.0f} МБ. Обрабатываю...")
            
            await note.edit_text("Режу кадры, выбиваю зелёный, клею баннер...")
            t0 = time.perf_counter()
            async with LIMIT:
                info = await video.process(str(inp), str(out), s)
            meta = await video.probe(str(out))
            
            # Проверяй размер выходного видео
            out_size_mb = out.stat().st_size / (1024 * 1024)
            if out_size_mb > 50:
                await note.edit_text(f"Выходное видео {out_size_mb:.0f} МБ, сжимаю до 50 МБ...")
                final = out.parent / "final.mp4"
                await video.compress_video(str(out), str(final), max_size_mb=45)
                out.unlink()
                out = final
                out_size_mb = out.stat().st_size / (1024 * 1024)
            
            await m.reply_video(
                FSInputFile(out, filename="ready.mp4"),
                width=meta["w"], height=meta["h"], duration=int(meta["dur"]),
                supports_streaming=True,
                caption=(
                    (f"Стоп-кадр на {info['at']:.1f}с, баннер держится {info['hold']:.1f}с"
                     if info["mode"] == "freeze" else
                     f"Баннер с {info['at']:.1f}с без паузы, звук ролика до {s.duck:g}")
                    + f" · срезано {s.cut_frames} кадр(ов)"
                    + (f" · апскейл {info['src']['w']}x{info['src']['h']} → "
                       f"{meta['w']}x{meta['h']} ({info['fit']})"
                       if info["fit"] != "none" else "")
                    + f" · {time.perf_counter()-t0:.1f}с"),
            )
            await note.delete()
        except Exception as e:
            log.exception("processing failed")
            await note.edit_text(f"Ошибка: {str(e)[-200:]}")


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("bot up")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
