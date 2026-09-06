# Инструкция по настройке бота в Telegram

## Шаг 1: Создай бота и получи токен

1. Напиши `@BotFather` в Telegram (это официальный бот для создания ботов)
2. Отправь `/newbot`
3. Следуй инструкциям:
   - **Имя бота** (просто красивое имя, как "My Banner Bot")
   - **Юзернейм** (заканчивается на `_bot`, например `my_banner_bot`)
4. BotFather вернёт тебе **API токен**, выглядит как `123456789:ABCdefGHIjklMNOpqrsTUVwxyz-1A2b3c`
5. **Сохрани этот токен**, он нужен для бота

## Шаг 2: Скачай архив с ботом

Распакуй `tiktok-banner-bot-v3.zip` — внутри папка `bot` со всеми файлами.

## Шаг 3: Первый запуск (локально)

### На Linux / macOS:
```bash
cd bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt        # нужен ffmpeg в системе
cp .env.example .env
```

Отредактируй `.env` (первая строка):
```
BOT_TOKEN=твой_токен_от_BotFather
```

Запусти:
```bash
set -a && . ./.env && set +a && python bot.py
```

### На Windows (PowerShell):
```powershell
cd bot
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Отредактируй `.env`, потом запусти:
```powershell
gci env:* | % { [Environment]::SetEnvironmentVariable($_.Name, $_.Value) }
python bot.py
```

## Шаг 4: Загрузи свой баннер

1. Напиши боту в личку `/help` — увидишь список команд
2. Отправь боту видео, где баннер на зелёном фоне (`#00FF00`)
3. **Ответь** на это видео командой `/banner` — баннер сохранится
4. Теперь отправляй любые видео боту — они вернутся с твоим баннером

## Шаг 5: Настройка режимов

### Режим отработки:
- `/mode auto` — короткие видео (< 10с) встают на **стоп-кадр**, длинные идут **без паузы, но со звуком вниз**
- `/mode freeze` — всегда стоп-кадр посередине
- `/mode duck` — всегда без паузы, звук ролика приглушается

### Апскейл и вписывание:
- `/size 1080x1920` — целевое разрешение (всё меньше подтянется)
- `/fit auto` — вертикальные ролики заполняют целый кадр (cover), горизонтальные — с размытым фоном (blur)
- `/fit cover` — заполнить и обрезать
- `/fit contain` — вписать, чёрные полосы
- `/fit blur` — вписать, размытый фон

### Звук и заморозка:
- `/duck 0.18` — громкость оригинала под баннером (0-1)
- `/vol 1.4` — громкость баннера (0-4)
- `/blur 8` — размытие стоп-кадра (0 = нет)

### Остальное:
- `/cut 3` — сколько кадров срезать с начала
- `/scale 0.92` — ширина баннера % от видео
- `/pos 0.5` — высота баннера (0 = вверх, 0.5 = центр, 1 = вниз)
- `/key 0x00FF00 0.30 0.12` — цвет, похожесть и мягкость хромакея
- `/jitter on` — микро-кроп для уникального хеша
- `/settings` —看 текущие значения

## Шаг 6: Запуск на сервере через Docker

Если хочешь запустить на сервере (DigitalOcean, AWS, VPS):

```bash
cd bot
docker build -t banner-bot .
docker run -d --restart unless-stopped \
  --env-file .env \
  -v $PWD/banners:/app/banners \
  --name banner_bot \
  banner_bot
```

## Лимиты и важное

- **Bot API**: скачивание до 20 МБ, отправка до 50 МБ
- Если видео больше 20 МБ — используй **local Bot API server** (поддерживает до 2 ГБ)
- Первый запуск может быть медленным (ffmpeg + Python асинхро)
- Параллельная обработка регулируется `CONCURRENCY` в `.env` (по умолчанию 2)

## Troubleshooting

**Ошибка `ffmpeg not found`**
- Linux: `sudo apt install ffmpeg` (Ubuntu/Debian) или `brew install ffmpeg` (macOS)
- Windows: скачай с https://ffmpeg.org/download.html, добавь в PATH

**Ошибка `aiogram not found`**
- Убедись, что активирован venv и запустил `pip install -r requirements.txt`

**Бот не отвечает**
- Проверь, что токен в `.env` правильный
- Проверь интернет
- Смотри логи консоли — там ошибки

---

**Ready to go!** Отправь боту видео, и он вернёт его с баннером. Удачи! 🚀
