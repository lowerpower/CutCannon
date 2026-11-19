# Brands: a look per show

A brand sets how a show's shorts look: the caption font, colors and word highlight, and the hook
card. Each brand is a folder here with a `brand.json`, plus any font files the brand needs
(`.ttf` / `.otf`, only fonts you have the rights to use).

```
brands/
├── terminal/brand.json     typed-terminal hook card, captions with the spoken word on a blue box
├── gold/brand.json         black hook card with gold text, captions with the spoken word in gold
└── <your-show>/
    ├── brand.json
    └── YourFont-Bold.ttf   optional: loaded only for this brand
```

Ask Claude for one: *"Create a CutCannon brand for my show from its look: the typed-terminal
wordmark from the intro, a monospace hook card, and clean captions in the blue from our
lower-third."* Claude writes the JSON, shows you a preview still, and adjusts it until you like it.

```bash
python bin/brand.py list                           # brands here
python bin/brand.py preview terminal podcast-ep12  # a still over a frame of the project -> brands/terminal/preview.png
python bin/brand.py show terminal                  # every field, with the defaults filled in
```

Use it in a plan with `"brand": "terminal"`, once at the top for every short or on one short.
`plan.py save` checks the brand and freezes a copy into that version, so editing a brand later
never changes how an old version renders: save a new version to pick up the change.

## Fields

Every field is optional. Leave one out and it keeps the default (the look CutCannon has without a
brand). Sizes and margins are pixels of a 1080-wide frame. Colors are `#RRGGBB`.

**`captions`**

| Field | Default | Meaning |
|---|---|---|
| `font`, `bold` | `"Montserrat Black"`, `false` | font family (from `fonts/`, the brand folder, or the system) |
| `size` | `84` | text size |
| `color` | `#FFFFFF` | text color |
| `outline`, `outline_width` | `#000000`, `7` | text outline |
| `shadow`, `shadow_color`, `shadow_opacity` | `3`, `#000000`, `0.5` | drop shadow |
| `highlight` | `#FFE500` | the word being spoken |
| `highlight_style` | `"color"` | `color`: the word turns `highlight`; `box`: a box of `highlight` behind it |
| `highlight_text`, `highlight_padding` | `null`, `16` | `box` only: the word's text color, and how far the box reaches |
| `uppercase` | `true` | captions in capitals |
| `margin_bottom`, `margin_side` | `560`, `80` | position: distance from the bottom, and from the sides |

**`hook`** (the hook card at the start of a short)

| Field | Default | Meaning |
|---|---|---|
| `font`, `bold`, `size` | `"Montserrat Black"`, `false`, `96` | |
| `color` | `#111111` | text color |
| `box`, `box_opacity`, `box_padding` | `#FFFFFF`, `1.0`, `28` | the card behind the text |
| `uppercase` | `true` | |
| `align` | `"center"` | `left`, `center` or `right` |
| `margin_top`, `margin_side` | `300`, `90` | position |
| `prefix`, `prefix_color` | `""`, `null` | text before the hook, e.g. `"> "` in another color |
| `cursor`, `cursor_color` | `""`, `null` | text after the hook, e.g. `"_"` |

A `description` field is shown by `brand.py list`.
