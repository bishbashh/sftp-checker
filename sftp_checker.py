#!/usr/bin/env python3
"""
SFTP Checker - Connect via proxy and list directories.
Mirrors the FileZilla "Generic proxy" + "SFTP site" setup.

Requirements:
    pip install paramiko PySocks
"""

import getpass
import socket
import sys

try:
    import paramiko
except ImportError:
    sys.exit("Missing dependency: pip install paramiko")

try:
    import socks
except ImportError:
    sys.exit("Missing dependency: pip install PySocks")

# ── proxy type labels (matches FileZilla UI order) ───────────────────────────
PROXY_TYPES = {
    "1": ("HTTP/1.1 CONNECT", socks.HTTP),
    "2": ("SOCKS 4",          socks.SOCKS4),
    "3": ("SOCKS 5",          socks.SOCKS5),
}

# ─────────────────────────────────────────────────────────────────────────────

def inp(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"  {label}{suffix}: ").strip()
    return val if val else default

def secret(label: str) -> str:
    return getpass.getpass(f"  {label}: ")

def section(title: str):
    print()
    print(f"─── {title} " + "─" * (50 - len(title)))

# ─────────────────────────────────────────────────────────────────────────────

def gather_inputs():
    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║          SFTP Checker  (FileZilla style)         ║")
    print("╚══════════════════════════════════════════════════╝")

    # ── Generic Proxy ────────────────────────────────────────────────────────
    section("Generic Proxy  (Connection → Generic proxy)")
    print()
    print("    Type of generic proxy:")
    for k, (label, _) in PROXY_TYPES.items():
        print(f"      {k}. {label}")
    print()
    ptype_key = inp("Proxy type", "1")
    if ptype_key not in PROXY_TYPES:
        sys.exit("[ERROR] Invalid proxy type selection.")
    proxy_label, proxy_type = PROXY_TYPES[ptype_key]

    proxy_host = inp("Proxy host")
    proxy_port = int(inp("Proxy port", "8080"))
    proxy_user = inp("Proxy user (leave blank if none)")
    proxy_pass = secret("Proxy password") if proxy_user else ""

    # ── SFTP Site ─────────────────────────────────────────────────────────────
    section("SFTP Site  (New Site → SFTP – SSH File Transfer Protocol)")
    sftp_host = inp("Host")
    sftp_port = int(inp("Port", "22"))
    sftp_user = inp("User")
    sftp_pass = secret("Password")

    return (
        proxy_type, proxy_label, proxy_host, proxy_port,
        proxy_user or None, proxy_pass or None,
        sftp_host, sftp_port, sftp_user, sftp_pass,
    )

# ─────────────────────────────────────────────────────────────────────────────

def connect_and_list(
    proxy_type, proxy_label, proxy_host, proxy_port, proxy_user, proxy_pass,
    sftp_host, sftp_port, sftp_user, sftp_pass,
):
    section("Connecting")
    print()
    print(f"  Proxy  : [{proxy_label}]  {proxy_host}:{proxy_port}"
          + (f"  user={proxy_user}" if proxy_user else ""))
    print(f"  Target : {sftp_host}:{sftp_port}  user={sftp_user}")
    print()

    # 1. Proxied socket ────────────────────────────────────────────────────────
    sock = socks.socksocket()
    sock.set_proxy(proxy_type, proxy_host, proxy_port, True, proxy_user, proxy_pass)
    sock.settimeout(20)

    print("  [..] Opening proxy tunnel...", end=" ", flush=True)
    try:
        sock.connect((sftp_host, sftp_port))
    except socks.ProxyConnectionError as e:
        print(f"\n  [FAIL] Cannot reach proxy: {e}")
        return False
    except socks.GeneralProxyError as e:
        print(f"\n  [FAIL] Proxy rejected tunnel: {e}")
        return False
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        print(f"\n  [FAIL] Socket error: {e}")
        return False
    print("OK")

    # 2. SSH transport ─────────────────────────────────────────────────────────
    print("  [..] SSH handshake...", end=" ", flush=True)
    transport = paramiko.Transport(sock)
    transport.banner_timeout = 20
    transport.auth_timeout   = 20
    try:
        transport.connect(username=sftp_user, password=sftp_pass)
    except paramiko.AuthenticationException:
        print("\n  [FAIL] Authentication failed – wrong username or password")
        transport.close()
        return False
    except paramiko.SSHException as e:
        print(f"\n  [FAIL] SSH error: {e}")
        transport.close()
        return False
    print("OK")

    # 3. SFTP listing ──────────────────────────────────────────────────────────
    print("  [..] Opening SFTP channel...", end=" ", flush=True)
    sftp = paramiko.SFTPClient.from_transport(transport)
    print("OK")

    try:
        section("Remote directory listing")
        print()
        entries = sftp.listdir_attr(".")
        if not entries:
            print("  (empty directory)")
        else:
            # sort: dirs first, then files, alphabetical
            entries.sort(key=lambda e: (not bool(e.st_mode and e.st_mode & 0o40000),
                                        e.filename.lower()))
            col_w = max(len(e.filename) for e in entries) + 2
            print(f"  {'TYPE':<5}  {'SIZE':>12}  {'NAME'}")
            print(f"  {'─'*5}  {'─'*12}  {'─'*col_w}")
            for e in entries:
                is_dir  = bool(e.st_mode and e.st_mode & 0o40000)
                ftype   = "DIR" if is_dir else "FILE"
                sz      = "-" if is_dir else f"{e.st_size:,}"
                print(f"  {ftype:<5}  {sz:>12}  {e.filename}")
    finally:
        sftp.close()
        transport.close()

    print()
    print("  [SUCCESS] Connection OK – listing complete.")
    return True

# ─────────────────────────────────────────────────────────────────────────────

def main():
    args = gather_inputs()
    connect_and_list(*args)
    print()
    input("Press Enter to exit...")

if __name__ == "__main__":
    main()
