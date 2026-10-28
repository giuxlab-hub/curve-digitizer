# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import math
import uuid
import numpy as np

CORNER_ORDER = ("bottom_left", "bottom_right", "top_left", "top_right")
CORNER_DESTINATIONS = {
    "bottom_left": (0.0, 0.0),
    "bottom_right": (1.0, 0.0),
    "top_left": (0.0, 1.0),
    "top_right": (1.0, 1.0),
}


class CalibrationError(ValueError):
    pass


@dataclass
class AxisConfig:
    name: str = "X"
    unit: str = ""
    minimum: float = 0.0
    maximum: float = 1.0
    scale: str = "linear"

    def validate(self) -> None:
        if self.scale not in ("linear", "log"):
            raise CalibrationError(f"Invalid scale type: {self.scale!r}")
        if not math.isfinite(self.minimum) or not math.isfinite(self.maximum):
            raise CalibrationError("Axis limits must be finite.")
        if self.minimum == self.maximum:
            raise CalibrationError("Axis minimum and maximum must be different.")
        if self.scale == "log" and (self.minimum <= 0 or self.maximum <= 0):
            raise CalibrationError("Logarithmic axes require positive limits.")

    def from_unit(self, t: float) -> float:
        self.validate()
        if self.scale == "linear":
            return self.minimum + t * (self.maximum - self.minimum)
        lo = math.log10(self.minimum)
        hi = math.log10(self.maximum)
        return 10.0 ** (lo + t * (hi - lo))

    def to_unit(self, value: float) -> float:
        self.validate()
        if self.scale == "linear":
            return (value - self.minimum) / (self.maximum - self.minimum)
        if value <= 0:
            raise CalibrationError("Logarithmic axis values must be positive.")
        lo = math.log10(self.minimum)
        hi = math.log10(self.maximum)
        return (math.log10(value) - lo) / (hi - lo)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "scale": self.scale,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AxisConfig":
        return cls(
            name=str(data.get("name", "X")),
            unit=str(data.get("unit", "")),
            minimum=float(data.get("minimum", 0.0)),
            maximum=float(data.get("maximum", 1.0)),
            scale=str(data.get("scale", "linear")),
        )


@dataclass
class Calibration:
    """Four point projective calibration (homography)."""
    pixels: dict[str, tuple[float, float]] = field(default_factory=dict)

    def is_complete(self) -> bool:
        return all(key in self.pixels for key in CORNER_ORDER)

    def clear(self) -> None:
        self.pixels.clear()

    def set_corner(self, name: str, pixel_x: float, pixel_y: float) -> None:
        if name not in CORNER_ORDER:
            raise CalibrationError(f"Unknown calibration corner: {name}")
        self.pixels[name] = (float(pixel_x), float(pixel_y))

    def matrix(self) -> tuple[np.ndarray, float]:
        if not self.is_complete():
            raise CalibrationError("All four calibration points are required.")
        src = np.asarray([self.pixels[n] for n in CORNER_ORDER], dtype=float)
        dst = np.asarray([CORNER_DESTINATIONS[n] for n in CORNER_ORDER], dtype=float)
        rows, rhs = [], []
        # h33 is fixed to 1. Eight correspondences equations solve the eight
        # remaining coefficients of the homography.
        for (x, y), (u, v) in zip(src, dst):
            rows.append([x, y, 1, 0, 0, 0, -u*x, -u*y]); rhs.append(u)
            rows.append([0, 0, 0, x, y, 1, -v*x, -v*y]); rhs.append(v)
        a = np.asarray(rows, dtype=float)
        b = np.asarray(rhs, dtype=float)
        if np.linalg.matrix_rank(a) < 8:
            raise CalibrationError("Degenerate calibration points.")
        cond = float(np.linalg.cond(a))
        try:
            h = np.linalg.solve(a, b)
        except np.linalg.LinAlgError as exc:
            raise CalibrationError("Unable to calculate homography.") from exc
        H = np.asarray([
            [h[0], h[1], h[2]],
            [h[3], h[4], h[5]],
            [h[6], h[7], 1.0],
        ], dtype=float)
        return H, cond

    @staticmethod
    def transform_with_matrix(H: np.ndarray, pixel_x: float, pixel_y: float) -> tuple[float, float]:
        p = H @ np.asarray([pixel_x, pixel_y, 1.0], dtype=float)
        if abs(p[2]) < 1e-15:
            raise CalibrationError("Projective transform is singular here.")
        return float(p[0] / p[2]), float(p[1] / p[2])

    def pixel_to_unit(self, pixel_x: float, pixel_y: float) -> tuple[float, float]:
        H, _ = self.matrix()
        return self.transform_with_matrix(H, pixel_x, pixel_y)

    def reprojection_rms(self) -> float:
        H, _ = self.matrix()
        errors = []
        for name in CORNER_ORDER:
            x, y = self.pixels[name]
            eu, ev = CORNER_DESTINATIONS[name]
            u, v = self.transform_with_matrix(H, x, y)
            errors.append((u-eu)**2 + (v-ev)**2)
        return math.sqrt(sum(errors) / len(errors))

    def to_dict(self) -> dict[str, Any]:
        return {"points": {n: {"pixel_x": p[0], "pixel_y": p[1]} for n, p in self.pixels.items()}}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Calibration":
        c = cls()
        for name, p in data.get("points", {}).items():
            if name in CORNER_ORDER:
                c.set_corner(name, float(p["pixel_x"]), float(p["pixel_y"]))
        return c


