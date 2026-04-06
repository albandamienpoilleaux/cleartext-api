import re
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/blog", tags=["blog"])

BLOG_DIR = Path(__file__).parent.parent / "blog"

# Simple markdown to HTML converter (no external dependency needed)
def md_to_html(md: str) -> str:
    """Convert basic markdown to HTML."""
    lines = md.split("\n")
    html_lines = []
    in_code_block = False
    in_list = False
    in_table = False
    table_header_done = False

    for line in lines:
        # Code blocks
        if line.strip().startswith("```"):
            if in_code_block:
                html_lines.append("</code></pre>")
                in_code_block = False
            else:
                lang = line.strip().removeprefix("```").strip()
                cls = f' class="language-{lang}"' if lang else ""
                html_lines.append(f"<pre><code{cls}>")
                in_code_block = True
            continue

        if in_code_block:
            html_lines.append(line.replace("<", "&lt;").replace(">", "&gt;"))
            continue

        # Table
        if "|" in line and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.match(r"^[-:]+$", c) for c in cells):
                table_header_done = True
                continue
            if not in_table:
                html_lines.append("<table>")
                in_table = True
            tag = "th" if not table_header_done else "td"
            row = "".join(f"<{tag}>{c}</{tag}>" for c in cells)
            html_lines.append(f"<tr>{row}</tr>")
            continue
        elif in_table:
            html_lines.append("</table>")
            in_table = False
            table_header_done = False

        # Close list if we're not in one anymore
        if in_list and not line.strip().startswith("- ") and not re.match(r"^\d+\.", line.strip()):
            html_lines.append("</ul>")
            in_list = False

        # Empty lines
        if not line.strip():
            html_lines.append("")
            continue

        # Headers
        if line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("#### "):
            html_lines.append(f"<h4>{line[5:]}</h4>")
        # Horizontal rule
        elif line.strip() == "---":
            html_lines.append("<hr>")
        # Unordered list
        elif line.strip().startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{inline_md(line.strip()[2:])}</li>")
        # Ordered list
        elif re.match(r"^\d+\.\s", line.strip()):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            text = re.sub(r"^\d+\.\s", "", line.strip())
            html_lines.append(f"<li>{inline_md(text)}</li>")
        # Paragraph
        else:
            html_lines.append(f"<p>{inline_md(line)}</p>")

    if in_list:
        html_lines.append("</ul>")
    if in_table:
        html_lines.append("</table>")

    return "\n".join(html_lines)


