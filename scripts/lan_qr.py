"""Print the addresses to open Local Scan and a QR code for the phone (called by run.bat)."""
import socket
import sys

import qrcode

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(("10.255.255.255", 1))  # no packet is sent; this just picks the outbound network interface
    ip = s.getsockname()[0]
except OSError:
    ip = "127.0.0.1"
finally:
    s.close()
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8010  # run.bat -Dev passes 5173, the Vite dev server
url = f"http://{ip}:{port}"
print(f"\n  On this PC:   http://localhost:{port}\n  On the phone: {url}  (same Wi-Fi)\n")
q = qrcode.QRCode(border=1)
q.add_data(url)
try:
    q.print_ascii(invert=True)
except UnicodeEncodeError:  # output is piped through a legacy code page that has no block characters
    for row in q.get_matrix():
        print("".join("##" if cell else "  " for cell in row))
