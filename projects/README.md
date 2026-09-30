# projects/

One folder per recording. Everything in here except this file is git-ignored.

```
projects/<name>/
  <your recording>.mov      the source: drop it here (one video per project)
  <anything>.vtt            optional transcript with speaker labels (<v Name>)
  meta.json                 source file name, size, fps, duration
  transcript.json / .txt    word-level transcript; fillers shown as (um)
  plans/v001.json … CURRENT versioned edit plans
  renders/                  <id>_vNNN.mp4, _qa.json, _frames.png, _render.json
  approvals.json            what you approved (nothing is ever posted)
```

Start a project either way:

```bash
mkdir projects/product-demo && mv ~/Downloads/ProductDemo.mov projects/product-demo/
python bin/transcribe.py product-demo

# or let it make the folder and move the file (and a same-named .vtt) in:
python bin/transcribe.py ~/Downloads/ProductDemo.mov --name product-demo
```
