import sys
import socket

s = socket.socket()
s.connect(("127.0.0.1", 9999))
s.send(sys.argv[1].encode())
s.close()
