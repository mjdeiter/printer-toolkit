# Printer Toolkit

A general-purpose CUPS/network printer troubleshooting GUI for Linux, built
with PyGObject (GTK 3). Modeled on
[HP_P1102w_Printer_Diagnostic_Tool](https://github.com/mjdeiter/printer_diagnostics),
but generalized: no single printer is hardcoded, and it adds LAN discovery.

## Why This Exists

`HP_P1102w_Printer_Diagnostic_Tool` (C++/gtkmm) is a deep diagnostic tool
built around one specific printer at a fixed IP. This tool covers the other
case: a general CUPS printer manager for a machine where the printer(s) on
the network aren't fixed in advance — scan the LAN, add or remove a queue,
audit every queue for problems, not just one.

## Features

- Full diagnostic scan (ping, port checks, CUPS status, stuck jobs)
- Scan the local subnet for JetDirect/IPP/LPD printers (nmap/avahi-browse if
  available, manual sweep as a fallback)
- List configured CUPS printers and show the print queue
- Detect duplicate CUPS queues pointing at the same device, and audit device
  URIs across all queues
- Clear stuck jobs, restart the CUPS service
- Add or remove a network printer by URI
- Test a specific host/port connection
- View the CUPS error log
- Output pane with Select All / Copy / Clear controls
- About dialog with version info and an in-app changelog

## Requirements

- `python3-gi` (PyGObject, GTK 3)
- CUPS client tools: `lpstat`, `lpadmin`, `cancel`, `lpinfo`
- Optional: `nmap` or `avahi-browse` for network scanning (falls back to a
  manual subnet sweep if neither is present)

## Deployment

Deployed to `/home/meridith/Scripts/printer_toolkit.py` on Meridith's Surface
(Devuan/XFCE), launched via `/home/meridith/Desktop/printer-toolkit.desktop`.

## Design Notes

Every version bump gets a line in the `CHANGELOG` list at the top of the
script (shown in the About dialog's Changelog viewer) — keep that habit
going with future changes.
