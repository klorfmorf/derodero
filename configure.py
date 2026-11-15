#!/usr/bin/env python3

from __future__ import annotations

import argparse
import platform
import shutil
import sys
from pathlib import Path

import ninja_syntax
import requests
import splat
from splat.scripts import split
from splat.segtypes.linker_entry import LinkerEntry

BASENAME = "derodero"
YAML_FILE = Path("splat.yaml")

ROOT_DIR = Path(__file__).resolve().parent
TOOLS_DIR = ROOT_DIR / "tools"
BUILD_DIR = ROOT_DIR / "build"

TARGET_ROM = ROOT_DIR / f"{BASENAME}.z64"
LD_PATH = ROOT_DIR / f"{BASENAME}.ld"
MAP_PATH = BUILD_DIR / f"{BASENAME}.map"
ELF_PATH = BUILD_DIR / f"{BASENAME}.elf"
Z64_PATH = BUILD_DIR / f"{BASENAME}.z64"
OK_PATH = BUILD_DIR / f"{BASENAME}.ok"
CHECKSUM_PATH = ROOT_DIR / "checksum.sha1"

CROSS = "mips64-linux-gnu-"
CROSS_AS = f"{CROSS}as"
CROSS_CPP = shutil.which(f"{CROSS}cpp") or shutil.which("cpp") or f"{CROSS}cpp"
CROSS_LD = f"{CROSS}ld"
CROSS_OBJCOPY = f"{CROSS}objcopy"
ICONV = shutil.which("iconv") or "iconv"

IDO_VERSION = "5.3"
IDO_DIR = TOOLS_DIR / f"ido-{IDO_VERSION}-recomp"
IDO_CC = IDO_DIR / "cc"

ASM_PROCESSOR_DIR = TOOLS_DIR / "asm-processor"
ASM_PROCESSOR = ASM_PROCESSOR_DIR / "asm-processor"

COMMON_INCLUDES = "-I include -I src -I build/include -I build -I ."
C_DEFS = "-D_LANGUAGE_C -DNDEBUG -D_FINALROM"
AS_FLAGS = f"-G 0 {COMMON_INCLUDES} -EB -mtune=vr4300 -march=vr4300 -mabi=32"
C_FLAGS = f"-G 0 -non_shared -fullwarn -verbose -Xcpluscomm -nostdinc -mips2 -O2 {COMMON_INCLUDES} {C_DEFS}"

GAME_CC_CMD = (
    f"{ASM_PROCESSOR} {IDO_CC} -- {CROSS_AS} {AS_FLAGS} -- "
    f"{C_FLAGS} $flags -c -o $out $in"
)

def get_platform_target() -> tuple[str, str]:
    system = sys.platform
    machine = platform.machine().lower()

    if system.startswith("linux"):
        os_name = "linux"
    elif system == "darwin":
        os_name = "macos"
    elif system in ("win32", "cygwin"):
        os_name = "windows"
    else:
        print(f"Error: Unsupported operating system '{system}'", file=sys.stderr)
        sys.exit(1)

    arch_name = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    return os_name, arch_name

def download_and_extract_archive(url: str, dest_dir: Path, flatten_single_dir: bool = False) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    archive_name = url.split("/")[-1]
    temp_archive = dest_dir / archive_name

    print(f"Downloading: {url}")
    try:
        with requests.get(url, stream=True, timeout=30) as response:
            response.raise_for_status()
            with open(temp_archive, "wb") as f:
                f.writelines(response.iter_content(chunk_size=16384))
    except requests.RequestException as e:
        print(f"Error downloading {url}: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Extracting to: {dest_dir}")
    shutil.unpack_archive(temp_archive, dest_dir)
    temp_archive.unlink(missing_ok=True)

    if flatten_single_dir:
        subdirs = [p for p in dest_dir.iterdir() if p.is_dir()]
        if len(subdirs) == 1:
            top_dir = subdirs[0]
            for item in top_dir.iterdir():
                item.rename(dest_dir / item.name)
            top_dir.rmdir()

def setup_toolchain() -> None:
    os_name, arch_name = get_platform_target()

    if IDO_DIR.exists():
        shutil.rmtree(IDO_DIR)

    ido_tag = "v1.2"
    ido_tar = f"ido-{IDO_VERSION}-recomp-{os_name}.tar.gz"
    ido_url = f"https://github.com/decompals/ido-static-recomp/releases/download/{ido_tag}/{ido_tar}"
    download_and_extract_archive(ido_url, IDO_DIR)

    if ASM_PROCESSOR_DIR.exists():
        shutil.rmtree(ASM_PROCESSOR_DIR)

    if os_name == "macos":
        target_triple = f"{arch_name}-apple-darwin"
    elif os_name == "linux":
        target_triple = f"{arch_name}-unknown-linux-gnu"
    else:
        target_triple = "x86_64-pc-windows-msvc"

    asm_proc_tag = "1.0.1"
    asm_proc_tar = f"asm-processor-{target_triple}.tar.xz"
    asm_proc_url = f"https://github.com/simonlindholm/asm-processor/releases/download/{asm_proc_tag}/{asm_proc_tar}"
    download_and_extract_archive(asm_proc_url, ASM_PROCESSOR_DIR, flatten_single_dir=True)

    print("Toolchain setup complete.")

def clean_project() -> None:
    artifacts: list[Path] = [
        ROOT_DIR / ".splache",
        ROOT_DIR / ".splat",
        ROOT_DIR / "asm",
        ROOT_DIR / "assets",
        BUILD_DIR,
        ROOT_DIR / "build.ninja",
    ]
    for path in artifacts:
        if path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    print("Project artifacts cleaned.")

