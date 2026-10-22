import argparse
import socket
import json

def scan_ports(ip, ports, timeout=1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
        #connect_ex renvoie 0 si le 3 way handshake est reussi
        if s.connect_ex((ip, ports)) != 0:
            return {"etat": "ferme"}
        banner = "Acune banniere"
        try:
             data = s.recv(1024).decode("utf-8", errors="ignore").strip()
             if data:
                  banner = data
        except OSError:
            pass
        return {"etat": "ouvert", "banniere": banner}

def parse_ports(text):
    ports = []
    for part in text.split(","):
         if "-" in part :
              start, end = part.split("-")
              ports.extend(range(int(start), int(end)+1))
         else:
              ports.append(int(part))
    return ports


def main():
    parser = argparse.ArgumentParser(description="Scanner de ports TCP")
    parser.add_argument("ip", help="Adresse IP à scanner")
    parser.add_argument("-p", "--ports", default="22,80,443,5432,8080", help="ports séparés par des virgules ou plages (ex: 20-25,80,443)")
    parser.add_argument("-t", "--timeout", type=int, default=1, help="Timeout en secondes pour chaque port")
    args = parser.parse_args()

    results = {"cible" : args.ip, "resultats": {}}
    for port in parse_ports(args.ports):
        results["resultats"][port] = scan_ports(args.ip, port, args.timeout)
    print(json.dumps(results, indent=4))


if __name__ == "__main__":
    main()