def inline_md(text: str) -> str:
    """Convert inline markdown (bold, italic, code, links)."""
    # Links [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    # Bold **text**
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    # Italic *text*
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    # Inline code `text`
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def blog_page(title: str, content_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} — ClearText API</title>
    <meta name="description" content="{title}. Extract clean text from any URL with ClearText API.">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        :root {{
            --bg: #0a0a0a; --surface: #141414; --border: #222;
            --text: #e5e5e5; --text-dim: #888; --accent: #3b82f6;
            --green: #22c55e;
            --mono: 'SF Mono', 'Fira Code', 'JetBrains Mono', monospace;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg); color: var(--text); line-height: 1.8;
        }}
        header {{
            padding: 20px 0; border-bottom: 1px solid var(--border);
        }}
        header .container {{
            display: flex; justify-content: space-between; align-items: center;
        }}
        .logo {{ font-size: 18px; font-weight: 700; letter-spacing: -0.5px; text-decoration: none; color: var(--text); }}
        .logo span {{ color: var(--accent); }}
        nav a {{
            color: var(--text-dim); text-decoration: none; margin-left: 28px; font-size: 14px;
        }}
        nav a:hover {{ color: var(--text); }}
        .container {{ max-width: 720px; margin: 0 auto; padding: 0 24px; }}
        article {{ padding: 60px 0 80px; }}
        h1 {{ font-size: 36px; font-weight: 700; letter-spacing: -1px; margin-bottom: 32px; line-height: 1.2; }}
        h2 {{ font-size: 24px; font-weight: 700; margin: 40px 0 16px; letter-spacing: -0.5px; }}
        h3 {{ font-size: 20px; font-weight: 600; margin: 32px 0 12px; }}
        p {{ margin-bottom: 16px; color: var(--text-dim); }}
        a {{ color: var(--accent); }}
        strong {{ color: var(--text); }}
        ul {{ margin: 16px 0; padding-left: 24px; }}
        li {{ margin-bottom: 8px; color: var(--text-dim); }}
        pre {{
            background: var(--surface); border: 1px solid var(--border);
            border-radius: 8px; padding: 16px; overflow-x: auto;
            margin: 16px 0; font-family: var(--mono); font-size: 13px; line-height: 1.6;
        }}
        code {{
            font-family: var(--mono); font-size: 0.9em;
            background: var(--surface); padding: 2px 6px; border-radius: 4px;
        }}
        pre code {{ background: none; padding: 0; }}
        table {{
            width: 100%; border-collapse: collapse; margin: 16px 0;
            font-size: 14px;
        }}
        th, td {{
            border: 1px solid var(--border); padding: 10px 14px; text-align: left;
        }}
        th {{ background: var(--surface); font-weight: 600; }}
        td {{ color: var(--text-dim); }}
        hr {{ border: none; border-top: 1px solid var(--border); margin: 40px 0; }}
        .cta {{
            background: var(--surface); border: 1px solid var(--border);
            border-radius: 12px; padding: 32px; text-align: center; margin: 40px 0;
        }}
        .cta a {{
            display: inline-block; padding: 12px 28px; background: var(--accent);
            color: #fff; border-radius: 8px; text-decoration: none; font-weight: 600;
        }}
        footer {{
            padding: 40px 0; border-top: 1px solid var(--border);
            text-align: center; color: var(--text-dim); font-size: 13px;
        }}
    </style>
</head>
<body>
    <header>
        <div class="container">
            <a href="/" class="logo">Clear<span>Text</span></a>
            <nav>
                <a href="/blog">Blog</a>
                <a href="/#features">Features</a>
                <a href="/#pricing">Pricing</a>
                <a href="/docs">API Docs</a>
            </nav>
        </div>
    </header>
    <article>
        <div class="container">
            {content_html}
            <div class="cta">
                <p><strong>Ready to extract clean text from any URL?</strong></p>
                <a href="/docs">Try ClearText API free</a>
            </div>
        </div>
    </article>
    <footer>
        <div class="container">
            ClearText API — Built for developers who need clean content.
        </div>
    </footer>
</body>
</html>"""


ARTICLES = {
    "mercury-parser-alternative": {
        "title": "The Best Mercury Parser Alternative in 2026",
        "file": "mercury-parser-alternative.md",
    },
    "extract-text-from-url-python": {
        "title": "How to Extract Clean Text from a URL in Python (2026)",
        "file": "extract-text-from-url-python.md",
    },
    "best-content-extraction-apis-2026": {
        "title": "Best Content Extraction APIs in 2026: A Developer's Comparison",
        "file": "best-content-extraction-apis-2026.md",
    },
}


@router.get("/", response_class=HTMLResponse)
async def blog_index():
    items = ""
    for slug, info in ARTICLES.items():
        items += f'<li><a href="/blog/{slug}">{info["title"]}</a></li>\n'

    content = f"<h1>Blog</h1><ul>{items}</ul>"
    return HTMLResponse(blog_page("Blog", content))


@router.get("/{slug}", response_class=HTMLResponse)
async def blog_article(slug: str):
    if slug not in ARTICLES:
        raise HTTPException(status_code=404, detail="Article not found")

    article = ARTICLES[slug]
    md_path = BLOG_DIR / article["file"]
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Article file not found")

    md_content = md_path.read_text(encoding="utf-8")
    html_content = md_to_html(md_content)
    return HTMLResponse(blog_page(article["title"], html_content))
