"""Verify the gate 4 bundle against its commitment, then pack it into one transportable file.

Gate 4 is the only gate here that needs a person, and the reason it is still open is not
that the instrument is missing. `scripts/build_gate4_worksheet.py` builds it,
`scripts/score_gate4.py` scores it, and both have been driven end to end. The reason it
is open is that the 72 plates a reviewer has to look at live on the machine that built
them, and a reviewer who is not sitting at that machine cannot look at anything.

So this packs them. One zip, one sha256, one size, and a receipt that says what is
inside it, so the file can be handed to a reviewer over any channel and checked on
arrival against something published rather than against the word of whoever sent it.

**It verifies before it packs, and refuses rather than warns.** Every image on disk is
re-hashed and every commitment recomputed from the key, exactly as the scorer does it.
A bundle whose stimulus has drifted from `artifacts/GATE4_WORKSHEET.json` is not a
bundle worth transporting: it would produce a review that cannot be scored, after
somebody had already spent an hour on it.

**What it does not do is shrink the images.** 109 MB is what 72 full-resolution
waterfalls weigh, and every way of making that smaller changes what the reviewer sees.
Lossless re-encoding preserves the pixels and breaks the digests, which costs the
commitment for about a quarter of the bytes. Lossy re-encoding preserves the digests of
nothing and smooths exactly the faint traces the reviewer is being asked to judge, which
would answer the gate's question by degrading its stimulus. Downscaling is the same
objection with a different knob. The gate asks whether a person can decide from the
image, so the image is the one thing in this pipeline that does not get compressed.

    .venv/Scripts/python.exe scripts/pack_gate4_bundle.py
    .venv/Scripts/python.exe scripts/pack_gate4_bundle.py --bundle D:/tracetriage_gate4

The zip is written next to the bundle and never inside the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from score_gate4 import ScoringError, verify_commitments  # noqa: E402

MANIFEST = REPO / "artifacts" / "GATE4_WORKSHEET.json"
OUT = REPO / "artifacts" / "GATE4_BUNDLE.json"

#: The instrument, published where a reviewer can read it without the 113 MB of plates.
#: Copied by this script rather than by hand, because two copies of a review protocol
#: drift and the one a judge reads would be the stale one. The images are not copied:
#: they are the whole weight of the bundle, and a page of empty plates is a clearer
#: statement that they have to be asked for than a page carrying three of them.
PUBLISHED = REPO / "apps" / "web" / "public" / "gate4"

#: What travels. The key is not on this list and never will be: it holds the salt and the
#: item-to-observation mapping, and a reviewer who receives it is not blinded any more.
PACKED = ("review.html", "worksheet.md", "responses.csv")
IMAGES = "images"


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


#: Injected into the published copy of the review page and into nothing else. Opened from
#: the console, that copy has no images: they are the whole weight of the bundle. Without a
#: line saying so the page reads as broken, and a reader who thinks the instrument is broken
#: does not ask for the plates. The copy inside the bundle keeps the builder's bytes.
WEB_BANNER = """<p style="margin:0;padding:14px 20px;border-bottom:1px solid #313845;
  background:#141c2b;color:#c3c4c7;font-size:13px;line-height:1.65">
  <strong style="color:#f1f2f3">The plates are not on this copy of the page.</strong>
  This is the instrument, published so the protocol can be read before anyone spends half an
  hour on it. The {n_images} images are {mb} MB of full-resolution waterfalls and travel as
  one file, <code>{archive}</code>, sha256 <code>{digest}</code>: every way of shrinking them
  changes what a reviewer is being asked to judge. Ask for that file, unpack it, and open
  this page from the folder it makes. Everything here works except the pictures.
</p>"""


def _publish_review(
    source: pathlib.Path, archive: str, digest: str, n_images: int, image_bytes: int
) -> None:
    """Copy the review page to the console, with one banner the bundle's copy has not."""
    # Bytes in, bytes out. `read_text` normalises the bundle's line endings, so the
    # published file would differ from its source on every line and a one-paragraph
    # injection would read as a rewrite of the whole page.
    html = source.read_bytes().decode("utf-8")
    anchor = "</header>"
    if anchor not in html:
        raise SystemExit(
            f"{source} has no </header>, so the banner explaining the missing plates has "
            f"nowhere to go. Publishing the page without it would put a review instrument "
            f"on the web that reads as broken."
        )
    banner = WEB_BANNER.format(
        n_images=n_images,
        mb=f"{image_bytes / 1e6:.0f}",
        archive=archive,
        digest=digest[:24],
    )
    # The banner takes whatever line ending the file already uses, for the same reason.
    ending = "\r\n" if "\r\n" in html else "\n"
    injected = html.replace(anchor, anchor + ending + banner.replace("\n", ending), 1)
    (PUBLISHED / "review.html").write_bytes(injected.encode("utf-8"))