@dataclass
class DigitizedPoint:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    manual_pixel_x: float = 0.0
    manual_pixel_y: float = 0.0
    pixel_x: float = 0.0
    pixel_y: float = 0.0
    calibrated_x: float | None = None
    calibrated_y: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "manual_click_pixel": {"x": self.manual_pixel_x, "y": self.manual_pixel_y},
            "pixel": {"x": self.pixel_x, "y": self.pixel_y},
            "calibrated": {"x": self.calibrated_x, "y": self.calibrated_y},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DigitizedPoint":
        pixel = data.get("pixel", {})
        manual = data.get("manual_click_pixel", pixel)
        calibrated = data.get("calibrated", {})
        return cls(
            id=str(data.get("id", str(uuid.uuid4()))),
            manual_pixel_x=float(manual.get("x", pixel.get("x", 0.0))),
            manual_pixel_y=float(manual.get("y", pixel.get("y", 0.0))),
            pixel_x=float(pixel.get("x", 0.0)),
            pixel_y=float(pixel.get("y", 0.0)),
            calibrated_x=None if calibrated.get("x") is None else float(calibrated["x"]),
            calibrated_y=None if calibrated.get("y") is None else float(calibrated["y"]),
        )


@dataclass
class Series:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Series"
    parameter_name: str = "Parameter"
    parameter_value: str = ""
    parameter_unit: str = ""
    visible: bool = True
    color: str = "#d62728"
    points: list[DigitizedPoint] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "parameter": {"name": self.parameter_name, "value": self.parameter_value, "unit": self.parameter_unit},
            "visible": self.visible,
            "color": self.color,
            "points": [p.to_dict() for p in self.points],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Series":
        p = data.get("parameter", {})
        return cls(
            id=str(data.get("id", str(uuid.uuid4()))),
            name=str(data.get("name", "Series")),
            parameter_name=str(p.get("name", "Parameter")),
            parameter_value=str(p.get("value", "")),
            parameter_unit=str(p.get("unit", "")),
            visible=bool(data.get("visible", True)),
            color=str(data.get("color", "#d62728")),
            points=[DigitizedPoint.from_dict(x) for x in data.get("points", [])],
        )


@dataclass
class Project:
    format_version: str = "1.0"
    image_path: str = ""
    image_width: int = 0
    image_height: int = 0
    x_axis: AxisConfig = field(default_factory=lambda: AxisConfig(name="X"))
    y_axis: AxisConfig = field(default_factory=lambda: AxisConfig(name="Y"))
    calibration: Calibration = field(default_factory=Calibration)
    series: list[Series] = field(default_factory=list)
    notes: str = ""
    show_point_numbers: bool = False
    snap_enabled: bool = False
    snap_radius: int = 3

    def calibration_ready(self) -> bool:
        if not self.calibration.is_complete():
            return False
        try:
            self.x_axis.validate(); self.y_axis.validate(); self.calibration.matrix()
        except CalibrationError:
            return False
        return True

    def pixel_to_calibrated(self, pixel_x: float, pixel_y: float) -> tuple[float, float]:
        u, v = self.calibration.pixel_to_unit(pixel_x, pixel_y)
        return self.x_axis.from_unit(u), self.y_axis.from_unit(v)

    def update_point_calibration(self, point: DigitizedPoint) -> None:
        try:
            point.calibrated_x, point.calibrated_y = self.pixel_to_calibrated(point.pixel_x, point.pixel_y)
        except CalibrationError:
            point.calibrated_x = point.calibrated_y = None

    def recalculate_all_points(self) -> None:
        for s in self.series:
            for p in s.points:
                self.update_point_calibration(p)

    def find_series(self, series_id: str | None) -> Series | None:
        return next((s for s in self.series if s.id == series_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "giux-curve-digitizer-project",
            "version": self.format_version,
            "image": {"path": self.image_path, "width": self.image_width, "height": self.image_height},
            "axes": {"x": self.x_axis.to_dict(), "y": self.y_axis.to_dict()},
            "calibration": self.calibration.to_dict(),
            "series": [s.to_dict() for s in self.series],
            "notes": self.notes,
            "display": {"show_point_numbers": self.show_point_numbers},
            "snap": {"enabled": self.snap_enabled, "radius": self.snap_radius},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        image, axes = data.get("image", {}), data.get("axes", {})
        display, snap = data.get("display", {}), data.get("snap", {})
        return cls(
            format_version=str(data.get("version", "1.0")),
            image_path=str(image.get("path", "")),
            image_width=int(image.get("width", 0)),
            image_height=int(image.get("height", 0)),
            x_axis=AxisConfig.from_dict(axes.get("x", {})),
            y_axis=AxisConfig.from_dict(axes.get("y", {})),
            calibration=Calibration.from_dict(data.get("calibration", {})),
            series=[Series.from_dict(s) for s in data.get("series", [])],
            notes=str(data.get("notes", "")),
            show_point_numbers=bool(display.get("show_point_numbers", False)),
            snap_enabled=bool(snap.get("enabled", False)),
            snap_radius=max(0, int(snap.get("radius", 3))),
        )
