"""Stage public documentation and build/preview MkDocs without exposing local data.

The source allowlist is defined in public_sources(). Files under docs/ map to
the site root; other selected files map under project/. Links are rewritten
from their repository-relative targets to the corresponding staged paths.
No configuration, input dataset or generated reconstruction output is discovered
recursively outside the explicitly public examples. Engineering Markdown,
agent instructions and portable skills are deliberately absent from the site.

CLI: --strict enables MkDocs warning-as-error validation. --serve starts its
local development server instead of building. Neither option deploys anything.
--dev-addr optionally supplies a loopback/host TCP address to MkDocs serve; it
has no default here and is rejected without --serve. The convenience PowerShell
launcher owns its port default; otherwise MkDocs uses its normal serve default.
The work/docs-source directory is owned generated staging; all other paths are
read-only. mkdocs.yml owns theme, navigation and site output configuration.
LODEXT_DOCS_SITE_URL is the absolute published base URL, including a repository
subpath and trailing slash. It affects canonical/search URLs, not reconstruction.
The authoritative local-preview default is defined only in mkdocs.yml; the
Pages workflow supplies the hosted URL from repository metadata.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]  # Repository root; independent of caller cwd.
# Generated public-source staging, replaced only after exact resolved-path check.
# Not the repository docs/ directory; stage() must never delete source material.
STAGING = ROOT / "work" / "docs-source"
# Inline Markdown image/link matcher: groups are opening markup, URL, closing ).
# Intentionally not a general Markdown parser; stage() rejects unpublished local
# targets and preserves external URLs, query strings and fragments.
# In a linked image, the outer destination starts immediately after the image's ")".
LINK = re.compile(r"(!?\[[^\]\n]*\]\(|(?<=\))\]\()([^\s)]+)(\))")

# Editorial publication boundary, not a discovery pattern. These are user tasks
# and references only; adding docs/*.md never publishes it automatically. The
# navigation in mkdocs.yml orders these pages but cannot expand this allowlist.
USER_GUIDE_PAGES = (
    "index.md", "how_it_works.md", "manual.md", "capabilities.md",
    "installation.md", "first_run.md", "your_data.md", "examples.md", "parameter_examples.md", "las_canteras.md",
    "input_contract_v0_2.md", "input_strategy.md", "cli_reference.md",
    "outputs.md", "troubleshooting.md", "dtm_preparation.md", "cesium.md",
    "surface_workflow.md", "viewer_validation.md", "point_ground.md", "building_recovery.md", "roof_regions.md",
)


def public_sources() -> list[Path]:
    """User-guide pages, project licence and public example assets only.

    Example README files are repository fixture/provenance notes; the website's
    examples.md provides the user explanation and links to downloadable assets.
    Exclusion from navigation alone would still expose pages through search.
    """
    paths = [ROOT / "docs" / name for name in USER_GUIDE_PAGES]
    paths += [ROOT / "LICENSE"]
    paths += [p for p in (ROOT / "examples").rglob("*") if p.suffix.lower() != ".md"]
    return sorted({p for p in paths if p.is_file()})


def stage() -> None:
    """Replace owned staging with allowlisted public files and rewritten links.

    Flatten docs/ into the site source root and place other public material under
    project/. Reject local Markdown targets outside the publishable allowlist.
    Only STAGING is disposable; source files and ignored datasets are not copied
    indiscriminately or modified. No build/server/publication is started here.
    """
    sources = public_sources()
    destinations = {}
    for source in sources:
        relative = source.relative_to(ROOT)
        if relative.parts[0] == "docs":
            destination = Path(*relative.parts[1:])
        else:
            destination = Path("project") / relative
        destinations[source.resolve()] = destination
    # Resolve and verify the exact disposable path before recursive removal.
    if STAGING.resolve() != ROOT.resolve() / "work" / "docs-source":
        raise RuntimeError("Refusing to replace an unexpected documentation staging path")
    if STAGING.exists():
        shutil.rmtree(STAGING)
    STAGING.mkdir(parents=True)
    for source in sources:
        target_relative = destinations[source.resolve()]
        destination = STAGING / target_relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix != ".md":
            shutil.copy2(source, destination)
            continue

        def rewrite(match: re.Match[str]) -> str:
            value = match.group(2)
            parsed = urlsplit(value)
            if parsed.scheme or parsed.netloc or not parsed.path or value.startswith("/"):
                return match.group(0)
            resolved = (source.parent / unquote(parsed.path)).resolve()
            if resolved not in destinations:
                raise ValueError(f"Unpublished local documentation target in {source.name}: {value}")
            relative = posixpath.relpath(destinations[resolved].as_posix(),
                                         target_relative.parent.as_posix())
            rewritten = quote(relative, safe="/._-")
            if parsed.query:
                rewritten += "?" + parsed.query
            if parsed.fragment:
                rewritten += "#" + parsed.fragment
            return match.group(1) + rewritten + match.group(3)

        destination.write_text(LINK.sub(rewrite, source.read_text(encoding="utf-8")),
                               encoding="utf-8")
    print(f"Staged {len(sources)} public documentation/example files", flush=True)


def main() -> int:
    """Stage documentation and return the local MkDocs build/serve exit code.

    --strict treats warnings as errors; --dev-addr requires --serve. Neither
    path deploys the site or changes reconstruction configuration.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="Fail on MkDocs warnings")
    parser.add_argument("--serve", action="store_true", help="Preview locally; do not deploy")
    parser.add_argument("--dev-addr", help="Serve address HOST:PORT; requires --serve")
    args = parser.parse_args()
    if args.dev_addr is not None and not args.serve:
        parser.error("--dev-addr requires --serve")
    stage()
    command = [sys.executable, "-m", "mkdocs", "serve" if args.serve else "build",
               "--config-file", str(ROOT / "mkdocs.yml")]
    if args.strict:
        command.append("--strict")
    if args.dev_addr is not None:
        command.extend(["--dev-addr", args.dev_addr])
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
