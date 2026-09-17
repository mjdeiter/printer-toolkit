#!/usr/bin/env python3
"""
Printer Toolkit — Meridith's Surface (Devuan/XFCE)

General-purpose CUPS/network printer troubleshooting tool. Modeled on the
HP_P1102w_Printer_Diagnostic_Tool used on ELITEBOOK (mjdeiter/printer_diagnostics)
but generalized: no single printer is hardcoded, and it adds LAN discovery.

Requires: python3-gi (already present on this box for power_widget.py), CUPS
client tools (lpstat/lpadmin/cancel/lpinfo). Network scan falls back
gracefully if nmap/avahi-browse aren't installed.

Deployed to: /home/meridith/Scripts/printer_toolkit.py
Launcher:    /home/meridith/Desktop/printer-toolkit.desktop
"""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango, Gdk

import subprocess
import shutil
import socket
import threading
import ipaddress
import re
import os

APP_TITLE = "Printer Toolkit"
APP_VERSION = "1.6"
APP_AUTHOR = "Matthew Deiter"
APP_WEBSITE = "https://matthewdeiter.com"
APP_REPO = "https://github.com/mjdeiter/printer-toolkit"

# (version, notes) — newest first. Add a line here with every version bump.
CHANGELOG = [
    ("1.6", "Fixed the socket/JetDirect URI in Add Network Printer: it was "
            "building socket://{ip}:99100 (stray extra digit, plus a stray "
            "'+' before the dict key) instead of the correct port 9100 — "
            "adding a raw/JetDirect printer was silently broken."),
    ("1.5", "Network scan now reports MAC addresses (nmap path runs sudo -n "
            "so it ARP-scans the subnet; manual-sweep fallback looks up each "
            "host's MAC via ip neigh/arp). Replaces the standalone "
            "find-printers.sh script on the Surface, which did the same "
            "scan on its own."),
    ("1.4", "Published to its own repo (github.com/mjdeiter/printer-toolkit); "
            "fixed the About dialog's Source link, which was still pointing "
            "at the unrelated HP_P1102w_Printer_Diagnostic_Tool repo."),
    ("1.3", "Added Select All / Copy / Clear buttons above the output pane; "
            "added this changelog to the About dialog."),
    ("1.2", "Default window size now scales to the screen's available work "
            "area instead of a fixed 760x560 (fixes an oversized window on "
            "high-DPI/small displays like the Surface). About dialog now "
            "credits the full author name and links to a personal site."),
    ("1.1", "Version bump prior to changelog tracking — history not recorded."),
    ("1.0", "Initial release: CUPS/network printer diagnostics, network scan, "
            "queue management, add/remove printers, CUPS log viewer."),
]

COMMON_PORTS = [(9100, "JetDirect/Raw"), (631, "IPP"), (515, "LPD")]
MDNS_SERVICES = ["_ipp._tcp", "_ipps._tcp", "_printer._tcp", "_pdl-datastream._tcp"]


def have(cmd):
    return shutil.which(cmd) is not None


def run(cmd, timeout=15, use_sudo=False):
    """Run a shell command, return (rc, output). use_sudo prefixes with sudo -n."""
    if use_sudo:
        cmd = "sudo -n " + cmd
    try:
        p = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return -1, f"[timed out after {timeout}s]"
    except Exception as e:
        return -1, f"[error: {e}]"


def local_subnet():
    """Best-effort guess of the local /24 to sweep, based on the default route iface IP."""
    rc, out = run("ip -4 -o addr show scope global | awk '{print $4}' | head -n1")
    if rc == 0 and out:
        try:
            iface = ipaddress.ip_interface(out.strip())
            net = ipaddress.ip_network(f"{iface.ip}/24", strict=False)
            return str(net)
        except Exception:
            pass
    return None


