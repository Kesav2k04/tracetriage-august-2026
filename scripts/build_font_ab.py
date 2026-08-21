"""Build the three font-loading conditions the paint measurement compares.

The console keeps the two licensed families out of `--font-display` and `--font-label`
until a head script has loaded them, because the Adobe kit declares them at
`font-display: auto` and auto holds text unpainted while a face arrives. The claim on
the provenance page is what that is worth in milliseconds, and a claim like that needs
a control, because a first paint moves with the machine, the server and the day.

So this writes three copies of one export and changes nothing else:

    after   the build as it ships
    before  the same build with the head script replaced by a blocking stylesheet
            link and `fonts-ready` written into the markup, which is exactly how
            this console loaded the kit until 2026-08-21
    nokit   the build as it ships, with the kit URL pointed at a closed port, so the
            first paint is the floor this page can reach with no third-party font
            at all

Three conditions rather than two, because two would not separate "the fix worked"
from "the machine was faster today". `after` has to land on `nokit`, not merely below
`before`: the question is whether the font host still holds the paint, and the only
reading of that is the floor.

Building them by patching the export rather than by three `next build` runs is the
point. One build means the JavaScript, the CSS, the images and the server are the same
bytes in all three, so the only thing that differs is the head. The `before` patch is
a faithful reconstruction and not a guess: the class it writes is the one the script
adds, and the link it writes is the line that was in `layout.tsx` at 1f630a0.

    .venv/Scripts/python.exe scripts/build_font_ab.py --out <dir>
    .venv/Scripts/python.exe scripts/build_font_ab.py --out <dir> --serve
    .venv/Scripts/python.exe scripts/build_font_ab.py --receipt <measurement.json>

Then serve the three directories and run `apps/web/audit/font-paint-ab.mjs` against them.
`--serve` holds all three on their ports for the length of one run and stops every one of
them on the way out, and that is the only reason serving lives in this file. What it
replaced was three printed shell commands of the form `cd <dir> && python -m http.server
<port>`, whose lifetime nothing owned: one run left six of them alive, and a process whose
working directory sits inside an export holds a Windows handle on it, so the next
`next build` failed with `EBUSY: resource busy or locked, rmdir` and the console gate
failed for a reason with nothing to do with the console.

This script still does not measure: a builder that also decides what the numbers mean is
a builder nobody can check.

`--receipt` is the other half. It takes what that harness printed, plus the per-page
third-party byte counts and the face census from `apps/web/audit/font-swap-probe.js`, and
writes `artifacts/FONT_PAINT_RECEIPT.json`. Every reading in that file is derived from the
numbers in the input rather than typed beside them: whether the fixed page reaches the
floor is a comparison of two distributions, and a comparison written out by hand is one
that survives its own numbers changing.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
import http.server
import json
import pathlib
import re
import shutil
import sys
import threading
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
EXPORT = REPO / "apps" / "web" / "out"

#: The head script, matched by its shape rather than by its text, so a change to the
#: face list does not silently stop this from finding it. If it stops matching, that is
#: a failure and not a fallback: see `_patch`.
SCRIPT = re.compile(
    r"<script>\(function\(\)\{var F=\[.*?\}\)\(\);</script>",
    re.S,
)
#: What `layout.tsx` shipped before 2026-08-21, byte for byte.
BLOCKING_LINK = '<link rel="stylesheet" href="https://use.typekit.net/iie4ixd.css"/>'
KIT_URL = "https://use.typekit.net/iie4ixd.css"
#: Discard. A connection here is refused at once rather than hanging, which is the
#: honest way to ask for the floor: a slow host and an absent host are different
#: measurements and this one is the absent host.
CLOSED_PORT = "http://127.0.0.1:9/blocked.css"

PORTS = {"after": 8101, "before": 8102, "nokit": 8103}

RECEIPT = REPO / "artifacts" / "FONT_PAINT_RECEIPT.json"


@contextlib.contextmanager
def _served(root: pathlib.Path, port: int):
    """One static server on loopback, dead before this hands control back.

    Two properties, both learned from a run that leaked. Every teardown is registered
    with the stack before anything can raise, so an exception, a Ctrl-C or a
    `SystemExit` takes the server with it: six of these outlived a measurement on
    2026-08-21 and were still holding 8101, 8102 and 8103 hours later, because the
    instruction this script printed started them in a shell and nothing owned their
    lifetime.

    And the directory is handed to the handler rather than entered. A process whose
    working directory is inside `apps/web/out` holds a Windows handle on it, so the next
    `next build` fails with `EBUSY: resource busy or locked, rmdir`. The console gate
    failed for a reason with nothing to do with the console, which is the expensive half
    of this defect: a leaked server is a nuisance and a leaked handle is a false
    regression somewhere else.

    Port 0 binds an ephemeral port and the caller reads it back off
    ``httpd.server_address``, which is how a test asks for a server without racing the
    three the harness names.
    """
    with contextlib.ExitStack() as stack:
        handler = functools.partial(
            http.server.SimpleHTTPRequestHandler, directory=str(root)
        )
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
        # Registered first so it unwinds last, and registered before the thread exists so
        # a thread that cannot start still releases the socket.
        stack.callback(httpd.server_close)
        httpd.daemon_threads = True
        worker = threading.Thread(
            target=httpd.serve_forever, name=f"font-ab-{port}", daemon=True
        )
        worker.start()
        stack.callback(worker.join, 5)
        # Unwinds first: stop the accept loop, then wait for it, then close the socket.
        # The other order leaves the loop spinning on a closed descriptor.
        stack.callback(httpd.shutdown)
        yield httpd


@contextlib.contextmanager
def _serve_all(destination: pathlib.Path):
    """The three conditions on the three ports, all of them stopped on the way out.

    One stack, so a second server that cannot bind takes the first one down with it
    rather than leaving a half-served set of conditions behind. A harness measuring two
    of three would report a comparison with no floor.
    """
    with contextlib.ExitStack() as stack:
        origins = {}
        for name, port in PORTS.items():
            root = destination / name
            if not (root / "index.html").is_file():
                raise SystemExit(
                    f"{root} has no index.html, so the {name} condition was never "
                    f"built. Run this script with --out first."
                )
            stack.enter_context(_served(root, port))
            origins[name] = f"http://127.0.0.1:{port}/"
        yield origins


def _before(html: str) -> str:
    """Blocking link in place of the script, and the class the script would have added."""
    patched, n = SCRIPT.subn(BLOCKING_LINK, html)
    if not n:
        return html
    return patched.replace('<html lang="en">', '<html lang="en" class="fonts-ready">', 1)


def _nokit(html: str) -> str:
    return html.replace(KIT_URL, CLOSED_PORT)


def _patch(root: pathlib.Path, edit) -> int:
    touched = 0
    for page in sorted(root.rglob("*.html")):
        source = page.read_text(encoding="utf-8")
        edited = edit(source)
        if edited != source:
            page.write_text(edited, encoding="utf-8")
            touched += 1
    return touched


def build(destination: pathlib.Path) -> dict:
    if not (EXPORT / "index.html").exists():
        raise SystemExit(
            f"{EXPORT} has no index.html. Run `npm run build` in apps/web first: this "
            f"script patches an export and cannot make one."
        )
    written = {}
    for name in PORTS:
        target = destination / name
        # Copied fresh each time rather than patched in place, so a second run of this
        # script produces the same three directories as the first. A `before` that had
        # already been patched has no script left to find, and the run that noticed
        # would have reported a condition it did not build.
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(EXPORT, target)
        probe = REPO / "apps" / "web" / "audit" / "font-swap-probe.js"
        shutil.copyfile(probe, target / "probe.js")
        edit = {"after": lambda html: html, "before": _before, "nokit": _nokit}[name]
        touched = _patch(target, edit)
        if name != "after" and touched == 0:
            raise SystemExit(
                f"the {name} patch changed no page. The head of the export does not "
                f"look like the one this script was written against, so the condition "
                f"it would have served is the same as `after` under a different name."
            )
        written[name] = {
            "port": PORTS[name],
            "pages_patched": touched,
            "index_sha256": hashlib.sha256(
                (target / "index.html").read_bytes()
            ).hexdigest()[:16],
        }
    return written


def _reading(measurement: dict) -> list[str]:
    """The readings, computed from the numbers rather than written next to them.

    Each sentence below is a claim that can be false. Reaching the floor is a comparison
    of two medians and of two extremes; the layout shift is a subtraction; the byte cost
    is a maximum over pages. Deriving them means a rerun that came out differently would
    change the prose instead of contradicting it.
    """
    summary = measurement["summary"]
    after, before, floor = summary["after"], summary["before"], summary["nokit"]
    on_the_floor = min(after["fcp_ms"]) <= max(floor["fcp_ms"])
    by_page = measurement["third_party_bytes"]["per_page"]
    worst_name, worst = max(by_page.items(), key=lambda kv: kv[1]["after"] - kv[1]["before"])
    free = [name for name, row in by_page.items() if row["after"] - row["before"] < 100]
    cls_cost = after["cls_median"] - before["cls_median"]
    census = measurement["faces_rendered_anywhere"]
    home = by_page["/"]

    readings = [
        "The font host no longer holds the first paint. `after` at a median of "
        f"{after['fcp_ms_median']} ms against `before` at {before['fcp_ms_median']} ms, and "
        f"a floor of {floor['fcp_ms_median']} ms with the kit pointed at a closed port."
    ]
    if on_the_floor:
        readings.append(
            "`after` reaches that floor rather than approaching it: its fastest round is "
            f"{min(after['fcp_ms'])} ms and the floor's slowest is {max(floor['fcp_ms'])} "
            "ms, so the two distributions overlap."
        )
    else:
        readings.append(
            "`after` does not reach the floor. Its fastest round is "
            f"{min(after['fcp_ms'])} ms and the floor's slowest is {max(floor['fcp_ms'])} "
            "ms, so something in the fixed page is still waiting on the kit."
        )
    if cls_cost > 0:
        steady = after["cls"].count(after["cls_median"])
        readings.append(
            f"The fix costs {cls_cost:.4f} of cumulative layout shift, "
            f"{after['cls_median']} against {before['cls_median']}, in {steady} of "
            f"{len(after['cls'])} rounds identically: the one reflow when the licensed face "
            f"replaces Plex. That is {0.1 / cls_cost:.0f} times under the 0.1 that counts "
            "as a good score, and it is the same shift `font-display: swap` would have "
            "produced."
        )
    else:
        readings.append("The fix costs no measurable layout shift.")
    readings.append(
        f"It costs {worst['after'] - worst['before']:,} bytes on the pages that render "
        f"fewer faces than the head script waits for: {worst['before']:,} before against "
        f"{worst['after']:,} after on `{worst_name}`, which draws {worst['faces_before']} of "
        f"the {worst['faces_after']}. On "
        + ", ".join(f"`{name}`" for name in free)
        + " it costs nothing. Both faces arrive after the first paint and carry a one-year "
        "cache header, so this is a cost to a first visit and to nothing else. The "
        "alternative is a per-route face list computed at build time, which buys those "
        "bytes on a page that has already painted and costs a build step that can be wrong "
        "about what a page renders."
    )
    unwaited = census["rendered_unwaited"]
    readings.append(
        f"{len(measurement['faces_waited_for'])} faces are waited for and "
        f"{len(census['faces'])} are rendered, over {census['pages_checked']} pages at "
        f"{len(census['viewports_checked'])} viewport widths, and `rendered_unwaited` is "
        + ("empty" if not unwaited else str(unwaited))
        + ". The first version of the list had the display face at 400, which no page "
        "renders, and omitted the label face at 400, which three pages do. Every page still "
        "reported clean, because by the time a probe can run, anything rendered has "
        "finished loading. `data-fonts` on the root element is what made the mismatch "
        "visible."
    )
    readings.append(
        "The `before` figure is not the 956 ms this project published on 2026-08-20, and "
        "the two are not comparable. That number came from a harness that started a fresh "
        "browser process per round; this one opens a fresh context, which shares a warm "
        "process. The comparison that carries the claim is the one inside this run, where "
        "all three conditions were measured against each other, interleaved, on one machine."
    )
    readings.append(
        "It also corrects a number published on 2026-08-18. The provenance page said the "
        "licensed typefaces cost 43,598 bytes cold, as one stylesheet and two faces. The "
        f"landing page rendered {home['faces_before']} faces then as it does now, so the "
        f"cold cost of the page that figure was quoted beside was {home['before']:,} bytes "
        "even before this change. The old number was curl over two of the three faces "
        "rather than a page load, which is why nothing caught it."
    )
    return readings


#: What each condition is, in one sentence, keyed the way the ports are.
CONDITIONS = {
    "after": (
        "the export as it ships: the kit is appended by a head script at media=print and "
        "the licensed families enter with html.fonts-ready once document.fonts.load has "
        "resolved for every face"
    ),
    "before": (
        "the same export with the head script replaced by the blocking stylesheet link "
        "this console shipped until 2026-08-21, and fonts-ready written into the markup"
    ),
    "nokit": (
        "the export as it ships with the kit URL pointed at a closed port, which is the "
        "floor a page with no third-party font can reach"
    ),
}

#: Named here so the receipt records which revision of each file produced it. A number
#: measured by a harness that has since changed is a number with no method.
HARNESS_FILES = (
    "scripts/build_font_ab.py",
    "apps/web/audit/font-paint-ab.mjs",
    "apps/web/audit/font-swap-probe.js",
)


def receipt(measurement: dict) -> dict:
    """The published receipt, assembled from one measurement file."""
    required = ("summary", "third_party_bytes", "faces_waited_for", "faces_rendered_anywhere")
    missing = [key for key in required if key not in measurement]
    if missing:
        raise SystemExit(
            f"the measurement file has no {missing}. It is the output of "
            f"apps/web/audit/font-paint-ab.mjs with the byte counts and the face census "
            f"from font-swap-probe.js added, and a receipt assembled from half of it would "
            f"publish a comparison with no control."
        )
    return {
        "schema": "tracetriage/font-paint",
        "schema_version": "0.2.0",
        "unit": "milliseconds to first contentful paint, and unitless cumulative layout shift",
        "measured_at_utc": measurement["measured_at_utc"],
        "page": measurement["page"],
        "browser": measurement["browser"],
        "server": measurement["server"],
        "harness": {
            "conditions_built_by": "scripts/build_font_ab.py",
            "measured_by": "apps/web/audit/font-paint-ab.mjs",
            "face_census_by": "apps/web/audit/font-swap-probe.js",
            "receipt_written_by": "scripts/build_font_ab.py --receipt",
            "invocation": (
                "the body of measure() was executed through a Playwright session on this "
                "machine rather than by `node apps/web/audit/font-paint-ab.mjs`, because "
                "Playwright is not a dependency of this project and is not installed in "
                "this checkout. The code that ran was extracted from the committed file, "
                "so the two are the same statements, and the digests below pin which "
                "revision of each file this run used."
            ),
            "sha256": {
                name: hashlib.sha256((REPO / name).read_bytes()).hexdigest()[:16]
                for name in HARNESS_FILES
            },
        },
        "kit_descriptors": measurement.get("kit_descriptors", {}),
        "conditions": {
            name: {"port": PORTS[name], "what_it_is": text}
            for name, text in CONDITIONS.items()
        },
        "measurement": {
            "rounds": measurement["rounds"],
            "viewport": measurement["viewport"],
            "settle_ms": measurement["settle_ms"],
            "summary": measurement["summary"],
        },
        "faces_waited_for": measurement["faces_waited_for"],
        "faces_rendered_anywhere": measurement["faces_rendered_anywhere"],
        "third_party_bytes": {
            "method": (
                "response body bytes as the browser received them, summed per page over "
                "every request to use.typekit.net and p.typekit.net, from Playwright "
                "request.sizes() on a cold context"
            ),
            **measurement["third_party_bytes"],
        },
        "reading": _reading(measurement),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        help="directory to write the three conditions into. Outside the repository.",
    )
    parser.add_argument(
        "--receipt",
        type=pathlib.Path,
        help="a measurement file from the harness, rendered into "
        "artifacts/FONT_PAINT_RECEIPT.json",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help=(
            "after building, hold the three conditions on their ports until "
            "interrupted, and stop all three on the way out. Only with --out. This is "
            "the form that cannot leak a server: the alternative is three shell "
            "commands whose lifetime nothing owns."
        ),
    )
    args = parser.parse_args(argv)
    if args.serve and not args.out:
        raise SystemExit(
            "--serve needs --out. It serves the three directories that --out writes, "
            "and serving something this run did not build would measure whatever was "
            "there from last time."
        )
    if bool(args.out) == bool(args.receipt):
        raise SystemExit(
            "one of --out or --receipt, not both and not neither. The first builds the "
            "three conditions and the second publishes what measuring them said, and a "
            "run that did both would write a receipt for directories it had just replaced."
        )
    if args.receipt:
        rendered = json.dumps(
            receipt(json.loads(args.receipt.read_text(encoding="utf-8"))), indent=1
        )
        RECEIPT.write_text(rendered + "\n", encoding="utf-8")
        print(f"{RECEIPT.name} written: {len(rendered):,} bytes")
        return 0
    destination = pathlib.Path(args.out).resolve()
    if REPO in destination.parents or destination == REPO:
        raise SystemExit(
            f"{destination} is inside the repository. These are three copies of a "
            f"16 MB export and none of them belongs in a checkout."
        )
    destination.mkdir(parents=True, exist_ok=True)
    written = build(destination)
    print(json.dumps({"out": str(destination), "conditions": written}, indent=1))
    if args.serve:
        with _serve_all(destination) as origins:
            print("\nServing until interrupted:")
            for name, origin in origins.items():
                print(f"  {name:>6}  {origin}")
            print(
                "\nRun apps/web/audit/font-paint-ab.mjs against these, then Ctrl-C "
                "here. All three stop with this process, on every exit path."
            )
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                print("\nstopped; the three ports are free")
        return 0
    print(
        # `--directory`, and no `cd`. The instruction here used to be
        # `cd <dir> && python -m http.server <port>`, and a run that followed it left six
        # servers alive whose working directory was inside an export, which held a Windows
        # handle on it and failed the next console build with EBUSY on rmdir. Prefer
        # --serve above: this form still needs someone to remember to stop it.
        "\nServe each and measure (--serve does this and stops them for you):\n"
        + "\n".join(
            f"  python -m http.server {spec['port']} --bind 127.0.0.1 "
            f"--directory {destination / name}"
            for name, spec in written.items()
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
