"""Browser smoke test for the atlas page: run it after changing tools/atlas_template.html.

    pip install playwright && python -m playwright install chromium     (once)
    python tests/page_smoke.py              # example roadmap and a generated large one
    python tests/page_smoke.py --shots      # also save screenshots to tests/shots/ to look at

It builds the page, opens it in headless Chromium and checks that:
  - no view throws or logs an error (chart, every territory, town and a sample of tasks, every page);
  - nothing scrolls sideways at phone width (390 px);
  - in every territory, houses, town names, the territory name and signposts don't overlap;
  - leaving during a zoom (Back, or another tab) leaves the view matching the address;
  - Esc in the search box only closes the search.
Exit code 0 when everything passes, 1 when something fails, 2 when Playwright isn't installed.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
SHOTS = Path(__file__).resolve().parent / "shots"

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("Playwright isn't installed: pip install playwright && python -m playwright install chromium")
    sys.exit(2)

OVERLAPS = r"""() => {
  const R = e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; };
  const items = [];
  document.querySelectorAll('#rsvg .r-town').forEach(g => {
    const id = g.querySelector('.r-hub').dataset.id;
    items.push({k: 'town', id, b: R(g.querySelector('.r-hub .disc'))});
    g.querySelectorAll(':scope > text').forEach(t => items.push({k: 'name', id, b: R(t)}));
    g.querySelectorAll('.mb').forEach(m => { const r = R(m.querySelector('.mb-hit')), x = (r[0] + r[2]) / 2, y = (r[1] + r[3]) / 2;
      items.push({k: 'house', id, tid: m.dataset.id, b: [x - 13, y - 13, x + 13, y + 13]}); });
  });
  document.querySelectorAll('#rsvg .ghost').forEach(g => { const c = g.querySelector('.track') || g.querySelector('.disc');
    items.push({k: 'ghost', id: g.dataset.id, b: R(c)}); const t = g.querySelector('text'); if (t) items.push({k: 'ghostname', id: g.dataset.id, b: R(t)}); });
  const t = document.querySelector('#rsvg .r-title'); if (t) items.push({k: 'title', id: '*', b: R(t)});
  document.querySelectorAll('#rsvg .r-edge').forEach(e => items.push({k: 'sign', id: e.dataset.ws, b: R(e)}));
  const ov = (a, b) => Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  const out = [];
  for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
    const a = items[i], b = items[j];
    if (a.id === b.id && a.k !== 'title' && !(a.k === 'house' && b.k === 'house')) continue;
    if (ov(a.b, b.b) > 60) out.push(`${a.k} ${a.tid || a.id} on ${b.k} ${b.tid || b.id}`);
  }
  return out;
}"""
SIDEWAYS = """() => document.documentElement.scrollWidth > document.documentElement.clientWidth"""


def make_large_roadmap(root: Path):
    """A placeholder roadmap about six times the size of the example, to find layout problems."""
    rng = random.Random(7)
    road = root / "roadmap"
    for sub in ("workstreams", "areas", "tasks", "milestones"):
        shutil.rmtree(road / sub, ignore_errors=True)
        (road / sub).mkdir(parents=True)

    def write(sub, name, fm, body=""):
        lines = ["---"] + [f"{k}: {v}" for k, v in fm.items()] + ["---", body]
        (road / sub / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for mid in ("M1", "M2", "M3"):
        write("milestones", mid, {"type": "milestone", "id": mid})
    streams = [("WOW", "Ways of Working"), ("STD", "Standards and Assurance"), ("TOOL", "Tooling and Automation"),
               ("REL", "Release and Delivery"), ("PPL", "People and Skills"), ("SUP", "Supplier and IP Management")]
    done = []
    for wi, (wid, wt) in enumerate(streams):
        write("workstreams", wt, {"type": "workstream", "id": wid}, f"Placeholder summary for {wt}.")
        for ai in range([5, 6, 5, 4, 5, 5][wi]):
            aid = f"{wid}{ai + 1}"
            write("areas", f"{aid} {wt.split()[0]} area {ai + 1}", {"type": "area", "id": aid, "parent": wid,
                                                                     "title": f"{wt.split()[0]} area {ai + 1}"})
            prev = []
            for ti in range(14 if (wi, ai) == (2, 0) else rng.randint(3, 8)):
                tid = f"{aid}-{ti + 1:02d}"
                deps = sorted({rng.choice(prev[-3:])} if prev and rng.random() < 0.8 else set())
                status = rng.choice(["planned", "planned", "in-progress", "review", "done", "adopted"])
                fm = {"type": "task", "id": tid, "parent": aid, "status": status, "owner": rng.choice(["Avery", "Blake", "Casey"]),
                      "milestone": rng.choice(["M1", "M2", "M3"]), "estimate": rng.choice([1, 2, 3, 5])}
                if deps:
                    fm["depends_on"] = "[" + ", ".join(deps) + "]"
                write("tasks", f"{tid} Placeholder task {tid} with a longer title", fm,
                      "Placeholder.\n\n## Subtasks\n- [x] One\n- [ ] Two\n" if status == "in-progress" else "Placeholder.")
                prev.append(tid)
                done.append(tid)


def build(root: Path) -> Path:
    out = root / "public" / "index.html"
    subprocess.run([sys.executable, str(KIT / "tools" / "build_atlas.py"), "--root", str(root), "--out", str(out)],
                   check=False, capture_output=True)
    return out


async def check_page(pw, name: str, page_file: Path, shots: bool) -> list:
    problems = []
    browser = await pw.chromium.launch()
    url = page_file.as_uri()

    async def open_page(width, height, scheme="light"):
        ctx = await browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
        pg = await ctx.new_page()
        pg.on("pageerror", lambda e: problems.append(f"{name}: page error: {e}"))
        pg.on("console", lambda m: problems.append(f"{name}: console {m.type}: {m.text}") if m.type in ("error", "warning") else None)
        await pg.goto(url)
        await pg.wait_for_function("document.body.hasAttribute('data-depth')", timeout=15000)
        return pg

    async def visit(pg, h, wait=650):
        await pg.evaluate("h => { location.hash = h; }", h)
        await pg.wait_for_timeout(wait)
        return await pg.evaluate("() => [location.hash, Array.from(document.querySelectorAll('main > .view')).filter(v => !v.hidden).map(v => v.id)[0]]")

    pg = await open_page(1440, 900)
    data = await pg.evaluate("() => JSON.parse(document.getElementById('atlas-data').textContent)")
    regions = [w["id"] for w in data["workstreams"] if any(a.get("parent") == w["id"] for a in data["areas"])]
    hashes = (["#map", "#progress", "#list", "#board", "#checks"] + [f"#region.{w}" for w in regions]
              + [f"#area.{a['id']}" for a in data["areas"]] + [f"#task.{t['id']}" for t in data["tasks"][::5]])
    for h in hashes:
        await visit(pg, h, 450)
    for w in regions:
        await visit(pg, f"#region.{w}", 800)
        for o in await pg.evaluate(OVERLAPS):
            problems.append(f"{name} territory {w}: {o}")
        if shots:
            await pg.screenshot(path=str(SHOTS / f"{name}-region-{w}.png"))
    # leaving during a zoom: the view must match the address afterwards
    await visit(pg, "#map", 900)
    await pg.evaluate("() => { document.querySelector('#world .town').dispatchEvent(new MouseEvent('click', {bubbles: true})); setTimeout(() => history.back(), 100); }")
    await pg.wait_for_timeout(1500)
    h, v = await pg.evaluate("() => [location.hash, Array.from(document.querySelectorAll('main > .view')).filter(v => !v.hidden).map(v => v.id)[0]]")
    if v != "v-map":
        problems.append(f"{name}: Back during a zoom left {v} on screen at {h}")
    # Esc in the search box closes the search and nothing else
    first = data["tasks"][0]["id"]
    await visit(pg, f"#task.{first}", 900)
    await pg.keyboard.press("/")
    await pg.keyboard.type(first[:2])
    await pg.keyboard.press("Escape")
    await pg.wait_for_timeout(500)
    if await pg.evaluate("() => location.hash") != f"#task.{first}":
        problems.append(f"{name}: Esc in the search box also left the task")
    if shots:
        for h in ("#map", f"#area.{data['areas'][0]['id']}", f"#task.{first}", "#progress"):
            await visit(pg, h, 1000)
            await pg.screenshot(path=str(SHOTS / f"{name}-{h[1:].replace('.', '-')}.png"))
    # phone width
    pg = await open_page(390, 844)
    for h in hashes[:5] + [f"#region.{w}" for w in regions[:3]] + [f"#area.{a['id']}" for a in data["areas"][:3]] + [f"#task.{first}"]:
        await visit(pg, h, 450)
        if await pg.evaluate(SIDEWAYS):
            problems.append(f"{name}: scrolls sideways at 390 px on {h}")
    if shots:
        await visit(pg, f"#region.{regions[0]}", 900)
        await pg.screenshot(path=str(SHOTS / f"{name}-phone-region.png"))
        pg = await open_page(1440, 900, "dark")
        await pg.wait_for_timeout(800)
        await pg.screenshot(path=str(SHOTS / f"{name}-map-dark.png"))
    await browser.close()
    return problems


async def main(shots: bool) -> int:
    if shots:
        SHOTS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        example = Path(tmp) / "example"
        large = Path(tmp) / "large"
        for dst in (example, large):
            shutil.copytree(KIT, dst, ignore=shutil.ignore_patterns(".git", ".github", "public", "tests", "__pycache__"))
        make_large_roadmap(large)
        pages = {"example": build(example), "large": build(large)}
        problems = []
        async with async_playwright() as pw:
            for name, page_file in pages.items():
                found = await check_page(pw, name, page_file, shots)
                print(f"{name}: {'ok' if not found else str(len(found)) + ' problem(s)'}")
                problems += found
    for p in problems:
        print("  " + p)
    if shots:
        print(f"Screenshots in {SHOTS}")
    return 1 if problems else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--shots", action="store_true", help="save screenshots to tests/shots/")
    sys.exit(asyncio.run(main(ap.parse_args().shots)))
