# LaTeX Preamble

The pinned template injects this preamble during PDF compilation. The
standalone renderer uses [`render/preamble.tex`](render/preamble.tex) and
[`render/cover.tex`](render/cover.tex).

```latex
% Core mathematics
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{amsfonts}
\usepackage{amsthm}

% Document layout
\usepackage{geometry}
\geometry{margin=0.25in}
\usepackage{float}
\usepackage{graphicx}
\usepackage{pdflscape}

% Tables
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{array}
\usepackage{etoolbox}
\BeforeBeginEnvironment{longtable}{\clearpage}

% Algorithm typesetting (for pseudocode in §2 Methodology)
\IfFileExists{algorithm2e.sty}{\usepackage[ruled,vlined,linesnumbered]{algorithm2e}}{}

% Code listings
\usepackage{listings}

% Typography and formatting
\usepackage{microtype}
\usepackage{xcolor}
\IfFileExists{siunitx.sty}{\usepackage[binary-units]{siunitx}}{}

% Cross-references and citations
\usepackage{hyperref}
\hypersetup{
    colorlinks=true,
    allcolors=red
}
\usepackage[capitalise,noabbrev]{cleveref}
\usepackage{natbib}

% ── Unicode-capable mono font for code listings ──────────────────────
% Use the same font as the standalone renderer through fontspec discovery.
\usepackage{fontspec}
\setmonofont{DejaVu Sans Mono}

% Math font for unicode-math: Latin Modern Math (TeX Live) has full BMP
% coverage including U+2223 (\mid), U+226A/226B (\ll/\gg), and the Greek/
% blackboard letters used in equations. Without an explicit \setmathfont,
% unicode-math falls back to lmroman text font which lacks several glyphs
% and emits "Missing character" warnings on every \mid in math mode.
\setmathfont{latinmodern-math.otf}
```
