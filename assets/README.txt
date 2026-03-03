Place app icons here before running electron-builder:

  icon.ico   — Windows (256x256 multi-resolution ICO)
  icon.icns  — macOS (512x512 ICNS)
  icon.png   — Linux (256x256 PNG)

Quick way to generate from a single PNG source:
  Windows: use https://icoconvert.com  (upload PNG, download ICO)
  macOS:   iconutil or https://cloudconvert.com/png-to-icns
  Linux:   just use the PNG directly (256x256 or larger)

electron-builder will use these automatically via the build config in package.json.
If no icons are provided, electron-builder uses a default Electron icon.