class PrinterToolkit(Gtk.Window):
    def __init__(self):
        super().__init__(title=APP_TITLE)
        w, h = self._sane_default_size(760, 560)
        self.set_default_size(w, h)
        self.set_border_width(10)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(root)

        header = Gtk.Label()
        header.set_markup(f"<b>{APP_TITLE}</b>  —  CUPS &amp; network printer troubleshooting")
        header.set_xalign(0)
        root.pack_start(header, False, False, 0)

        # Button grid
        grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        root.pack_start(grid, False, False, 0)

        buttons = [
            ("Full Diagnostic Scan", self.on_full_scan),
            ("Scan Network for Printers", self.on_scan_network),
            ("List CUPS Printers", self.on_list_printers),
            ("Show Print Queue", self.on_show_queue),
            ("Clear Stuck Jobs", self.on_clear_jobs),
            ("Restart CUPS Service", self.on_restart_cups),
            ("Test Printer Connection…", self.on_test_connection),
            ("Add Network Printer…", self.on_add_printer),
            ("Remove a Printer…", self.on_remove_printer),
            ("View CUPS Error Log", self.on_view_log),
        ]
        cols = 2
        for i, (label, handler) in enumerate(buttons):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", handler)
            grid.attach(btn, i % cols, i // cols, 1, 1)

        # About button, own row below the main grid, right-aligned
        about_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        about_btn = Gtk.Button(label="About")
        about_btn.connect("clicked", self.on_about)
        about_row.pack_end(about_btn, False, False, 0)
        root.pack_start(about_row, False, False, 0)

        # Small utility buttons for the output pane — sized to their
        # label, not stretched like the main action grid.
        output_toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        select_all_btn = Gtk.Button(label="Select All")
        select_all_btn.connect("clicked", self.on_select_all)
        copy_btn = Gtk.Button(label="Copy")
        copy_btn.connect("clicked", self.on_copy_output)
        clear_btn = Gtk.Button(label="Clear")
        clear_btn.connect("clicked", self.on_clear_output)
        output_toolbar.pack_start(select_all_btn, False, False, 0)
        output_toolbar.pack_start(copy_btn, False, False, 0)
        output_toolbar.pack_start(clear_btn, False, False, 0)
        root.pack_start(output_toolbar, False, False, 0)

        # Output area
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self.output = Gtk.TextView()
        self.output.set_editable(False)
        self.output.set_monospace(True)
        self.output.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.buf = self.output.get_buffer()
        scroll.add(self.output)
        root.pack_start(scroll, True, True, 0)

        # Status bar
        self.status = Gtk.Label(label="Ready.")
        self.status.set_xalign(0)
        root.pack_start(self.status, False, False, 0)

        self.log(f"{APP_TITLE} ready.\n")
        self._check_prereqs()

    def _sane_default_size(self, want_w, want_h):
        """Cap the requested window size to a fraction of the monitor's
        work area (in logical/scaled pixels), so small or high-DPI screens
        like the Surface don't get handed a window that swallows the
        whole display. Falls back to the requested size if anything about
        the monitor query fails."""
        try:
            display = Gdk.Display.get_default()
            monitor = display.get_primary_monitor() or display.get_monitor(0)
            geo = monitor.get_workarea()
            max_w = int(geo.width * 0.65)
            max_h = int(geo.height * 0.65)
            return min(want_w, max_w), min(want_h, max_h)
        except Exception:
            return want_w, want_h

    # ---------- helpers ----------

    def log(self, text, clear=False):
        def _do():
            if clear:
                self.buf.set_text("")
            end = self.buf.get_end_iter()
            self.buf.insert(end, text if text.endswith("\n") else text + "\n")
            self.output.scroll_to_iter(self.buf.get_end_iter(), 0, False, 0, 0)
        GLib.idle_add(_do)

    def set_status(self, text):
        GLib.idle_add(self.status.set_text, text)

    def run_async(self, fn, *args):
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _check_prereqs(self):
        missing = []
        for cmd in ("lpstat", "lpadmin", "cancel", "lpinfo"):
            if not have(cmd):
                missing.append(cmd)
        if missing:
            self.log(
                "WARNING: CUPS client tools missing: " + ", ".join(missing) + "\n"
                "  Install with: sudo apt-get install cups cups-client\n"
            )
        if not have("nmap") and not have("avahi-browse"):
            self.log(
                "NOTE: Neither nmap nor avahi-browse is installed — network scan will "
                "fall back to a plain port sweep (slower, no printer names).\n"
                "  For better results: sudo apt-get install nmap avahi-utils\n"
            )

    # ---------- actions ----------

    def on_select_all(self, _btn):
        start = self.buf.get_start_iter()
        end = self.buf.get_end_iter()
        self.buf.select_range(start, end)
        self.output.grab_focus()
        self.set_status("Selected all output.")

    def on_copy_output(self, _btn):
        start = self.buf.get_start_iter()
        end = self.buf.get_end_iter()
        text = self.buf.get_text(start, end, False)
        clipboard = Gtk.Clipboard.get_default(Gdk.Display.get_default())
        clipboard.set_text(text, -1)
        self.set_status("Output copied to clipboard.")

    def on_clear_output(self, _btn):
        self.buf.set_text("")
        self.set_status("Output cleared.")

    def on_about(self, _btn):
        dialog = Gtk.AboutDialog(transient_for=self, modal=True)
        dialog.set_program_name(APP_TITLE)
        dialog.set_version(APP_VERSION)
        dialog.set_authors([APP_AUTHOR])
        dialog.set_website(APP_WEBSITE)
        dialog.set_website_label("matthewdeiter.com")
        dialog.set_comments(
            "CUPS & network printer troubleshooting for the Surface.\n"
            f"Source: {APP_REPO}"
        )
        CHANGELOG_RESPONSE = 100
        dialog.add_button("Changelog", CHANGELOG_RESPONSE)
        while True:
            response = dialog.run()
            if response == CHANGELOG_RESPONSE:
                self._show_changelog(dialog)
                continue
            break
        dialog.destroy()

    def _show_changelog(self, parent):
        text = "\n\n".join(f"v{ver}  —  {notes}" for ver, notes in CHANGELOG)
        dialog = Gtk.Dialog(title=f"{APP_TITLE} — Changelog", transient_for=parent, modal=True)
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        box = dialog.get_content_area()
        box.set_border_width(10)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_width(420)
        scroll.set_min_content_height(300)
        label = Gtk.Label(label=text)
        label.set_xalign(0)
        label.set_yalign(0)
        label.set_line_wrap(True)
        label.set_margin_start(6)
        label.set_margin_end(6)
        scroll.add(label)
        box.add(scroll)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def on_full_scan(self, _btn):
        self.set_status("Running full diagnostic scan…")
        self.run_async(self._full_scan)

    def _full_scan(self):
        self.log("=" * 60 + "\nFULL DIAGNOSTIC SCAN\n" + "=" * 60, clear=True)

        # 1. CUPS service state
        self.log("\n[1] CUPS service status:")
        if have("service"):
            rc, out = run("service cups status", use_sudo=True)
            self.log(out if out else f"(exit {rc})")
        else:
            self.log("  'service' command not found.")

        # 2. Configured queues + default
        self.log("\n[2] Configured printers:")
        if have("lpstat"):
            rc, out = run("lpstat -p -d")
            self.log(out if out else "  No printers configured.")
        else:
            self.log("  lpstat not available — CUPS client tools not installed.")

        # 3. Duplicate-queue-same-IP check (mirrors the ELITEBOOK P1102w tool's check)
        self.log("\n[3] Checking for duplicate queues pointing at the same device:")
        self._check_duplicate_queues()

        # 4. Stuck / pending jobs
        self.log("\n[4] Print queue / pending jobs:")
        if have("lpstat"):
            rc, out = run("lpstat -o")
            self.log(out if out else "  No pending jobs.")

        # 5. Recent CUPS errors
        self.log("\n[5] Last 15 lines of CUPS error log:")
        rc, out = run("sudo -n tail -n 15 /var/log/cups/error_log 2>/dev/null")
        self.log(out if out else "  (log empty or unreadable)")

        # 6. Quick connectivity check for each configured device URI
        self.log("\n[6] Connectivity to each configured printer's device URI:")
        self._check_all_device_uris()

        self.log("\n" + "=" * 60 + "\nSCAN COMPLETE\n" + "=" * 60)
        self.set_status("Full diagnostic scan complete.")

    def _check_duplicate_queues(self):
        rc, out = run("lpstat -v")
        if rc != 0 or not out:
            self.log("  Could not read device URIs (lpstat -v).")
            return
        ip_to_queues = {}
        for line in out.splitlines():
            m = re.search(r"^device for ([^:]+):\s*(\S+)", line)
            if not m:
                continue
            queue, uri = m.group(1), m.group(2)
            ip_m = re.search(r"://([^/:]+)", uri)
            key = ip_m.group(1) if ip_m else uri
            ip_to_queues.setdefault(key, []).append(queue)
        dupes = {k: v for k, v in ip_to_queues.items() if len(v) > 1}
        if dupes:
            for target, queues in dupes.items():
                self.log(f"  NOTE: {target} is targeted by multiple queues: {', '.join(queues)}")
                self.log("        (informational — jobs may be misrouted if the wrong one is default)")
        else:
            self.log("  None found — each printer target has exactly one queue.")

    def _check_all_device_uris(self):
        rc, out = run("lpstat -v")
        if rc != 0 or not out:
            self.log("  No device URIs to check.")
            return
        for line in out.splitlines():
            m = re.search(r"^device for ([^:]+):\s*(\S+)", line)
            if not m:
                continue
            queue, uri = m.group(1), m.group(2)
            ip_m = re.search(r"://([^/:]+)", uri)
            if not ip_m:
                self.log(f"  {queue}: {uri} (not a network URI, skipping)")
                continue
            host = ip_m.group(1)
            reachable = self._ping(host)
            open_ports = [name for port, name in COMMON_PORTS if self._port_open(host, port)]
            self.log(
                f"  {queue} -> {host}: "
                f"{'reachable' if reachable else 'NOT REACHABLE (ping failed)'}, "
                f"open ports: {', '.join(open_ports) if open_ports else 'none of 9100/631/515'}"
            )

    def on_scan_network(self, _btn):
        self.set_status("Scanning network for printers… this can take a minute")
        self.run_async(self._scan_network)

    def _scan_network(self):
        self.log("Scanning for network printers...\n", clear=True)

        found_mdns = False
        if have("avahi-browse"):
            self.log("mDNS/Bonjour discovery (avahi-browse):")
            for svc in MDNS_SERVICES:
                rc, out = run(f"avahi-browse -rt {svc}", timeout=12)
                if out and "Failed" not in out:
                    hits = [l for l in out.splitlines() if l.strip().startswith("=")]
                    if hits:
                        found_mdns = True
                        self.log(f"  {svc}:")
                        for l in hits:
                            self.log(f"    {l.strip()}")
            if not found_mdns:
                self.log("  No mDNS printer services found.")
            self.log("")
        else:
            self.log("avahi-browse not installed — skipping mDNS discovery "
                      "(sudo apt-get install avahi-utils for names + service info).\n")

        subnet = local_subnet()
        if not subnet:
            self.log("Could not determine local subnet — skipping port sweep.")
            self.set_status("Network scan complete (partial — no subnet detected).")
            return

        self.log(f"Port-sweeping {subnet} for printer ports (9100, 631, 515)...")
        if have("nmap"):
            ports = ",".join(str(p) for p, _ in COMMON_PORTS)
            # sudo -n so nmap ARP-scans the local subnet and reports each
            # host's MAC address alongside its open ports, not just the ports.
            rc, out = run(f"nmap -T4 --open -p {ports} {subnet}", timeout=90, use_sudo=True)
            self.log(out if out else "  nmap returned nothing.")
        else:
            self.log("  nmap not installed — doing a slower manual sweep "
                      "(sudo apt-get install nmap for a much faster scan).")
            self._manual_sweep(subnet)

        self.log("\nDone.")
        self.set_status("Network scan complete.")

    def _manual_sweep(self, subnet):
        net = ipaddress.ip_network(subnet, strict=False)
        hits = []
        for host in net.hosts():
            host = str(host)
            for port, name in COMMON_PORTS:
                if self._port_open(host, port, timeout=0.15):
                    mac = self._get_mac(host)
                    hits.append(f"  {host}:{port} open ({name}) — MAC {mac}")
        if hits:
            for h in hits:
                self.log(h)
        else:
            self.log("  No hosts found with printer ports open.")

    def _get_mac(self, host):
        """Look up a host's MAC in the local ARP/neighbor table (populated
        by the TCP connect just made to it in _port_open)."""
        rc, out = run(f"ip neigh show {host}")
        for line in out.splitlines():
            parts = line.split()
            if "lladdr" in parts:
                return parts[parts.index("lladdr") + 1]
        rc, out = run(f"arp -n {host}")
        for line in out.splitlines():
            for tok in line.split():
                if re.fullmatch(r"([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", tok):
                    return tok
        return "(unknown)"

    def _ping(self, host, timeout=2):
        rc, _ = run(f"ping -c 1 -W {timeout} {host}", timeout=timeout + 2)
        return rc == 0

    def _port_open(self, host, port, timeout=0.5):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            return False

    def on_list_printers(self, _btn):
        self.set_status("Listing printers…")
        self.run_async(self._list_printers)

    def _list_printers(self):
        self.log("CUPS printers:\n", clear=True)
        rc, out = run("lpstat -p -d -l")
        self.log(out if out else "No printers configured.")
        self.set_status("Done.")

    def on_show_queue(self, _btn):
        self.set_status("Checking print queue…")
        self.run_async(self._show_queue)

    def _show_queue(self):
        self.log("Pending print jobs:\n", clear=True)
        rc, out = run("lpstat -o")
        self.log(out if out else "No pending jobs — queue is empty.")
        self.set_status("Done.")

    def on_clear_jobs(self, _btn):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Clear all print jobs on every queue?",
        )
        dialog.format_secondary_text(
            "This cancels every pending job on every printer (cancel -a). "
            "Use this to clear a stuck queue."
        )
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YeS:
            self.set_status("Clearing print jobs…")
            self.run_async(self._clear_jobs)

    def _clear_jobs(self):
        self.log("Clearing all print jobs...\n", clear=True)
        rc, out = run("cancel -a", use_sudo=True)
        self.log(out if out else "All jobs cancelled.")
        self.log("\nRe-checking queue:")
        rc, out = run("lpstat -o")
        self.log(out if out else "Queue is now empty.")
        self.set_status("Jobs cleared.")

    def on_restart_cups(self, _btn):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Restart the CUPS print service?",
        )
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            self.set_status("Restarting CUPS…")
            self.run_async(self._restart_cups)

    def _restart_cups(self):
        self.log("Restarting CUPS (service cups restart)...\n", clear=True)
        rc, out = run("service cups restart", use_sudo=True)
        self.log(out if out else f"Exit code: {rc}")
        rc, out = run("service cups status", use_sudo=True)
        self.log("\nStatus after restart:\n" + out)
        self.set_status("CUPS restarted.")

    def on_test_connection(self, _btn):
        dialog = Gtk.Dialog(title="Test Printer Connection", transient_for=self, flags=0)
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Test", Gtk.ResponseType.OK,
        )
        box = dialog.get_content_area()
        box.set_spacing(6)
        box.set_border_width(10)
        label = Gtk.Label(label="Printer IP address or hostname:")
        entry = Gtk.Entry()
        entry.set_activates_default(True)
        dialog.set_default_response(Gtk.ResponseType.OK)
        box.add(label)
        box.add(entry)
        dialog.show_all()
        response = dialog.run()
        host = entry.get_text().strip()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and host:
            self.set_status(f"Testing {host}…")
            self.run_async(self._test_connection, host)

    def _test_connection(self, host):
        self.log(f"Testing connection to {host}...\n", clear=True)
        reachable = self._ping(host)
        self.log(f"Ping: {'OK' if reachable else 'FAILED — host unreachable'}")
        for port, name in COMMON_PORTS:
            open_ = self._port_open(host, port, timeout=2)
            self.log(f"Port {port} ({name}): {'OPEN' if open_ else 'closed/filtered'}")
        self.set_status("Connection test complete.")

    def on_add_printer(self, _btn):
        dialog = Gtk.Dialog(title="Add Network Printer", transient_for=self, flags=0)
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Add", Gtk.ResponseType.OK,
        )
        box = dialog.get_content_area()
        box.set_spacing(6)
        box.set_border_width(10)

        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        box.add(grid)

        name_entry = Gtk.Entry()
        ip_entry = Gtk.Entry()
        proto_combo = Gtk.ComboBoxText()
        for p in ["socket (raw/JetDirect, port 9100)", "ipp (port 631)", "lpd (port 515)"]:
            proto_combo.append_text(p)
        proto_combo.set_active(0)

        for i, (label_text, widget) in enumerate([
            ("Queue name (no spaces):", name_entry),
            ("Printer IP address:", ip_entry),
            ("Protocol:", proto_combo),
        ]):
            lbl = Gtk.Label(label=label_text)
            lbl.set_xalign(0)
            grid.attach(lbl, 0, i, 1, 1)
            grid.attach(widget, 1, i, 1, 1)

        dialog.show_all()
        response = dialog.run()
        name = name_entry.get_text().strip()
        ip = ip_entry.get_text().strip()
        proto_idx = proto_combo.get_active()
        dialog.destroy()

        if response != Gtk.ResponseType.OK or not name or not ip:
            return

        uri = {
            0: f"socket://{ip}:9100",
            1: f"ipp://{ip}/ipp/print",
            2: f"lpd://{ip}/queue",
        }[proto_idx]

        self.set_status(f"Adding printer {name}…")
        self.run_async(self._add_printer, name, uri)

    def _add_printer(self, name, uri):
        self.log(f"Adding printer '{name}' at {uri} (driverless/IPP-everywhere)...\n", clear=True)
        cmd = f"lpadmin -p '{name}' -E -v '{uri}' -m everywhere"
        rc, out = run(cmd, use_sudo=True)
        if rc == 0:
            self.log(f"Added. Setting as default is optional — not done automatically.")
        else:
            self.log(f"Failed (exit {rc}):\n{out}\n\n"
                      "If 'everywhere' driver isn't supported by this printer, try again "
                      "specifying a real PPD with -m <driver>, or check 'lpinfo -m' for options.")
        rc, out = run("lpstat -p -d")
        self.log("\nCurrent printers:\n" + out)
        self.set_status("Done.")

    def on_remove_printer(self, _btn):
        rc, out = run("lpstat -p")
        names = re.findall(r"^printer (\S+)", out, re.MULTILINE)
        if not names:
            self.log("No printers configured to remove.", clear=True)
            return
        dialog = Gtk.Dialog(title="Remove a Printer", transient_for=self, flags=0)
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Remove", Gtk.ResponseType.OK,
        )
        box = dialog.get_content_area()
        box.set_spacing(6)
        box.set_border_width(10)
        box.add(Gtk.Label(label="Select printer to remove:"))
        combo = Gtk.ComboBoxText()
        for n in names:
            combo.append_text(n)
        combo.set_active(0)
        box.add(combo)
        dialog.show_all()
        response = dialog.run()
        name = combo.get_active_text()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and name:
            self.set_status(f"Removing {name}…")
            self.run_async(self._remove_printer, name)

    def _remove_printer(self, name):
        self.log(f"Removing printer '{name}'...\n", clear=True)
        rc, out = run(f"lpadmin -x '{name}'", use_sudo=True)
        self.log(out if out else ("Removed." if rc == 0 else f"Failed (exit {rc})"))
        rc, out = run("lpstat -p -d")
        self.log("\nRemaining printers:\n" + (out or "(none)"))
        self.set_status("Done.")

    def on_view_log(self, _btn):
        self.set_status("Reading CUPS error log…")
        self.run_async(self._view_log)

    def _view_log(self):
        self.log("Last 50 lines of /var/log/cups/error_log:\n", clear=True)
        rc, out = run("tail -n 50 /var/log/cups/error_log", use_sudo=True)
        self.log(out if out else "(log empty or not found)")
        self.set_status("Done.")


def main():
    win = PrinterToolkit()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
