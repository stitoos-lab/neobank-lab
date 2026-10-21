import socket
import json

def scan_ports(ip, ports):
    results = {"cible": ip, "resultats": {}}

    for port in ports:
        # AF_INET = IPv4, sock_stream = tcp
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0) #je skip le port apres 1 seconde

        #connect_ex renvoie 0 si le 3 way handshake est reussi
        if s.connect_ex((ip, port)) == 0:
            banner = "Aucune banniere"
            try :
                #lecture des premieres octets (bannner grabbing)
                banner = s.recv(1024).decode('utf-8', errors='ignore').strip()
            except :
                pass

            results["resultats"][port] = {"etat": "ouvert", "banniere": banner}

        else :
            results["resultats"][port] = {"etat": "ferme"}

        s.close()

    return results

if __name__ == "__main__":
    #je cible l'interface locale (localhost) pour tester
    target_ips = "127.0.0.1"
    # je teste les ports ssh(22), http(80), https(443), postgresql(5432)
    ports_to_test = [22,80,443,5432,8000]

    data = scan_ports(target_ips, ports_to_test)
    print(json.dumps(data, indent=4))