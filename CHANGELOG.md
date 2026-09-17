# Changelog

## v1.7 - 2026-09-17
### Fixed
- `Gtk.ResponseType.YeS` typo made the **Yes** button on the Clear Stuck Jobs
  confirmation raise an `AttributeError` instead of cancelling jobs, so
  clearing a stuck queue from the GUI silently did nothing.

## v1.6 - 2026-09-17
### Fixed
- Add Network Printer built `socket://{ip}:99100` (stray extra digit, plus a
  stray `+` before the dict key) instead of port 9100, so adding a
  raw/JetDirect printer was broken.

## v1.5 - 2026-09-17
### Added
- Network scan now reports MAC addresses: the nmap path runs `sudo -n` so it
  ARP-scans the subnet, and the manual-sweep fallback resolves each host's MAC
  via `ip neigh`/`arp`. Replaces the standalone `find-printers.sh` on the
  Surface, which duplicated this scan.

## v1.4 - 2026-09-17
### Fixed
- Published to this repo. The About dialog's Source link previously pointed
  at `HP_P1102w_Printer_Diagnostic_Tool`'s repo (an unrelated C++ project) —
  it now points here.

## v1.3
### Added
- Select All / Copy / Clear buttons above the output pane.
- Changelog viewer inside the About dialog.

## v1.2
### Fixed
- Default window size now scales to ~65% of the monitor's available work
  area (capped at the original 760x560) instead of a fixed size, fixing an
  oversized window on high-DPI/small displays like the Surface's.
### Changed
- About dialog credits the full author name and links to a personal site.

## v1.1
- Version bump prior to changelog tracking; history not recorded.

## v1.0
- Initial release: CUPS/network printer diagnostics, network scan, queue
  management, add/remove printers, CUPS log viewer.
