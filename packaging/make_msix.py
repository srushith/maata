"""Builds the Microsoft Store package (dist\\Maata-<version>.msix) from dist\\Maata.exe.

Run after `pyinstaller main.spec`:
    python packaging/make_msix.py

The Store signs the package itself, so this doesn't sign anything. Needs the
Windows 10/11 SDK (for makeappx.exe and makepri.exe) and PyQt5 (to draw the logos).
"""
import glob
import os
import shutil
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt5.QtCore import QRectF, Qt  # noqa: E402
from PyQt5.QtGui import QColor, QImage, QPainter  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from version import __version__  # noqa: E402
from widgets import draw_mic  # noqa: E402

# From Partner Center > Product management > Product identity.
IDENTITY_NAME = "SrushithKumar.Maata"
PUBLISHER = "CN=E8626EB8-8E93-4AC9-829E-9E4E3C843B2C"
PUBLISHER_DISPLAY_NAME = "Srushith Kumar"

BLUE = QColor("#2563EB")  # same blue as assets/icon.ico
DIST = os.path.join(ROOT, "dist")
LAYOUT = os.path.join(ROOT, "build", "msix")

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap rescap">
  <Identity Name="{name}" Publisher="{publisher}" Version="{version}" ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>Maata</DisplayName>
    <PublisherDisplayName>{publisher_display}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.26100.0" />
  </Dependencies>
  <Resources>
    <Resource Language="en-us" />
  </Resources>
  <Applications>
    <Application Id="Maata" Executable="Maata.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="Maata" Description="Talk instead of type in any Windows app."
        BackgroundColor="transparent"
        Square150x150Logo="Assets\\Square150x150Logo.png" Square44x44Logo="Assets\\Square44x44Logo.png">
        <uap:DefaultTile Wide310x150Logo="Assets\\Wide310x150Logo.png"
          Square71x71Logo="Assets\\Square71x71Logo.png" Square310x310Logo="Assets\\Square310x310Logo.png" />
      </uap:VisualElements>
    </Application>
  </Applications>
  <Capabilities>
    <rescap:Capability Name="runFullTrust" />
    <DeviceCapability Name="microphone" />
  </Capabilities>
</Package>
"""

# (file name, width, height, how much of the height the blue circle fills)
LOGOS = []
for scale in (100, 125, 150, 200, 400):
    s = scale / 100
    LOGOS += [
        (f"Square44x44Logo.scale-{scale}.png", round(44 * s), round(44 * s), 0.92),
        (f"Square150x150Logo.scale-{scale}.png", round(150 * s), round(150 * s), 0.6),
        (f"Wide310x150Logo.scale-{scale}.png", round(310 * s), round(150 * s), 0.6),
        (f"Square71x71Logo.scale-{scale}.png", round(71 * s), round(71 * s), 0.7),
        (f"Square310x310Logo.scale-{scale}.png", round(310 * s), round(310 * s), 0.5),
        (f"StoreLogo.scale-{scale}.png", round(50 * s), round(50 * s), 1.0),
    ]
# Taskbar and Start list icons, drawn without a coloured plate behind them.
for size in (16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 256):
    for form in ("", "_altform-unplated", "_altform-lightunplated"):
        LOGOS.append((f"Square44x44Logo.targetsize-{size}{form}.png", size, size, 0.92))


def draw_logo(path, width, height, fill):
    img = QImage(width, height, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    d = min(width, height) * fill
    cx, cy = width / 2, height / 2
    p.setPen(Qt.NoPen)
    p.setBrush(BLUE)
    p.drawEllipse(QRectF(cx - d / 2, cy - d / 2, d, d))
    # widgets.make_icon draws the mic at 44/60 of the circle, slightly above centre.
    draw_mic(p, cx, cy - d / 60, d * 44 / 60, QColor("white"))
    p.end()
    img.save(path)


def sdk_tool(name):
    found = shutil.which(name)
    if found:
        return found
    matches = sorted(glob.glob(
        rf"C:\Program Files (x86)\Windows Kits\10\bin\10.*\x64\{name}"))
    if not matches:
        sys.exit(f"{name} not found. Install the Windows SDK.")
    return matches[-1]


def run(*args):
    print(">", " ".join(args))
    subprocess.run(args, check=True)


def main():
    exe = os.path.join(DIST, "Maata.exe")
    if not os.path.exists(exe):
        sys.exit("dist\\Maata.exe not found. Run `pyinstaller main.spec` first.")

    shutil.rmtree(LAYOUT, ignore_errors=True)
    assets = os.path.join(LAYOUT, "Assets")
    os.makedirs(assets)
    shutil.copy2(exe, LAYOUT)

    app = QApplication.instance() or QApplication([])  # noqa: F841 (needed for QPainter)
    for name, w, h, fill in LOGOS:
        draw_logo(os.path.join(assets, name), w, h, fill)

    # The Store wants a.b.c.0 (the last number is reserved for the Store).
    version = ".".join((__version__.split(".") + ["0", "0"])[:3]) + ".0"
    with open(os.path.join(LAYOUT, "AppxManifest.xml"), "w", encoding="utf-8") as f:
        f.write(MANIFEST.format(name=IDENTITY_NAME, publisher=PUBLISHER,
                                publisher_display=PUBLISHER_DISPLAY_NAME, version=version))

    # resources.pri lets Windows pick the right logo size for each screen.
    pri_config = os.path.join(ROOT, "build", "priconfig.xml")
    run(sdk_tool("makepri.exe"), "createconfig", "/cf", pri_config,
        "/dq", "en-US", "/pv", "10.0.0", "/o")
    # Keep every logo size in one resources.pri. By default makepri splits them
    # per scale, which only works for multi-package bundles.
    with open(pri_config, encoding="utf-8") as f:
        config = f.read()
    start, end = config.find("<packaging>"), config.find("</packaging>")
    if start != -1 and end != -1:
        config = config[:start] + config[end + len("</packaging>"):]
    with open(pri_config, "w", encoding="utf-8") as f:
        f.write(config)
    run(sdk_tool("makepri.exe"), "new", "/pr", LAYOUT, "/cf", pri_config,
        "/mn", os.path.join(LAYOUT, "AppxManifest.xml"),
        "/of", os.path.join(LAYOUT, "resources.pri"), "/o")

    out = os.path.join(DIST, f"Maata-{__version__}.msix")
    run(sdk_tool("makeappx.exe"), "pack", "/d", LAYOUT, "/p", out, "/o")
    print(f"\nBuilt {out}")


if __name__ == "__main__":
    main()
