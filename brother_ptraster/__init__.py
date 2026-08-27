"""Brother P-touch raster protocol encoder for the PT-P710BT label printer.

This package implements the "raster mode" command set that Brother uses
across its thermal label printers (QL and PT series share the same wire
protocol, only the print-head width, DPI and media tables differ). It is a
clean-room implementation based on Brother's publicly documented Raster
Command Reference and on the byte-level behaviour that is consistent across
the many open-source drivers for this printer family.

It has NOT been validated against a physical PT-P710BT in this environment.
Before relying on it for real prints, run the unit tests, then do a supervised
test print (see README.md) and compare against Brother's official reference
if anything looks off.
"""

from .protocol import RasterJobBuilder
from .media import MediaSpec, MEDIA_TABLE, get_media

__all__ = ["RasterJobBuilder", "MediaSpec", "MEDIA_TABLE", "get_media"]