def write_permuter_settings() -> None:
    settings_path = ROOT_DIR / "permuter_settings.toml"
    content = f"""build_system = "ninja"
compiler_type = "ido"

[preserve_macros]
"g[DS]P.*" = "void"
"gs[DS]P.*" = "void"
"G_IM_SIZ_.*" = "int"
"G_[AC]C.*" = "int"
ABS = "int"
ARRAY_COUNT = "int"
CLAMP = "int"
NULL = "int"

[decompme.compilers]
"{IDO_CC}" = "ido{IDO_VERSION}"
"""
    settings_path.write_text(content, encoding="utf-8")

def create_build_script(linker_entries: list[LinkerEntry]) -> None:
    built_objects: set[str] = set()
    ninja_file = ROOT_DIR / "build.ninja"

    with open(ninja_file, "w", encoding="utf-8") as f:
        ninja = ninja_syntax.Writer(f, width=9999)

        ninja.rule(
            "bin",
            description="bin $in",
            command=f"{CROSS_LD} -r -b binary $in -o $out",
        )
        ninja.rule(
            "as",
            description="as $in",
            command=f"{CROSS_CPP} {COMMON_INCLUDES} $in -o - | {CROSS_AS} {AS_FLAGS} -o $out",
        )
        ninja.rule(
            "as_rodata",
            description="as (euc-jp) $in",
            command=f"{CROSS_CPP} {COMMON_INCLUDES} $in -o - | {ICONV} -f UTF-8 -t EUC-JP | {CROSS_AS} {AS_FLAGS} -o $out",
        )
        ninja.rule(
            "cc",
            description="cc $in",
            command=GAME_CC_CMD,
        )
        ninja.rule(
            "ld",
            description="link $out",
            command=f"{CROSS_LD} -m elf32btsmip -T undefined_syms.txt -T undefined_syms_auto.txt -Map $mapfile -T $in -o $out",
        )
        ninja.rule(
            "z64",
            description="rom $out",
            command=f"{CROSS_OBJCOPY} $in $out -O binary",
        )
        ninja.rule(
            "sha1sum",
            description="sha1sum $in",
            command="sha1sum -c $in && touch $out",
        )

        def add_build_entry(
            outputs: Path | list[Path],
            inputs: list[Path],
            rule: str,
            variables: dict[str, str] | None = None,
        ) -> None:
            out_list = [outputs] if isinstance(outputs, Path) else outputs
            for out_path in out_list:
                if out_path.suffix == ".o":
                    built_objects.add(str(out_path))

            ninja.build(
                outputs=[str(p) for p in out_list],
                rule=rule,
                inputs=[str(p) for p in inputs],
                variables=variables,
            )

        for entry in linker_entries:
            seg = entry.segment
            if entry.object_path is None or seg.type.startswith("."):
                continue

            if any(str(p).endswith(".rodata.s") for p in entry.src_paths) or seg.type == "rodata":
                add_build_entry(entry.object_path, entry.src_paths, "as_rodata")

            elif isinstance(seg, (splat.segtypes.n64.header.N64SegHeader,
                                splat.segtypes.common.asm.CommonSegAsm,
                                splat.segtypes.common.data.CommonSegData)):
                add_build_entry(entry.object_path, entry.src_paths, "as")

            elif isinstance(seg, splat.segtypes.common.c.CommonSegC):
                add_build_entry(entry.object_path, entry.src_paths, "cc")

            elif isinstance(seg, splat.segtypes.common.bin.CommonSegBin):
                add_build_entry(entry.object_path, entry.src_paths, "bin")

            else:
                print(f"Warning: Segment type '{seg.type}' is unhandled, building as raw binary.")
                add_build_entry(entry.object_path, entry.src_paths, "bin")

        ninja.build(
            str(ELF_PATH),
            "ld",
            str(LD_PATH),
            implicit=sorted(built_objects),
            variables={"mapfile": str(MAP_PATH)},
        )
        ninja.build(
            str(Z64_PATH),
            "z64",
            str(ELF_PATH),
        )
        ninja.build(
            str(OK_PATH),
            "sha1sum",
            str(CHECKSUM_PATH),
            implicit=[str(Z64_PATH)],
        )
        ninja.default(str(OK_PATH))

def main() -> None:
    parser = argparse.ArgumentParser(description="Configure project build system")
    parser.add_argument(
        "-c", "--clean",
        help="Clean extraction artifacts and build outputs",
        action="store_true",
    )
    parser.add_argument(
        "-s", "--setup",
        help="Download and configure compilers and toolchain prerequisites",
        action="store_true",
    )
    parser.add_argument(
        "-d", "--disassemble-all",
        help="Force Splat to disassemble all code",
        action="store_true",
    )
    args = parser.parse_args()

    if args.clean:
        clean_project()

    if args.setup:
        setup_toolchain()
        return

    if not TARGET_ROM.exists():
        print(f"Error: Target ROM '{TARGET_ROM.name}' is missing from project root.", file=sys.stderr)
        sys.exit(1)

    print(f"Splitting ROM using {YAML_FILE}...")
    split.main(
        [YAML_FILE],
        modes=["all"],
        verbose=False,
        disassemble_all=args.disassemble_all,
    )

    print("Generating build.ninja...")
    linker_entries: list[LinkerEntry] = split.linker_writer.entries
    create_build_script(linker_entries)

    write_permuter_settings()
    print("Configuration complete. Run 'ninja' to build.")

if __name__ == "__main__":
    main()