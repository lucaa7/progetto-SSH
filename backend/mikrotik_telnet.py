import time
from netmiko.terminal_server.terminal_server import TerminalServerTelnet


class MikrotikRouterOSTelnet(TerminalServerTelnet):

    def telnet_login(self, *args, **kwargs):
        print("[DEBUG] telnet_login avviato")
        delay = 1.0
        time.sleep(delay)
        output = ""

        for _ in range(30):
            output += self.read_channel()
            print(f"[DEBUG] buffer: {repr(output[-80:])}")

            if "Login:" in output:
                print("[DEBUG] trovato Login:")
                self.write_channel(self.username + "\n")
                time.sleep(delay)
                output = ""

            elif "Password:" in output:
                print("[DEBUG] trovato Password:")
                self.write_channel(self.password + "\n")
                time.sleep(delay)
                output = ""

            elif "@" in output and "] >" in output:
                print("[DEBUG] trovato prompt MikroTik")
                return output

            time.sleep(0.5)

        raise Exception(f"Login fallito. Ultimo output: {repr(output)}")

    def session_preparation(self):
        print("[DEBUG] session_preparation avviata")
        self.telnet_login()
        time.sleep(1.0)
        print("[DEBUG] clear_buffer...")
        self.clear_buffer()
        print("[DEBUG] session_preparation completata")