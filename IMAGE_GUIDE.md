# Изображения единорогов

## Почему бот может показывать схематическую карточку

Код не умеет сам получать фотореалистичные изображения из интернета. Он ищет локальные файлы в:

`unicorn_images/`

Если файла нет, создаётся простая fallback-карточка, чтобы бот не падал.

## Имена файлов

Имя должно точно совпадать с `id` из `data.py`.

Примеры:

- `unicorn_images/heather.jpg`
- `unicorn_images/elderbloom.jpg`
- `unicorn_images/eclipsefoal.jpg`
- `unicorn_images/glasshorn.jpg`
- `unicorn_images/firststar.jpg`

Поддерживаются `.jpg`, `.jpeg`, `.png`, `.webp`.

## Полный список

Шепчущий лес:

- heather
- pearlbrook
- mossmane
- dusk
- ambermane
- ivycrown
- whitehart
- elderbloom
- midnightcrown (секретный)

Лунные топи:

- misthoof
- moonreed
- lanternmane
- silverfen
- wisphorn
- mireoracle
- eclipsefoal
- drownedstar
- silentoracle (секретный)

Хрустальный кряж:

- glasshorn
- stormcrest
- frostveil
- comet
- aurora
- astral
- sunseraph
- firststar
- skyancestor (секретный)

## Рекомендуемый визуальный стиль

Базовый промпт:

> photorealistic wildlife photography of a biologically plausible unicorn, realistic horse anatomy and musculature, natural coat and mane, one keratin horn, natural environmental lighting, professional telephoto wildlife lens, documentary animal photography, highly realistic fur, no wings, no armor, no saddle, no text, no frame

Далее добавляй описание конкретного вида и его среды.

Например `glasshorn.jpg`:

> photorealistic wildlife photography of a pale grey unicorn on a remote snowy high-altitude mountain ridge, realistic horse anatomy, single translucent crystalline horn with subtle internal striations, cold morning light, visible breath, snow-covered rocks, professional telephoto wildlife lens, documentary animal photography, no wings, no armor, no text

`elderbloom.jpg`:

> photorealistic wildlife photography of an extremely rare pale forest unicorn in an ancient rain-soaked pine forest, realistic horse anatomy, tiny natural white flowers tangled in the mane, matte ivory horn, mist, wet vegetation, documentary wildlife photography, no wings, no armor, no text

`firststar.jpg`:

> photorealistic wildlife photography of an elusive pearl-white unicorn on a remote crystalline mountain ridge during a meteor shower at dusk, realistic horse anatomy, long pale mane in mountain wind, subtly luminous horn, faint starlight reflected in the coat, plausible natural landscape, photographed from a distance with a professional telephoto wildlife lens, mysterious but realistic, no wings, no armor, no text

## После добавления изображений

Локально просто перезапусти:

```cmd
py bot.py
```

На сервере:

```bash
sudo systemctl restart unicorn-bot
```

Если файл не подхватывается, проверь регистр имени и командой:

```bash
ls -la unicorn_images
```
