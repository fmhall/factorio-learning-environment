import subprocess
import json
from typing import List


def get_local_container_ips() -> tuple[List[str], List[int], List[int]]:
    """Get addresses and host ports of running local Factorio containers.

    Returns (ips, udp_ports, tcp_ports), sorted together by RCON (tcp) port so
    that index i in each list refers to the same container. All lists are empty
    when no containers are running.
    """
    cmd = ["docker", "ps", "--filter", "name=factorio_", "--format", '"{{.ID}}"']
    result = subprocess.run(cmd, capture_output=True, text=True)
    container_ids = [cid.strip('"') for cid in result.stdout.strip().split("\n")]

    if not container_ids or container_ids[0] == "":
        return [], [], []

    containers = []
    for container_id in container_ids:
        cmd = ["docker", "inspect", container_id]
        result = subprocess.run(cmd, capture_output=True, text=True)
        container_info = json.loads(result.stdout)

        ports = container_info[0]["NetworkSettings"]["Ports"]
        udp_port = None
        tcp_port = None
        for port, bindings in ports.items():
            if "/udp" in port and bindings:
                udp_port = int(bindings[0]["HostPort"])
            if "/tcp" in port and bindings:
                tcp_port = int(bindings[0]["HostPort"])

        if tcp_port is None:
            # Container without an RCON mapping is unusable; skip it.
            continue
        containers.append(("127.0.0.1", udp_port, tcp_port))

    # Keep the (ip, udp, tcp) triples correlated: sort by RCON port.
    containers.sort(key=lambda c: c[2])
    ips = [c[0] for c in containers]
    udp_ports = [c[1] for c in containers]
    tcp_ports = [c[2] for c in containers]
    return ips, udp_ports, tcp_ports


if __name__ == "__main__":
    ips, udp_ports, tcp_ports = get_local_container_ips()
    if ips:
        print("Local Factorio container addresses:")
        for ip, udp, tcp in zip(ips, udp_ports, tcp_ports):
            print(f"{ip} rcon=tcp/{tcp} game=udp/{udp}")
    else:
        print("No local Factorio containers found.")
