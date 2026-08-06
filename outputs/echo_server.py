#!/usr/bin/env python3
import socket

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(("127.0.0.1", 8767))
s.listen(1)
print("Listening on 8767")
conn, addr = s.accept()
data = conn.recv(4096)
print("RECEIVED:")
print(data.decode("utf-8", errors="replace"))
conn.send(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nOK")
conn.close()
