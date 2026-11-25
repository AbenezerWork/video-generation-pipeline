# UI fonts

The studio console bundles two typefaces so the UI looks the same offline. Both are licensed
under the SIL Open Font License 1.1, which permits bundling and redistributing the fonts with
software. The files here are the upstream web fonts, unmodified (only renamed on disk), and
each licence text sits next to them. No Ethiopic font is bundled for the UI: Amharic content
uses the system font (`--font-content-am` in `tokens.css`).

| File | Face | Version | Licence |
| --- | --- | --- | --- |
| `MonaSansVF.woff2` | Mona Sans, variable: `wdth` 75–125, `wght` 200–900, `opsz` | 2.027 | `OFL-MonaSans.txt` |
| `JetBrainsMono-Regular.woff2` | JetBrains Mono Regular (400) | 2.304 | `OFL-JetBrainsMono.txt` |
| `JetBrainsMono-SemiBold.woff2` | JetBrains Mono SemiBold (600) | 2.304 | `OFL-JetBrainsMono.txt` |

## Sources

- **Mona Sans 2.027**, copyright 2022 The Mona Sans Project Authors, Reserved Font Name "Mona".
  Release `v2.0.27` of <https://github.com/github/mona-sans> (2026-05-19).
  `MonaSansVF.woff2` is `fonts/webfonts/variable/MonaSansVF[wdth,opsz,wght].woff2` at that tag
  (git blob `9f7c78308a8b3c44116413b90a162712241e6f19`, SHA-256
  `875ad1fab0c1f4854927fa8086963fb6ddd4608b04a58b267cddf8a9d78f80d3`), the same font the
  release's `mona-sans-webfonts-v2.0.27.zip` carries. `OFL-MonaSans.txt` is `OFL.txt` from the
  release asset `mona-sans-variable-v2.0.27.zip` (SHA-256
  `a95127550b2957ff84cd636d4532b227ddc33d3485082437fa27816ef1d066ec`, matching the digest
  GitHub publishes for the asset).
- **JetBrains Mono 2.304**, copyright 2020 The JetBrains Mono Project Authors. Release asset
  `JetBrainsMono-2.304.zip` of <https://github.com/JetBrains/JetBrainsMono> (tag `v2.304`,
  2023-01-14; zip SHA-256 `6f6376c6ed2960ea8a963cd7387ec9d76e3f629125bc33d1fdcd7eb7012f7bbf`).
  The two woff2 files are `fonts/webfonts/JetBrainsMono-Regular.woff2` (SHA-256
  `a9cb1cd82332b23a47e3a1239d25d13c86d16c4220695e34b243effa999f45f2`) and
  `fonts/webfonts/JetBrainsMono-SemiBold.woff2` (SHA-256
  `918edad542a1da608fd2ba8daebaff9ac802309103fe760eed465b8b4e47faf1`);
  `OFL-JetBrainsMono.txt` is the zip's `OFL.txt`.

The embedded name tables were checked after download (`Mona Sans VF`, "Version 2.027";
`JetBrains Mono`, "Version 2.304"), as were the Mona Sans variation axes.

## Why these faces

Mona Sans is the expressive display and interface face: its width axis runs from condensed to
expanded, so headings can be wide and declarative while dense rail labels stay compact, all
from one file. JetBrains Mono sets timings, counts and provider names with tabular, slashed-zero
digits so live numbers don't jitter.

## Updating

Download a newer release from the same upstream repository, check the licence is still OFL 1.1,
replace the files and licence texts, and update the versions and hashes above. The test
`tests/test_ui_design_system.py` checks every `@font-face` source in `tokens.css` is a local
woff2 and that the licences ship in the wheel.
