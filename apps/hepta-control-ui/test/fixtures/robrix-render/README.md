# Failed actual renderer regression

`unreadable-e51a1d0f.png` is the actual Chromium 1280px default-host capture
from source `e51a1d0fe5fdb8e3566b292aa0babe0603161812`, Actions run
`37032742983`, artifact `11237964859`. Its startup smoke passed while all
text remained colored blocks. It contains an empty local-draft scene, no live
conversation or credentials. Pixel OCR must reject it. This test fixture is
not a product asset and does not establish full visual or accessibility acceptance.