def pack(bundle: pathlib.Path, key: pathlib.Path) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not key.exists():
        raise SystemExit(
            f"no key at {key}. It is written outside the repository on purpose, so this "
            f"has to be told where it is with --key. Without it the commitments cannot "
            f"be recomputed and there is nothing to verify the bundle against."
        )
    key_data = json.loads(key.read_text(encoding="utf-8"))
    try:
        checked = verify_commitments(manifest, key_data, bundle / IMAGES)
    except ScoringError as error:
        raise SystemExit(
            f"the bundle does not match its commitment, so it is not packed: {error}"
        ) from error

    missing = [name for name in PACKED if not (bundle / name).exists()]
    if missing:
        raise SystemExit(
            f"{missing} are not in {bundle}. A reviewer needs the page, the protocol and "
            f"the empty response file, and a zip missing one of them is a zip that gets "
            f"three emails back."
        )

    archive = bundle.parent / "tracetriage_gate4_bundle.zip"
    # Stored rather than deflated for the images. They are PNGs, which are already
    # deflate streams, so compressing them again buys about a percent for minutes of
    # CPU. The three small text files are compressed, because they are text.
    with zipfile.ZipFile(archive, "w") as zf:
        for name in PACKED:
            zf.write(bundle / name, f"tracetriage_gate4/{name}", zipfile.ZIP_DEFLATED)
        for image in sorted((bundle / IMAGES).iterdir()):
            zf.write(image, f"tracetriage_gate4/{IMAGES}/{image.name}", zipfile.ZIP_STORED)

    images = sorted((bundle / IMAGES).iterdir())
    digest = _sha256(archive)
    PUBLISHED.mkdir(parents=True, exist_ok=True)
    (PUBLISHED / "worksheet.md").write_bytes((bundle / "worksheet.md").read_bytes())
    _publish_review(
        bundle / "review.html",
        archive.name,
        digest,
        len(images),
        sum(image.stat().st_size for image in images),
    )
    return {
        "schema": "tracetriage/gate4-bundle",
        "schema_version": "0.1.0",
        "unit": "the blinded gate 4 review bundle, as one file",
        "verified_against": "artifacts/GATE4_WORKSHEET.json",
        "commitments_checked": checked,
        "n_items": manifest["items"],
        "n_unique_observations": manifest["unique_observations"],
        "n_repeats": manifest["repeated_observations"],
        "source": manifest["source"],
        "archive": {
            "name": archive.name,
            "bytes": archive.stat().st_size,
            "sha256": digest,
            "n_entries": len(PACKED) + len(images),
        },
        "images": {
            "n": len(images),
            "bytes": sum(p.stat().st_size for p in images),
            "compression": "stored, not deflated: PNG is already a deflate stream",
        },
        "not_packed": {
            "key": (
                "the salt and the item-to-observation mapping. A reviewer who receives "
                "it is not blinded, and the scorer needs it on the machine that scores "
                "rather than on the machine that reviews."
            ),
        },
        "reading": (
            "One file, one digest. A reviewer checks what arrived against the sha256 "
            "above, opens review.html, answers 72 items and sends back one CSV. The "
            "verdict in artifacts/GATE4_RECEIPT.json stays NOT_RUN until that file "
            "exists, and no number in this repository moves before it does."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=pathlib.Path, default=pathlib.Path("D:/tracetriage_gate4"))
    parser.add_argument(
        "--key",
        type=pathlib.Path,
        default=None,
        help="the key file. Defaults to KEY_do_not_open_until_scored.json in the bundle.",
    )
    args = parser.parse_args(argv)
    bundle = args.bundle.resolve()
    key = args.key or bundle / "KEY_do_not_open_until_scored.json"
    receipt = pack(bundle, key)
    rendered = json.dumps(receipt, indent=1) + "\n"
    OUT.write_text(rendered, encoding="utf-8")
    # The same receipt, where the console can import it. The evaluation page prints
    # the size and the digest of the file a reviewer is asked for, and a page that
    # printed them from a different source than the packer would eventually print a
    # digest for an archive nobody has.
    (PUBLISHED / "BUNDLE.json").write_text(rendered, encoding="utf-8")
    print(
        f"{OUT.name} written: {receipt['commitments_checked']} commitments verified, "
        f"{receipt['archive']['name']} is {receipt['archive']['bytes']:,} bytes, "
        f"sha256 {receipt['archive']['sha256'][:16]}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
