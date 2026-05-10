import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path


# Build a standalone executable:
#   python build.py
#
# Edit the variables in the __main__ block below directly.


def parse_version_tuple(version):
    parts = version.split(".") if version else ["0"]
    numbers = []
    for part in parts[:4]:
        numbers.append(int(part) if part.isdigit() else 0)
    while len(numbers) < 4:
        numbers.append(0)
    return tuple(numbers)


def read_project_metadata(project_dir):
    pyproject_path = project_dir / "pyproject.toml"
    if not pyproject_path.exists():
        return {}
    with pyproject_path.open("rb") as f:
        return tomllib.load(f).get("project", {})


def write_windows_version_file(
    build_dir,
    app_name,
    app_version,
    company_name,
    description,
    product_name,
    copyright_text,
):
    if not app_version:
        return None

    version_tuple = parse_version_tuple(app_version)
    version_file = build_dir / "version_info.txt"
    build_dir.mkdir(exist_ok=True)
    version_file.write_text(
        f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple},
    prodvers={version_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', {company_name!r}),
          StringStruct('FileDescription', {description!r}),
          StringStruct('FileVersion', {app_version!r}),
          StringStruct('InternalName', {app_name!r}),
          StringStruct('OriginalFilename', {app_name + '.exe'!r}),
          StringStruct('ProductName', {product_name!r}),
          StringStruct('ProductVersion', {app_version!r}),
          StringStruct('LegalCopyright', {copyright_text!r}),
        ],
      ),
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
""",
        encoding="utf-8",
    )
    return version_file


if __name__ == "__main__":
    # Basic paths
    project_dir = Path(__file__).resolve().parent
    entry_file = project_dir / "cc-model-switch.py"
    dist_dir = project_dir / "dist"
    build_dir = project_dir / "build"
    project_metadata = read_project_metadata(project_dir)

    # Build metadata. Edit these directly.
    app_name = project_metadata.get("name", "cc-model-switch")
    app_version = project_metadata.get("version", "")
    output_name = f"{app_name}-{app_version}" if app_version else app_name
    app_icon = "icon.ico"
    company_name = "CLN-Grated"
    description = project_metadata.get("description", "Claude Code model switcher")
    product_name = app_name
    copyright_text = "(C) 2026 Ad_closeNN."

    if importlib.util.find_spec("PyInstaller") is None:
        print("缺少 PyInstaller。先安装:")
        print(f"  {sys.executable} -m pip install PyInstaller")
        sys.exit(1)

    pyinstaller_options = [
        "--onefile",
        "--clean",
        "--noupx",
        "--name",
        output_name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir),
        "--specpath",
        str(build_dir),
    ]

    if app_icon:
        icon_path = Path(app_icon)
        if not icon_path.is_absolute():
            icon_path = project_dir / icon_path
        if not icon_path.exists():
            print(f"图标文件不存在: {icon_path}")
            sys.exit(1)
        pyinstaller_options.extend(["--icon", str(icon_path)])

    version_file = write_windows_version_file(
        build_dir,
        app_name,
        app_version,
        company_name,
        description,
        product_name,
        copyright_text,
    )
    if version_file is not None:
        pyinstaller_options.extend(["--version-file", str(version_file)])

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        *pyinstaller_options,
        str(entry_file),
    ]

    output_file = dist_dir / f"{output_name}.exe"
    print("构建信息:")
    print(f"  app_name: {app_name}")
    print(f"  app_version: {app_version or '-'}")
    print(f"  output_name: {output_name}")
    print(f"  app_icon: {app_icon or '-'}")
    print(f"  company_name: {company_name or '-'}")
    print(f"  description: {description or '-'}")
    print(f"  product_name: {product_name or '-'}")
    print(f"  copyright_text: {copyright_text or '-'}")
    print(f"  entry_file: {entry_file}")
    print(f"  output_file: {output_file}")
    print()

    print("开始构建:")
    print("  " + " ".join(command))
    subprocess.run(command, cwd=project_dir, check=True)

    print("\n构建完成:")
    print(f"  {output_file}")
