# Curve Digitizer

**A standalone, open-source desktop tool for manually extracting numerical data from plotted curves and old datasheets.**

[Official website and software page](https://giux-lab.it/software/curve-digitizer/) ·
[English documentation](https://giux-lab.it/en/programs/curve-digitizer/) ·
[Italian source-package README](README.it.md)

**Current published package:** 0.4.7 · **License:** GPL-3.0-or-later · **Platforms:** Linux and Windows

Curve Digitizer is a compact **Python 3 / Tkinter** desktop application designed to turn raster graph traces into reproducible numerical data. Its original use case is the digitization of families of vacuum-tube characteristic curves for later fitting and SPICE-model preparation. It also works with transistors, diodes, sensors and other plotted measurements.

## Features

- Import PNG, JPEG and TIFF graph images without modifying the originals.
- Pan, zoom, fit the image to the window and inspect source-image pixel coordinates.
- Calibrate the graph with **four reference points and a projective homography** to account for rotated or moderately perspective-skewed scans.
- Configure X and Y axes, units, ranges, and linear or logarithmic scales.
- Define multiple series; each series has a name and a parameter with its own value and unit.
- Add, move and delete curve points, with undo and redo.
- Optionally snap to the darkest pixel in a local neighborhood while **preserving the original manual click separately**.
- Save/reopen UTF-8 JSON projects, including calibration, series, point coordinates and notes.
- Export calibrated points to CSV with configurable headers and explicit series parameters.
- Verify calibration against selected known coordinates.

The original image is never overwritten. The tool intentionally does **not** provide OCR, automatic curve tracing, smoothing, interpolation, fitting, automatic unit conversions, or SPICE-model generation.

## Installation

Requires **Python 3.10+**, Tkinter/Tcl-Tk, [Pillow](https://pillow.readthedocs.io/) and [NumPy](https://numpy.org/).

On Debian/Ubuntu, install Tkinter if necessary:

```bash
sudo apt install python3-tk
```

An optional virtual environment for the two Python dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

On Windows, use an installed Python 3 interpreter that includes Tkinter, then install the dependencies from `requirements.txt`.

## Run

```bash
python3 curve_digitizer.py
```

Run the command from the folder containing all three Python files.

## Quick start

1. **Open an image** of the graph to be digitized.
2. Configure the X/Y axes, minima, maxima, units and linear/log scales.
3. Mark calibration corners in this order: **bottom-left, bottom-right, top-left, top-right**.
4. Use **Verify calibration** on a known graph point when appropriate.
5. Create a named curve series, including the associated parameter (for example grid voltage `Vg = -20 V`).
6. Add the required points; adjust them individually and use optional snapping as needed.
7. Save the project as JSON and export the calibrated data as CSV.

Example CSV layout for a tube characteristic family:

```csv
Va_V,Vg_V,Ia_mA
100,-20,12.3
120,-20,18.1
```

Export preserves the order of the entered points. Units are labels, not automatic numerical conversions.

## Source files

| File | Purpose |
|---|---|
| `curve_digitizer.py` | Tkinter desktop GUI, workflow, project commands and CSV export |
| `digitizer_model.py` | Scientific data model, axes, calibration/homography and JSON |
| `image_canvas.py` | Image Canvas, zoom/pan and image↔Canvas coordinates |
| `requirements.txt` | Pillow and NumPy dependencies |
| `README.it.md` | README from the original Giux-Lab source ZIP |
| `LICENSE` and `COPYING` | GPL-3.0-or-later notice and complete GPLv3 text |

## Full documentation

The authoritative documentation is maintained on **Giux-Lab**:

- [Italian software page and download](https://giux-lab.it/software/curve-digitizer/)
- [English introduction and manual](https://giux-lab.it/en/programs/curve-digitizer/)
- [Installation and interface](https://giux-lab.it/en/programs/curve-digitizer/install-and-interface/)
- [Saving JSON projects and exporting CSV](https://giux-lab.it/en/programs/curve-digitizer/save-and-export-csv/)

No separate GitHub Pages site is maintained for this repository.

## Origin and licensing

Source published by **Giux-Lab**, version **0.4.7**, from the [original downloadable ZIP](https://giux-lab.it/wp-content/uploads/2026/09/curve_digitizer.zip).

The three Python modules, dependencies and original license notice are imported unchanged from the distributed ZIP. The original Italian README is preserved as `README.it.md`; this English landing page, `COPYING`, and repository metadata are added for GitHub.

Released under the **GNU General Public License, version 3 or later** (GPL-3.0-or-later). See [LICENSE](LICENSE) and [COPYING](COPYING).

*Curve Digitizer is a standalone application and does not require the GX-TXT framework.*
