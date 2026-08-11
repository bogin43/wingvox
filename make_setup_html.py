#!/usr/bin/env python3
"""Render SETUP.md to a styled setup.html for the installers to open.

Both installers used to `open SETUP.md` directly, which hands a raw
markdown file to whatever app the OS has registered for .md -- TextEdit on
a stock Mac, Notepad on Windows. Users got a wall of asterisks and pipe
characters at exactly the moment they needed clear instructions.

SETUP.md stays the single source of truth (GitHub renders it for anyone
browsing the repo); this just produces a readable local copy. Only the
markdown subset SETUP.md actually uses is supported -- headings, tables,
fenced and inline code, bold, links, blockquotes, ordered/unordered lists.
"""

import html
import re
import sys
from pathlib import Path

CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  max-width: 44rem; margin: 0 auto; padding: 3rem 1.25rem 6rem;
  color: #1c1c1e; background: #fff;
}
h1 { font-size: 2rem; letter-spacing: -0.02em; margin: 0 0 .5rem; }
h2 { font-size: 1.4rem; letter-spacing: -0.01em; margin: 2.5rem 0 .75rem;
     padding-top: 1.25rem; border-top: 1px solid #e5e5ea; }
h3 { font-size: 1.1rem; margin: 1.75rem 0 .5rem; }
p, li { color: #2c2c2e; }
a { color: #0066cc; }
code {
  font: .875em ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  background: #f2f2f7; padding: .15em .4em; border-radius: 4px;
}
pre {
  background: #f2f2f7; padding: 1rem; border-radius: 8px; overflow-x: auto;
  border: 1px solid #e5e5ea;
}
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; display: block; overflow-x: auto; }
th, td { text-align: left; padding: .6rem .75rem; border-bottom: 1px solid #e5e5ea; vertical-align: top; }
th { font-weight: 600; background: #f7f7fa; white-space: nowrap; }
blockquote {
  margin: 1rem 0; padding: .75rem 1rem; border-left: 3px solid #ffb340;
  background: #fff8ec; border-radius: 0 6px 6px 0;
}
blockquote p { margin: 0; }
hr { border: 0; border-top: 1px solid #e5e5ea; margin: 2.5rem 0; }
@media (prefers-color-scheme: dark) {
  body { color: #e5e5ea; background: #1c1c1e; }
  p, li { color: #d1d1d6; }
  h2 { border-top-color: #3a3a3c; }
  a { color: #6cb4ff; }
  code, pre { background: #2c2c2e; }
  pre { border-color: #3a3a3c; }
  th, td { border-bottom-color: #3a3a3c; }
  th { background: #2c2c2e; }
  blockquote { background: #2e2617; border-left-color: #ffb340; }
  hr { border-top-color: #3a3a3c; }
}
"""


def inline(text: str) -> str:
    """Escape, then re-introduce the inline markup we support. Code spans are
    pulled out first so their contents never get treated as markup."""
    spans: list = []

    def stash(match):
        spans.append(match.group(1))
        return f"\x00{len(spans) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = html.escape(text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return re.sub(
        r"\x00(\d+)\x00",
        lambda m: f"<code>{html.escape(spans[int(m.group(1))])}</code>",
        text,
    )


def slug(text: str) -> str:
    """GitHub-style heading anchor, so SETUP.md's own "Jump to: Mac | Windows"
    links resolve in the rendered page instead of going nowhere."""
    text = re.sub(r"<[^>]+>", "", text).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def convert(md: str) -> str:
    out, lines, i = [], md.splitlines(), 0
    list_tag = None
    para: list = []

    def close_list():
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    def close_para():
        # Markdown treats consecutive lines as one paragraph; emitting a <p>
        # per source line would break every wrapped sentence onto its own row.
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]

        if line.startswith("```"):
            close_para()
            close_list()
            i += 1
            block = []
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(html.escape(lines[i]))
                i += 1
            out.append("<pre><code>" + "\n".join(block) + "</code></pre>")
            i += 1
            continue

        # A table: header row, separator row of dashes, then body rows.
        if (line.startswith("|") and i + 1 < len(lines)
                and re.match(r"^\|[\s:|-]+\|$", lines[i + 1])):
            close_para()
            close_list()
            cells = [c.strip() for c in line.strip("|").split("|")]
            out.append("<table><thead><tr>"
                       + "".join(f"<th>{inline(c)}</th>" for c in cells)
                       + "</tr></thead><tbody>")
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                row = [c.strip() for c in lines[i].strip("|").split("|")]
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
                i += 1
            out.append("</tbody></table>")
            continue

        if match := re.match(r"^(#{1,4})\s+(.*)", line):
            close_para()
            close_list()
            level = len(match.group(1))
            text = inline(match.group(2))
            out.append(f'<h{level} id="{slug(match.group(2))}">{text}</h{level}>')
        elif re.match(r"^---+$", line):
            close_para()
            close_list()
            out.append("<hr>")
        elif line.startswith("> "):
            close_para()
            close_list()
            out.append(f"<blockquote><p>{inline(line[2:])}</p></blockquote>")
        elif match := re.match(r"^(\d+)\.\s+(.*)", line):
            close_para()
            if list_tag != "ol":
                close_list()
                out.append("<ol>")
                list_tag = "ol"
            out.append(f"<li>{inline(match.group(2))}</li>")
        elif match := re.match(r"^[-*]\s+(.*)", line):
            close_para()
            if list_tag != "ul":
                close_list()
                out.append("<ul>")
                list_tag = "ul"
            out.append(f"<li>{inline(match.group(1))}</li>")
        elif line.strip() == "":
            close_para()
            close_list()
        else:
            close_list()
            para.append(line.strip())
        i += 1

    close_para()
    close_list()
    return "\n".join(out)


def main():
    here = Path(__file__).parent
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "SETUP.md"
    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else here / "setup.html"
    body = convert(src.read_text(encoding="utf-8"))
    dest.write_text(
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Wingvox setup</title>\n"
        f"<style>{CSS}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n",
        encoding="utf-8",
    )
    print(dest)


if __name__ == "__main__":
    main()
