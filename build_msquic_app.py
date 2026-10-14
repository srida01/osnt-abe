import argparse
from pathlib import Path

from common import ROOT, run


def build(source, library=None):
    source = Path(source).resolve()
    header = source / "src/inc/msquic.h"

    if not header.is_file():
        raise RuntimeError(f"Missing header: {header}")

    header_text = header.read_text()

    for field in [
        "SendCongestionWindow",
        "SendEcnCongestionCount",
        "EcnEnabled",
    ]:
        if field not in header_text:
            raise RuntimeError(f"MsQuic header lacks {field}")

    if library:
        lib = Path(library).resolve()
    else:
        candidates = [
            path
            for path in (source / "build").rglob("libmsquic.so*")
            if path.is_file()
        ]

        if not candidates:
            raise RuntimeError(
                "No libmsquic.so found under the MsQuic build folder. "
                "Locate your shared library and pass --library PATH."
            )

        candidates.sort(
            key=lambda path: (
                "Release" not in str(path),
                path.name != "libmsquic.so",
                str(path),
            )
        )

        lib = candidates[0].resolve()

    if not lib.is_file():
        raise RuntimeError(f"Library does not exist: {lib}")

    run([
        "cc",
        "-std=c11",
        "-O2",
        "-Wall",
        "-Wextra",
        "-pthread",
        "-I", header.parent,
        ROOT / "traffic.c",
        lib,
        "-Wl,-rpath," + str(lib.parent),
        "-o", ROOT / "msquic_traffic",
    ])

    dependencies = run(
        ["ldd", ROOT / "msquic_traffic"],
        capture_output=True,
        text=True,
    ).stdout

    if "not found" in dependencies:
        raise RuntimeError(dependencies)

    print(f"Traffic application built using {lib}", flush=True)
    return str(lib)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--msquic", required=True)
    parser.add_argument("--library")
    args = parser.parse_args()

    build(args.msquic, args.library)
