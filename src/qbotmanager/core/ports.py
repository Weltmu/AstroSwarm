import socket


def is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", int(port)))
            return True
        except OSError:
            return False


def find_free_port(preferred: int, max_tries: int = 200) -> int:
    port = int(preferred)
    for _ in range(max_tries):
        if is_port_free(port):
            return port
        port += 1
    return port